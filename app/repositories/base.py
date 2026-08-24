from __future__ import annotations

from abc import ABC, abstractmethod

from app.chunking.base import ChunkDraft
from app.models.document import Chunk, Document


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
    def get_latest_by_filename(self, filename: str) -> Document | None:
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
        markdown_tokens: int,
        chunks: list[ChunkDraft],
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_chunks(self, document_id: str, offset: int, limit: int) -> tuple[list[Chunk], int]:
        raise NotImplementedError

    @abstractmethod
    def get_chunks_by_ids(self, chunk_ids: list[str]) -> list[tuple[Document, Chunk]]:
        raise NotImplementedError

    @abstractmethod
    def get_neighbor_chunks(
        self,
        document_id: str,
        chunk_index: int,
        window: int,
    ) -> list[Chunk]:
        raise NotImplementedError

    @abstractmethod
    def replace_content(
        self,
        document: Document,
        *,
        original_filename: str,
        content_type: str,
        extension: str,
        file_size: int,
        sha256: str,
        storage_path: str,
        markdown_path: str,
        markdown_chars: int,
        markdown_tokens: int,
        chunks: list[ChunkDraft],
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def delete(self, document: Document) -> None:
        raise NotImplementedError

    @abstractmethod
    def refresh_search_index(self, document_id: str) -> int:
        """Rebuild lexical index entries from persisted chunks and return their count."""
        raise NotImplementedError
