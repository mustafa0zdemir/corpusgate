from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.models.document import Chunk, Document
from app.retrieval.types import RetrievalFilters


@dataclass(frozen=True, slots=True)
class SearchCandidate:
    document: Document
    chunk: Chunk
    score: float


class SearchIndex(ABC):
    """Retrieval boundary that can later be implemented by a semantic index."""

    @abstractmethod
    def search(
        self,
        terms: list[str],
        *,
        filters: RetrievalFilters | None = None,
        document_ids: list[str] | None = None,
        limit: int,
        offset: int = 0,
    ) -> list[SearchCandidate]:
        raise NotImplementedError
