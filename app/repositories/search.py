from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.models.document import Chunk, Document


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
        document_ids: list[str] | None,
        limit: int,
        offset: int = 0,
    ) -> list[SearchCandidate]:
        raise NotImplementedError
