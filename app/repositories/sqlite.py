from __future__ import annotations

from uuid import uuid4

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.chunking.base import ChunkDraft
from app.models.document import Chunk, Document, DocumentStatus
from app.repositories.base import DocumentRepository, SearchCandidate


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
            self.session.execute(delete(Chunk).where(Chunk.document_id == document.id))
            self.session.add_all(
                [
                    Chunk(
                        id=str(uuid4()),
                        document_id=document.id,
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
            )
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

    def search_candidates(
        self,
        terms: list[str],
        *,
        document_id: str | None,
        limit: int,
    ) -> list[SearchCandidate]:
        conditions = [func.lower(Chunk.content).contains(term) for term in terms]
        heading_conditions = [
            func.lower(func.coalesce(Chunk.heading, "")).contains(term) for term in terms
        ]
        query = (
            select(Document, Chunk)
            .join(Chunk, Chunk.document_id == Document.id)
            .where(Document.status == DocumentStatus.ready.value)
            .where(or_(*(conditions + heading_conditions)))
        )
        if document_id is not None:
            query = query.where(Document.id == document_id)
        rows = self.session.execute(
            query.order_by(Document.created_at.desc(), Chunk.chunk_index).limit(limit)
        ).all()
        return [SearchCandidate(document=row[0], chunk=row[1]) for row in rows]

    def delete(self, document: Document) -> None:
        self.session.delete(document)
        self.session.commit()
