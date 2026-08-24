from __future__ import annotations

import logging
from dataclasses import dataclass

from app.core.config import Settings
from app.core.resources import OperationCapacity
from app.embeddings.base import EmbeddingProvider
from app.embeddings.fastembed import FastEmbedEmbeddingProvider
from app.vectorstores.base import VectorStore
from app.vectorstores.qdrant import QdrantVectorStore

logger = logging.getLogger("corpusgate.semantic")


@dataclass(slots=True)
class SemanticRuntime:
    enabled: bool
    provider: EmbeddingProvider | None = None
    store: VectorStore | None = None
    capacity: OperationCapacity | None = None
    unavailable_reason: str | None = None

    @property
    def available(self) -> bool:
        return bool(self.enabled and self.provider and self.store and self.capacity)

    def close(self) -> None:
        if self.store is not None:
            self.store.close()
        if self.capacity is not None:
            self.capacity.shutdown()


def create_semantic_runtime(settings: Settings) -> SemanticRuntime:
    if not settings.semantic_enabled:
        return SemanticRuntime(enabled=False, unavailable_reason="semantic_disabled")
    try:
        provider = FastEmbedEmbeddingProvider(
            model_name=settings.embedding_model,
            model_version=settings.embedding_model_version,
            dimension=settings.embedding_dimension,
            cache_dir=settings.embedding_cache_dir,
            batch_size=settings.embedding_batch_size,
            threads=settings.embedding_threads,
            offline=settings.embedding_offline,
            query_prefix=settings.embedding_query_prefix,
            passage_prefix=settings.embedding_passage_prefix,
        )
        store = QdrantVectorStore(
            url=settings.vector_store_url,
            collection=settings.vector_collection,
            timeout_seconds=settings.vector_store_timeout_seconds,
        )
        capacity = OperationCapacity(
            operation="embedding",
            capacity=settings.max_concurrent_embeddings,
            queue_timeout=settings.embedding_queue_timeout_seconds,
        )
        return SemanticRuntime(True, provider, store, capacity)
    except Exception as exc:
        logger.warning(
            "semantic_runtime_unavailable",
            extra={
                "event": "semantic_runtime_unavailable",
                "error_type": type(exc).__name__,
            },
        )
        return SemanticRuntime(True, unavailable_reason=type(exc).__name__)
