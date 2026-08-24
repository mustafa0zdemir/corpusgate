from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter

from app.core.config import Settings
from app.models.document import Chunk, Document
from app.repositories.base import DocumentRepository
from app.semantic.runtime import SemanticRuntime
from app.vectorstores.base import VectorRecord

logger = logging.getLogger("private_document_gateway.semantic_index")


@dataclass(frozen=True, slots=True)
class IndexingResult:
    embedded_chunks: int
    reused_chunks: int
    deleted_vectors: int
    duration_ms: float


class SemanticIndexService:
    """Incrementally synchronizes SQLite chunks to the optional vector index."""

    def __init__(
        self,
        settings: Settings,
        repository: DocumentRepository,
        runtime: SemanticRuntime,
    ):
        self.settings = settings
        self.repository = repository
        self.runtime = runtime

    def sync_document(self, document: Document) -> IndexingResult:
        started = perf_counter()
        provider, store, capacity = self._components()
        store.ensure_collection(
            provider.dimension,
            embedding_model=provider.model_name,
            embedding_version=provider.model_version,
        )
        chunks, _ = self.repository.list_chunks(document.id, 0, max(document.chunk_count, 1))
        previous = store.list_document_records(document.id)
        reusable = {
            record.content_hash: record.vector
            for record in previous
            if record.embedding_model == provider.model_name
            and record.embedding_version == provider.model_version
            and len(record.vector) == provider.dimension
        }
        hashes = {chunk.id: _content_hash(chunk.content) for chunk in chunks}
        missing = [chunk for chunk in chunks if hashes[chunk.id] not in reusable]
        vectors = (
            capacity.run(
                lambda: provider.embed_passages([chunk.content for chunk in missing]),
                timeout=self.settings.embedding_timeout_seconds,
            )
            if missing
            else []
        )
        if len(vectors) != len(missing):
            raise RuntimeError("The embedding provider returned an incomplete batch.")
        generated = {chunk.id: vector for chunk, vector in zip(missing, vectors, strict=True)}
        now = datetime.now(UTC)
        records = [
            self._record(
                document,
                chunk,
                hashes[chunk.id],
                reusable.get(hashes[chunk.id]) or generated[chunk.id],
                now,
            )
            for chunk in chunks
        ]
        # Publish the complete replacement before deleting stale points. A failed batch
        # therefore leaves the last working index intact.
        store.upsert(records)
        current_ids = {chunk.id for chunk in chunks}
        stale = [record.chunk_id for record in previous if record.chunk_id not in current_ids]
        store.delete_chunks(stale)
        result = IndexingResult(
            embedded_chunks=len(missing),
            reused_chunks=len(chunks) - len(missing),
            deleted_vectors=len(stale),
            duration_ms=round((perf_counter() - started) * 1000, 3),
        )
        logger.info(
            "semantic_index_updated",
            extra={
                "event": "semantic_index_updated",
                "document_id": document.id,
                "chunk_count": len(chunks),
                "duration_ms": result.duration_ms,
            },
        )
        return result

    def delete_document(self, document_id: str) -> None:
        if self.runtime.store is not None:
            self.runtime.store.delete_document(document_id)

    def _components(self):
        if not self.runtime.available:
            raise RuntimeError("Semantic indexing is unavailable.")
        assert self.runtime.provider is not None
        assert self.runtime.store is not None
        assert self.runtime.capacity is not None
        return self.runtime.provider, self.runtime.store, self.runtime.capacity

    def _record(
        self,
        document: Document,
        chunk: Chunk,
        content_hash: str,
        vector: list[float],
        indexed_at: datetime,
    ) -> VectorRecord:
        provider = self.runtime.provider
        assert provider is not None
        return VectorRecord(
            chunk_id=chunk.id,
            document_id=document.id,
            document_name=document.original_filename,
            file_type=document.extension,
            heading=chunk.heading,
            position={
                "chunk_index": chunk.chunk_index,
                "char_start": chunk.char_start,
                "char_end": chunk.char_end,
                "page_number": chunk.page_number,
                "slide_number": chunk.slide_number,
                "sheet_name": chunk.sheet_name,
            },
            content_hash=content_hash,
            embedding_model=provider.model_name,
            embedding_version=provider.model_version,
            indexed_at=indexed_at,
            vector=vector,
        )


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
