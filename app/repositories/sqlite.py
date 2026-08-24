from __future__ import annotations

from uuid import uuid4

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.chunking.base import ChunkDraft
from app.models.document import Chunk, Document, DocumentStatus
from app.repositories.base import DocumentRepository


class SQLiteDocumentRepository(DocumentRepository):
    """SQLAlchemy repository; its contract is intentionally portable to PostgreSQL."""

    def __init__(self, session: Session):
        self.session = session

    def create(self, document: Document) -> Document:
        self.session.add(document)
        self.session.commit()
        return document

    def get(self, document_id: str) -> Document | None:
        return self.session.get(Document, document_id)

    def get_by_hash(self, sha256: str) -> Document | None:
        return self.session.scalar(select(Document).where(Document.sha256 == sha256))

    def get_latest_by_filename(self, filename: str) -> Document | None:
        return self.session.scalar(
            select(Document)
            .where(Document.original_filename == filename)
            .order_by(Document.updated_at.desc(), Document.id)
            .limit(1)
        )

    def list(self, offset: int, limit: int) -> tuple[list[Document], int]:
        total = self.session.scalar(select(func.count()).select_from(Document)) or 0
        items = list(
            self.session.scalars(
                select(Document)
                .order_by(Document.created_at.desc(), Document.id)
                .offset(offset)
                .limit(limit)
            )
        )
        return items, total

    def update_status(
        self, document: Document, status: str, error_message: str | None = None
    ) -> None:
        document.status = status
        document.error_message = error_message
        self.session.add(document)
        self.session.commit()

    def mark_ready(
        self,
        document: Document,
        *,
        markdown_path: str,
        markdown_chars: int,
        markdown_tokens: int,
        chunks: list[ChunkDraft],
    ) -> None:
        try:
            self._replace_chunks(document.id, chunks)
            document.markdown_path = markdown_path
            document.markdown_chars = markdown_chars
            document.markdown_tokens = markdown_tokens
            document.chunk_count = len(chunks)
            document.status = DocumentStatus.ready.value
            document.error_message = None
            self.session.add(document)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

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
        try:
            self._replace_chunks(document.id, chunks)
            document.original_filename = original_filename
            document.content_type = content_type
            document.extension = extension
            document.file_size = file_size
            document.sha256 = sha256
            document.storage_path = storage_path
            document.markdown_path = markdown_path
            document.markdown_chars = markdown_chars
            document.markdown_tokens = markdown_tokens
            document.chunk_count = len(chunks)
            document.status = DocumentStatus.ready.value
            document.error_message = None
            self.session.add(document)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

    def _replace_chunks(self, document_id: str, chunks: list[ChunkDraft]) -> None:
        self.session.execute(
            text("DELETE FROM chunk_fts WHERE document_id = :document_id"),
            {"document_id": document_id},
        )
        self.session.execute(delete(Chunk).where(Chunk.document_id == document_id))
        records = [
            Chunk(
                id=str(uuid4()),
                document_id=document_id,
                chunk_index=draft.chunk_index,
                heading=draft.heading,
                content=draft.content,
                char_start=draft.char_start,
                char_end=draft.char_end,
                token_count=draft.token_count,
                page_number=draft.page_number,
                slide_number=draft.slide_number,
                sheet_name=draft.sheet_name,
            )
            for draft in chunks
        ]
        self.session.add_all(records)
        self.session.flush()
        if records:
            self.session.execute(
                text(
                    "INSERT INTO chunk_fts(chunk_id, document_id, heading, content) "
                    "VALUES (:chunk_id, :document_id, :heading, :content)"
                ),
                [
                    {
                        "chunk_id": chunk.id,
                        "document_id": document_id,
                        "heading": chunk.heading or "",
                        "content": chunk.content,
                    }
                    for chunk in records
                ],
            )

    def list_chunks(self, document_id: str, offset: int, limit: int) -> tuple[list[Chunk], int]:
        total = (
            self.session.scalar(
                select(func.count()).select_from(Chunk).where(Chunk.document_id == document_id)
            )
            or 0
        )
        items = list(
            self.session.scalars(
                select(Chunk)
                .where(Chunk.document_id == document_id)
                .order_by(Chunk.chunk_index)
                .offset(offset)
                .limit(limit)
            )
        )
        return items, total

    def get_chunks_by_ids(self, chunk_ids: list[str]) -> list[tuple[Document, Chunk]]:
        if not chunk_ids:
            return []
        return list(
            self.session.execute(
                select(Document, Chunk)
                .join(Chunk, Chunk.document_id == Document.id)
                .where(Chunk.id.in_(chunk_ids))
            ).all()
        )

    def get_neighbor_chunks(
        self,
        document_id: str,
        chunk_index: int,
        window: int,
    ) -> list[Chunk]:
        return list(
            self.session.scalars(
                select(Chunk)
                .where(Chunk.document_id == document_id)
                .where(Chunk.chunk_index.between(chunk_index - window, chunk_index + window))
                .order_by(Chunk.chunk_index)
            )
        )

    def delete(self, document: Document) -> None:
        try:
            self.session.execute(
                text("DELETE FROM chunk_fts WHERE document_id = :document_id"),
                {"document_id": document.id},
            )
            self.session.delete(document)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

    def refresh_search_index(self, document_id: str) -> int:
        try:
            chunks = list(
                self.session.scalars(
                    select(Chunk)
                    .where(Chunk.document_id == document_id)
                    .order_by(Chunk.chunk_index)
                )
            )
            self.session.execute(
                text("DELETE FROM chunk_fts WHERE document_id = :document_id"),
                {"document_id": document_id},
            )
            if chunks:
                self.session.execute(
                    text(
                        "INSERT INTO chunk_fts(chunk_id, document_id, heading, content) "
                        "VALUES (:chunk_id, :document_id, :heading, :content)"
                    ),
                    [
                        {
                            "chunk_id": chunk.id,
                            "document_id": document_id,
                            "heading": chunk.heading or "",
                            "content": chunk.content,
                        }
                        for chunk in chunks
                    ],
                )
            self.session.commit()
            return len(chunks)
        except Exception:
            self.session.rollback()
            raise
