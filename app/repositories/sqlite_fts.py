from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.document import Chunk, Document, DocumentStatus
from app.repositories.search import SearchCandidate, SearchIndex


class SQLiteFtsSearchIndex(SearchIndex):
    """SQLite FTS5 index using weighted BM25 ranking."""

    def __init__(self, session: Session):
        self.session = session

    def search(
        self,
        terms: list[str],
        *,
        document_ids: list[str] | None,
        limit: int,
        offset: int = 0,
    ) -> list[SearchCandidate]:
        if not terms or limit <= 0:
            return []

        match_query = " OR ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms)
        filters = ["chunk_fts MATCH :match_query", "d.status = :ready"]
        parameters: dict[str, object] = {
            "match_query": match_query,
            "ready": DocumentStatus.ready.value,
            "limit": limit,
            "offset": offset,
        }
        if document_ids:
            placeholders = []
            for index, document_id in enumerate(document_ids):
                key = f"document_id_{index}"
                placeholders.append(f":{key}")
                parameters[key] = document_id
            filters.append(f"d.id IN ({', '.join(placeholders)})")

        statement = text(
            "SELECT c.id AS chunk_id, "
            "bm25(chunk_fts, 0.0, 0.0, 5.0, 1.0) AS rank "
            "FROM chunk_fts "
            "JOIN chunks c ON c.id = chunk_fts.chunk_id "
            "JOIN documents d ON d.id = c.document_id "
            f"WHERE {' AND '.join(filters)} "
            "ORDER BY rank ASC, c.chunk_index ASC "
            "LIMIT :limit OFFSET :offset"
        )
        ranked_rows = self.session.execute(statement, parameters).mappings().all()
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
