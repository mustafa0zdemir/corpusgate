from __future__ import annotations

from datetime import UTC, datetime

from app.chunking.base import ChunkDraft
from app.core.database import Database
from app.core.resources import OperationCapacity
from app.embeddings.base import EmbeddingProvider
from app.models.document import Document, DocumentStatus
from app.repositories.sqlite import SQLiteDocumentRepository
from app.repositories.sqlite_fts import SQLiteFtsSearchIndex
from app.retrieval.types import RetrievalFilters
from app.semantic.runtime import SemanticRuntime
from app.services.search import FullTextSearchService
from app.services.semantic_index import SemanticIndexService
from app.vectorstores.base import VectorRecord, VectorSearchHit, VectorStore


class FakeEmbeddingProvider(EmbeddingProvider):
    model_name = "local-test-model"
    model_version = "v1"
    dimension = 3

    def __init__(self) -> None:
        self.passage_calls: list[list[str]] = []

    def load(self) -> float:
        return 1.0

    def embed_query(self, query: str) -> list[float]:
        return [1.0, float("semantic" in query), 0.0]

    def embed_passages(self, passages: list[str]) -> list[list[float]]:
        self.passage_calls.append(passages)
        return [[1.0, float(index), 0.0] for index, _ in enumerate(passages)]


class FakeVectorStore(VectorStore):
    def __init__(self) -> None:
        self.records: dict[str, VectorRecord] = {}
        self.available = True

    def ensure_collection(self, dimension: int, **_metadata) -> None:
        if not self.available:
            raise RuntimeError("offline")
        assert dimension == 3

    def health(self) -> bool:
        return self.available

    def list_document_records(self, document_id: str, **_metadata) -> list[VectorRecord]:
        return [record for record in self.records.values() if record.document_id == document_id]

    def upsert(self, records: list[VectorRecord]) -> None:
        self.records.update({record.chunk_id: record for record in records})

    def delete_chunks(self, chunk_ids: list[str]) -> None:
        for chunk_id in chunk_ids:
            self.records.pop(chunk_id, None)

    def delete_document(self, document_id: str) -> None:
        self.records = {
            key: value for key, value in self.records.items() if value.document_id != document_id
        }

    def search(
        self,
        query_vector: list[float],
        *,
        filters: RetrievalFilters,
        limit: int,
        offset: int = 0,
        **_metadata,
    ) -> list[VectorSearchHit]:
        assert len(query_vector) == 3
        records = [
            record
            for record in self.records.values()
            if (not filters.document_ids or record.document_id in filters.document_ids)
            and (not filters.file_types or record.file_type in filters.file_types)
            and (not filters.heading or record.heading == filters.heading)
        ]
        records.sort(key=lambda record: record.position["chunk_index"], reverse=True)
        return [
            VectorSearchHit(record.chunk_id, 0.9 - index * 0.1, {})
            for index, record in enumerate(records[offset : offset + limit])
        ]

    def close(self) -> None:
        return


def _document(repository: SQLiteDocumentRepository) -> Document:
    document = Document(
        id="11111111-1111-4111-8111-111111111111",
        original_filename="knowledge.md",
        content_type="text/markdown",
        extension="md",
        file_size=100,
        sha256="a" * 64,
        storage_path="uploads/source.md",
        status=DocumentStatus.pending.value,
    )
    repository.create(document)
    repository.mark_ready(
        document,
        markdown_path="markdown/cache.md",
        markdown_chars=100,
        markdown_tokens=25,
        chunks=[
            ChunkDraft(0, "Exact", "exactterm literal evidence", 0, 26, 6),
            ChunkDraft(1, "Meaning", "automobile maintenance advice", 27, 57, 7),
        ],
    )
    return document


def _runtime():
    provider = FakeEmbeddingProvider()
    store = FakeVectorStore()
    capacity = OperationCapacity(operation="embedding-test", capacity=1, queue_timeout=1)
    return SemanticRuntime(True, provider, store, capacity), provider, store


def test_incremental_embedding_reuses_unchanged_content(settings) -> None:
    database = Database(settings)
    database.create_schema()
    runtime, provider, store = _runtime()
    try:
        with database.session_factory() as session:
            repository = SQLiteDocumentRepository(session)
            document = _document(repository)
            indexer = SemanticIndexService(settings, repository, runtime)
            first = indexer.sync_document(document)
            second = indexer.sync_document(document)

            assert first.embedded_chunks == 2
            assert second.embedded_chunks == 0
            assert second.reused_chunks == 2
            assert len(provider.passage_calls) == 1
            assert len(store.records) == 2
    finally:
        runtime.close()
        database.dispose()


def test_hybrid_rrf_deduplicates_and_enforces_budget(settings) -> None:
    database = Database(settings)
    database.create_schema()
    runtime, _provider, _store = _runtime()
    try:
        with database.session_factory() as session:
            repository = SQLiteDocumentRepository(session)
            document = _document(repository)
            SemanticIndexService(settings, repository, runtime).sync_document(document)
            page = FullTextSearchService(
                settings,
                repository,
                SQLiteFtsSearchIndex(session),
                runtime,
            ).search(
                "exactterm semantic",
                retrieval_mode="hybrid",
                top_k=10,
                max_chars=40,
                max_tokens=8,
            )

            assert page.retrieval_mode == "hybrid"
            assert page.metrics.returned_chars <= 40
            assert page.metrics.returned_estimated_tokens <= 8
            assert len({item.chunk_id for item in page.items}) == len(page.items)
            assert any(item.lexical_rank for item in page.items)
            assert any(item.semantic_rank for item in page.items)
            assert all(item.combined_rank for item in page.items)
    finally:
        runtime.close()
        database.dispose()


def test_semantic_filters_and_lexical_fallback(settings) -> None:
    database = Database(settings)
    database.create_schema()
    runtime, _provider, store = _runtime()
    try:
        with database.session_factory() as session:
            repository = SQLiteDocumentRepository(session)
            document = _document(repository)
            SemanticIndexService(settings, repository, runtime).sync_document(document)
            service = FullTextSearchService(
                settings,
                repository,
                SQLiteFtsSearchIndex(session),
                runtime,
            )
            semantic = service.search(
                "related concept",
                retrieval_mode="semantic",
                filters=RetrievalFilters(file_types=("md",), heading="Meaning"),
            )
            assert [item.heading for item in semantic.items] == ["Meaning"]
            assert semantic.retrieval_mode == "semantic"

            store.available = False
            fallback = service.search("exactterm", retrieval_mode="hybrid")
            assert fallback.retrieval_mode == "lexical_fallback"
            assert fallback.fallback_reason == "RuntimeError"
            assert fallback.items[0].heading == "Exact"
    finally:
        runtime.close()
        database.dispose()


def test_vector_metadata_contains_no_chunk_content(settings) -> None:
    database = Database(settings)
    database.create_schema()
    runtime, _provider, store = _runtime()
    try:
        with database.session_factory() as session:
            repository = SQLiteDocumentRepository(session)
            document = _document(repository)
            SemanticIndexService(settings, repository, runtime).sync_document(document)
            record = next(iter(store.records.values()))
            assert record.content_hash
            assert record.embedding_model == "local-test-model"
            assert record.embedding_version == "v1"
            assert record.indexed_at <= datetime.now(UTC)
            assert not hasattr(record, "content")
    finally:
        runtime.close()
        database.dispose()
