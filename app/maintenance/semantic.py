from __future__ import annotations

import argparse
import json

from app.core.config import get_settings
from app.core.database import Database
from app.repositories.sqlite import SQLiteDocumentRepository
from app.semantic.runtime import create_semantic_runtime
from app.services.semantic_index import SemanticIndexService


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage the private semantic index.")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("download-model", help="Preload the configured local model cache.")
    reindex = subcommands.add_parser("reindex", help="Synchronize all ready document chunks.")
    reindex.add_argument(
        "--force",
        action="store_true",
        help="Delete document vectors before rebuilding them.",
    )
    arguments = parser.parse_args()
    settings = get_settings()
    runtime = create_semantic_runtime(settings)
    if not runtime.available:
        raise SystemExit("Semantic runtime is disabled or unavailable.")
    try:
        if arguments.command == "download-model":
            assert runtime.provider is not None
            load_ms = runtime.provider.load()
            print(
                json.dumps(
                    {
                        "status": "ready",
                        "model": runtime.provider.model_name,
                        "version": runtime.provider.model_version,
                        "dimension": runtime.provider.dimension,
                        "load_ms": load_ms,
                    },
                    separators=(",", ":"),
                )
            )
            return
        _reindex(settings, runtime, force=arguments.force)
    finally:
        runtime.close()


def _reindex(settings, runtime, *, force: bool) -> None:
    database = Database(settings)
    database.create_schema()
    totals = {"documents": 0, "embedded": 0, "reused": 0, "deleted": 0, "failed": 0}
    try:
        offset = 0
        while True:
            with database.session_factory() as session:
                repository = SQLiteDocumentRepository(session)
                documents, total = repository.list(offset, 100)
                indexer = SemanticIndexService(settings, repository, runtime)
                for document in documents:
                    try:
                        if force:
                            indexer.delete_document(document.id)
                        result = indexer.sync_document(document)
                        totals["documents"] += 1
                        totals["embedded"] += result.embedded_chunks
                        totals["reused"] += result.reused_chunks
                        totals["deleted"] += result.deleted_vectors
                    except Exception:
                        totals["failed"] += 1
                offset += len(documents)
                if offset >= total or not documents:
                    break
    finally:
        database.dispose()
    print(json.dumps(totals, separators=(",", ":")))


if __name__ == "__main__":
    main()
