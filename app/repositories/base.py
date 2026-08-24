from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.chunking.base import ChunkDraft
from app.models.document import Chunk, Document


@dataclass(frozen=True, slots=True)
class SearchCandidate:
    document: Document
    chunk: Chunk


class DocumentRepository(ABC):
    @abstractmethod
    def create(self, document: Document) -> Document:
        raise NotImplementedError

    @abstractmethod
    def get(self, document_id: str) -> Document | None:
        raise NotImplementedError

    @abstractmethod
    def get_by_hash(self, sha256: str) -> Document | None:
        raise NotImplementedError

    @abstractmethod
    def list(self, offset: int, limit: int) -> tuple[list[Document], int]:
        raise NotImplementedError

    @abstractmethod
    def update_status(
        self, document: Document, status: str, error_message: str | None = None
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def mark_ready(
        self,
        document: Document,
        *,
        markdown_path: str,
        markdown_chars: int,
        chunks: list[ChunkDraft],
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_chunks(self, document_id: str, offset: int, limit: int) -> tuple[list[Chunk], int]:
        raise NotImplementedError

    @abstractmethod
    def search_candidates(
        self,
        terms: list[str],
        *,
        document_id: str | None,
        limit: int,
    ) -> list[SearchCandidate]:
        raise NotImplementedError

    @abstractmethod
    def delete(self, document: Document) -> None:
        raise NotImplementedError
