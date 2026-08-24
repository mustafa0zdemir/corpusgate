from __future__ import annotations

import argparse
import hashlib
import json
import resource
import sys
import tempfile
from pathlib import Path
from statistics import mean
from time import perf_counter
from uuid import NAMESPACE_URL, uuid5

from app.chunking.base import ChunkDraft
from app.core.config import get_settings
from app.core.database import Database
from app.models.document import Document, DocumentStatus
from app.repositories.sqlite import SQLiteDocumentRepository
from app.repositories.sqlite_fts import SQLiteFtsSearchIndex
from app.semantic.runtime import create_semantic_runtime
from app.services.search import FullTextSearchService
from app.services.semantic_index import SemanticIndexService


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare lexical, semantic, and hybrid retrieval.")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    dataset = json.loads(arguments.dataset.read_text("utf-8"))
    report = evaluate(dataset)
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if arguments.output:
        arguments.output.write_text(serialized + "\n", "utf-8")
    print(serialized)


def evaluate(dataset: dict) -> dict:
    base_settings = get_settings()
    with tempfile.TemporaryDirectory(prefix="corpusgate-evaluation-") as temporary:
        root = Path(temporary)
        settings = base_settings.model_copy(
            update={
                "semantic_enabled": True,
                "data_dir": root,
                "database_url": f"sqlite:///{root / 'evaluation.db'}",
                "vector_collection": f"{base_settings.vector_collection}_evaluation",
                "max_results_per_document": 0,
            }
        )
        database = Database(settings)
        database.create_schema()
        runtime = create_semantic_runtime(settings)
        if not runtime.available:
            raise RuntimeError("The semantic runtime is unavailable for evaluation.")
        indexing = {"documents": 0, "chunks": 0, "batch_embedding_ms": 0.0}
        try:
            with database.session_factory() as session:
                repository = SQLiteDocumentRepository(session)
                for source in dataset["documents"]:
                    document = _add_document(repository, source)
                    started = perf_counter()
                    result = SemanticIndexService(settings, repository, runtime).sync_document(
                        document
                    )
                    indexing["documents"] += 1
                    indexing["chunks"] += result.embedded_chunks
                    indexing["batch_embedding_ms"] += round((perf_counter() - started) * 1000, 3)
                modes = {
                    mode: _evaluate_mode(
                        dataset["queries"],
                        mode,
                        FullTextSearchService(
                            settings,
                            repository,
                            SQLiteFtsSearchIndex(session),
                            runtime,
                        ),
                    )
                    for mode in ("lexical", "semantic", "hybrid")
                }
            return {
                "dataset": {
                    "documents": len(dataset["documents"]),
                    "queries": len(dataset["queries"]),
                },
                "model": {
                    "name": runtime.provider.model_name,
                    "version": runtime.provider.model_version,
                    "dimension": runtime.provider.dimension,
                },
                "indexing": indexing,
                "modes": modes,
                "process_peak_rss_mb": _peak_rss_mb(),
                "vector_index_bytes": None,
                "measurement_notes": [
                    "Times and memory are measurements from this run, not product guarantees.",
                    "Qdrant does not expose per-collection disk bytes through this adapter; "
                    "measure the vector volume on the deployment host.",
                ],
            }
        finally:
            runtime.close()
            database.dispose()


def _add_document(repository: SQLiteDocumentRepository, source: dict) -> Document:
    content = "\n\n".join(
        f"# {chunk['heading']}\n\n{chunk['content']}" for chunk in source["chunks"]
    )
    document = Document(
        id=str(uuid5(NAMESPACE_URL, f"corpusgate-evaluation:{source['name']}")),
        original_filename=source["name"],
        content_type="text/markdown",
        extension="md",
        file_size=len(content.encode()),
        sha256=hashlib.sha256(content.encode()).hexdigest(),
        storage_path=f"evaluation/{source['name']}",
        status=DocumentStatus.pending.value,
    )
    repository.create(document)
    drafts = []
    position = 0
    for index, chunk in enumerate(source["chunks"]):
        text = chunk["content"]
        drafts.append(ChunkDraft(index, chunk["heading"], text, position, position + len(text), 0))
        position += len(text) + 2
    repository.mark_ready(
        document,
        markdown_path=f"evaluation/{source['name']}",
        markdown_chars=len(content),
        markdown_tokens=max(1, len(content) // 4),
        chunks=drafts,
    )
    return document


def _evaluate_mode(queries: list[dict], mode: str, service: FullTextSearchService) -> dict:
    rows = []
    for item in queries:
        page = service.search(
            item["query"],
            retrieval_mode=mode,
            top_k=5,
            max_tokens=500,
            max_chars=2_000,
        )
        actual = [f"{hit.document_name}#{hit.heading}" for hit in page.items]
        expected = set(item["expected"])
        ranks = [index for index, value in enumerate(actual, 1) if value in expected]
        recall = len(expected.intersection(actual)) / len(expected) if expected else int(not ranks)
        rows.append(
            {
                "id": item["id"],
                "expected": item["expected"],
                "returned": actual,
                "recall_at_5": recall,
                "reciprocal_rank": 1 / min(ranks) if ranks else 0.0,
                "hit": bool(ranks) if expected else not actual,
                "latency_ms": page.metrics.search_ms,
                "returned_tokens": page.metrics.returned_estimated_tokens,
                "actual_mode": page.retrieval_mode,
                "lexical_search_ms": page.metrics.lexical_search_ms,
                "query_embedding_ms": page.metrics.query_embedding_ms,
                "semantic_search_ms": page.metrics.semantic_search_ms,
                "hybrid_search_ms": page.metrics.hybrid_search_ms,
            }
        )
    return {
        "recall_at_5": mean(row["recall_at_5"] for row in rows),
        "mrr": mean(row["reciprocal_rank"] for row in rows),
        "hit_rate": mean(row["hit"] for row in rows),
        "average_query_ms": mean(row["latency_ms"] for row in rows),
        "average_returned_tokens": mean(row["returned_tokens"] for row in rows),
        "average_lexical_search_ms": _optional_mean(rows, "lexical_search_ms"),
        "average_query_embedding_ms": _optional_mean(rows, "query_embedding_ms"),
        "average_semantic_search_ms": _optional_mean(rows, "semantic_search_ms"),
        "average_hybrid_search_ms": _optional_mean(rows, "hybrid_search_ms"),
        "queries": rows,
    }


def _optional_mean(rows: list[dict], key: str) -> float | None:
    values = [row[key] for row in rows if row[key] is not None]
    return mean(values) if values else None


def _peak_rss_mb() -> float:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
    return round(value / divisor, 3)


if __name__ == "__main__":
    main()
