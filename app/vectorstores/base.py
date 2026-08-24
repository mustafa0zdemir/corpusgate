from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.retrieval.types import RetrievalFilters


class VectorStoreUnavailableError(RuntimeError):
    """Raised when the optional vector store cannot serve a request."""


class VectorDimensionMismatchError(VectorStoreUnavailableError):
    """Raised when configured model and collection dimensions differ."""


@dataclass(frozen=True, slots=True)
class VectorRecord:
    chunk_id: str
    document_id: str
    document_name: str
    file_type: str
    heading: str | None
    position: dict[str, int | str | None]
    content_hash: str
    embedding_model: str
    embedding_version: str
    indexed_at: datetime
    vector: list[float]


@dataclass(frozen=True, slots=True)
class VectorSearchHit:
    chunk_id: str
    score: float
    payload: dict[str, Any]


class VectorStore(ABC):
    @abstractmethod
    def ensure_collection(
        self,
        dimension: int,
        *,
        embedding_model: str,
        embedding_version: str,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def health(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def list_document_records(
        self,
        document_id: str,
        *,
        embedding_model: str | None = None,
        embedding_version: str | None = None,
    ) -> list[VectorRecord]:
        raise NotImplementedError

    @abstractmethod
    def upsert(self, records: list[VectorRecord]) -> None:
        raise NotImplementedError

    @abstractmethod
    def delete_chunks(self, chunk_ids: list[str]) -> None:
        raise NotImplementedError

    @abstractmethod
    def delete_document(self, document_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def search(
        self,
        query_vector: list[float],
        *,
        filters: RetrievalFilters,
        embedding_model: str,
        embedding_version: str,
        limit: int,
        offset: int = 0,
    ) -> list[VectorSearchHit]:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError
