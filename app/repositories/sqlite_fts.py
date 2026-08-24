from __future__ import annotations

import sqlite3
from time import monotonic

from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.errors import OperationTimeoutError
from app.models.document import Chunk, Document, DocumentStatus
from app.repositories.search import SearchCandidate, SearchIndex
from app.retrieval.types import RetrievalFilters


class SQLiteFtsSearchIndex(SearchIndex):
    """SQLite FTS5 index using weighted BM25 ranking."""

    def __init__(self, session: Session, *, timeout_seconds: int = 10):
        self.session = session
        self.timeout_seconds = timeout_seconds

    def search(
        self,
        terms: list[str],
        *,
        filters: RetrievalFilters | None = None,
        document_ids: list[str] | None = None,
        limit: int,
        offset: int = 0,
    ) -> list[SearchCandidate]:
        if not terms or limit <= 0:
            return []
        filters = filters or RetrievalFilters(document_ids=tuple(document_ids or ()))

        match_query = " OR ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms)
        conditions = ["chunk_fts MATCH :match_query", "d.status = :ready"]
        parameters: dict[str, object] = {
            "match_query": match_query,
            "ready": DocumentStatus.ready.value,
            "limit": limit,
            "offset": offset,
        }
        if filters.document_ids:
            placeholders = []
            for index, document_id in enumerate(filters.document_ids):
                key = f"document_id_{index}"
                placeholders.append(f":{key}")
                parameters[key] = document_id
            conditions.append(f"d.id IN ({', '.join(placeholders)})")

        if filters.file_types:
            placeholders = []
            for index, file_type in enumerate(filters.file_types):
                key = f"file_type_{index}"
                placeholders.append(f":{key}")
                parameters[key] = file_type.lower().lstrip(".")
            conditions.append(f"d.extension IN ({', '.join(placeholders)})")
        if filters.heading:
            conditions.append("c.heading = :heading")
            parameters["heading"] = filters.heading

        statement = text(
            "SELECT c.id AS chunk_id, "
            "bm25(chunk_fts, 0.0, 0.0, 5.0, 1.0) AS rank "
            "FROM chunk_fts "
            "JOIN chunks c ON c.id = chunk_fts.chunk_id "
            "JOIN documents d ON d.id = c.document_id "
            f"WHERE {' AND '.join(conditions)} "
            "ORDER BY rank ASC, c.chunk_index ASC "
            "LIMIT :limit OFFSET :offset"
        )
        connection = self.session.connection()
        driver_connection = connection.connection.driver_connection
        deadline = monotonic() + self.timeout_seconds
        timed_out = False

        def stop_after_deadline() -> int:
            nonlocal timed_out
            timed_out = monotonic() >= deadline
            return int(timed_out)

        if isinstance(driver_connection, sqlite3.Connection):
            progress_steps = 1 if self.timeout_seconds <= 0 else 1_000
            driver_connection.set_progress_handler(stop_after_deadline, progress_steps)
        try:
            ranked_rows = self.session.execute(statement, parameters).mappings().all()
        except OperationalError as exc:
            if timed_out:
                raise OperationTimeoutError("search") from exc
            raise
        finally:
            if isinstance(driver_connection, sqlite3.Connection):
                driver_connection.set_progress_handler(None, 0)
        if not ranked_rows:
            return []

        chunk_ids = [row["chunk_id"] for row in ranked_rows]
        orm_rows = self.session.execute(
            select(Document, Chunk)
            .join(Chunk, Chunk.document_id == Document.id)
            .where(Chunk.id.in_(chunk_ids))
        ).all()
        by_chunk_id = {chunk.id: (document, chunk) for document, chunk in orm_rows}
        return [
            SearchCandidate(
                document=by_chunk_id[row["chunk_id"]][0],
                chunk=by_chunk_id[row["chunk_id"]][1],
                score=round(-float(row["rank"]), 8),
            )
            for row in ranked_rows
            if row["chunk_id"] in by_chunk_id
        ]
