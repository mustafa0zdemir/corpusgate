from __future__ import annotations

from typing import Annotated, Any

from mcp.server import MCPServer
from mcp_types import ToolAnnotations
from pydantic import Field
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings, get_settings
from app.core.database import Database
from app.core.errors import AppError
from app.repositories.sqlite import SQLiteDocumentRepository
from app.services.search import KeywordSearchService, SearchHit

READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)


def create_mcp_server(settings: Settings, sessions: sessionmaker) -> MCPServer:
    server = MCPServer(
        "Private Document Gateway",
        instructions=(
            "Use search tools before requesting sections. Results are bounded chunks; "
            "the server never returns raw files or a full document by default."
        ),
    )

    @server.tool(annotations=READ_ONLY)
    def list_documents(
        offset: Annotated[int, Field(ge=0, description="Zero-based document offset")] = 0,
        limit: Annotated[int, Field(ge=1, description="Page size; server-capped")] = 20,
    ) -> dict[str, Any]:
        """List document metadata when you need to discover which documents are available."""
        actual_limit = min(limit, settings.max_page_size)
        with sessions() as session:
            documents, total = SQLiteDocumentRepository(session).list(offset, actual_limit)
            return {
                "documents": [_document_metadata(document) for document in documents],
                "offset": offset,
                "limit": actual_limit,
                "total": total,
                "has_more": offset + len(documents) < total,
            }

    @server.tool(annotations=READ_ONLY)
    def get_document_metadata(
        document_id: Annotated[str, Field(description="UUID returned by list_documents")],
    ) -> dict[str, Any]:
        """Get metadata and processing status for one document.

        No document text is returned.
        """
        with sessions() as session:
            document = SQLiteDocumentRepository(session).get(document_id)
            if document is None:
                raise ValueError("Document not found.")
            return _document_metadata(document)

    @server.tool(annotations=READ_ONLY)
    def search_documents(
        query: Annotated[str, Field(min_length=1, description="Keywords to find across documents")],
        top_k: Annotated[int, Field(ge=1, description="Maximum number of chunks")] = 5,
        max_chars: Annotated[int, Field(ge=1, description="Total text budget")] = 8_000,
    ) -> dict[str, Any]:
        """Search across all ready documents and return only the best bounded chunks."""
        return _search(settings, sessions, query, None, top_k, max_chars)

    @server.tool(annotations=READ_ONLY)
    def search_document(
        document_id: Annotated[str, Field(description="Document UUID to search within")],
        query: Annotated[str, Field(min_length=1, description="Keywords to find")],
        top_k: Annotated[int, Field(ge=1, description="Maximum number of chunks")] = 5,
        max_chars: Annotated[int, Field(ge=1, description="Total text budget")] = 8_000,
    ) -> dict[str, Any]:
        """Search inside one known document when its ID is already available."""
        return _search(settings, sessions, query, document_id, top_k, max_chars)

    @server.tool(annotations=READ_ONLY)
    def get_relevant_chunks(
        query: Annotated[str, Field(min_length=1, description="Question or keywords")],
        document_ids: Annotated[
            list[str] | None,
            Field(description="Optional document UUID allowlist; at most 10"),
        ] = None,
        top_k: Annotated[int, Field(ge=1, description="Maximum number of chunks")] = 5,
        max_chars: Annotated[int, Field(ge=1, description="Total text budget")] = 8_000,
    ) -> dict[str, Any]:
        """Retrieve a small cross-document context set for answering a specific question."""
        if document_ids is not None and len(document_ids) > 10:
            raise ValueError("At most 10 document IDs may be supplied.")
        if not document_ids:
            return _search(settings, sessions, query, None, top_k, max_chars)

        actual_top_k = min(top_k, settings.max_search_top_k)
        actual_max_chars = min(max_chars, settings.max_response_chars)
        combined: list[SearchHit] = []
        with sessions() as session:
            search = KeywordSearchService(SQLiteDocumentRepository(session))
            for document_id in dict.fromkeys(document_ids):
                combined.extend(
                    search.search(
                        query,
                        document_id=document_id,
                        top_k=actual_top_k,
                        max_chars=actual_max_chars,
                    )
                )
        combined.sort(key=lambda hit: (-hit.score, hit.document_id, hit.chunk_index))
        return _hits_payload(query, combined, actual_top_k, actual_max_chars)

    @server.tool(annotations=READ_ONLY)
    def get_document_section(
        document_id: Annotated[str, Field(description="Document UUID")],
        start_chunk: Annotated[int, Field(ge=0, description="Zero-based chunk index")] = 0,
        chunk_count: Annotated[
            int, Field(ge=1, description="Consecutive chunks; server-capped")
        ] = 3,
        max_chars: Annotated[int, Field(ge=1, description="Total text budget")] = 8_000,
    ) -> dict[str, Any]:
        """Read a bounded sequence of chunks after search has identified a useful section."""
        actual_count = min(chunk_count, settings.max_page_size)
        budget = min(max_chars, settings.max_response_chars)
        with sessions() as session:
            repository = SQLiteDocumentRepository(session)
            document = repository.get(document_id)
            if document is None:
                raise ValueError("Document not found.")
            chunks, total = repository.list_chunks(document_id, start_chunk, actual_count)
            items: list[dict[str, Any]] = []
            for chunk in chunks:
                if budget <= 0:
                    break
                content = chunk.content[:budget]
                items.append(
                    {
                        "document_id": document_id,
                        "chunk_id": chunk.id,
                        "chunk_index": chunk.chunk_index,
                        "heading": chunk.heading,
                        "content": content,
                    }
                )
                budget -= len(content)
            return {
                "document_id": document_id,
                "items": items,
                "start_chunk": start_chunk,
                "returned_chars": sum(len(item["content"]) for item in items),
                "total_chunks": total,
                "has_more": start_chunk + len(items) < total,
            }

    return server


def _search(
    settings: Settings,
    sessions: sessionmaker,
    query: str,
    document_id: str | None,
    top_k: int,
    max_chars: int,
) -> dict[str, Any]:
    actual_top_k = min(top_k, settings.max_search_top_k)
    actual_max_chars = min(max_chars, settings.max_response_chars)
    try:
        with sessions() as session:
            hits = KeywordSearchService(SQLiteDocumentRepository(session)).search(
                query,
                document_id=document_id,
                top_k=actual_top_k,
                max_chars=actual_max_chars,
            )
    except AppError as exc:
        raise ValueError(exc.message) from exc
    return _hits_payload(query, hits, actual_top_k, actual_max_chars)


def _hits_payload(
    query: str,
    hits: list[SearchHit],
    top_k: int,
    max_chars: int,
) -> dict[str, Any]:
    selected: list[dict[str, Any]] = []
    remaining = max_chars
    for hit in hits:
        if len(selected) >= top_k or remaining <= 0:
            break
        content = hit.content[:remaining]
        selected.append(
            {
                "document_id": hit.document_id,
                "chunk_id": hit.chunk_id,
                "chunk_index": hit.chunk_index,
                "heading": hit.heading,
                "content": content,
                "score": hit.score,
            }
        )
        remaining -= len(content)
    return {
        "query": query,
        "items": selected,
        "top_k": top_k,
        "returned_chars": sum(len(item["content"]) for item in selected),
    }


def _document_metadata(document) -> dict[str, Any]:
    return {
        "document_id": document.id,
        "original_filename": document.original_filename,
        "content_type": document.content_type,
        "file_size": document.file_size,
        "status": document.status,
        "chunk_count": document.chunk_count,
        "markdown_chars": document.markdown_chars,
        "created_at": document.created_at.isoformat(),
        "updated_at": document.updated_at.isoformat(),
    }


def run_stdio() -> None:
    settings = get_settings()
    database = Database(settings)
    database.create_schema()
    create_mcp_server(settings, database.session_factory).run()


if __name__ == "__main__":
    run_stdio()
