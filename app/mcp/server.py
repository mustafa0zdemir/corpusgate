from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any

from mcp.server import MCPServer
from mcp_types import ToolAnnotations
from pydantic import Field
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings, get_settings
from app.core.database import Database
from app.core.errors import AppError
from app.repositories.sqlite import SQLiteDocumentRepository
from app.repositories.sqlite_fts import SQLiteFtsSearchIndex
from app.retrieval.types import RetrievalFilters
from app.semantic.runtime import SemanticRuntime
from app.services.search import FullTextSearchService, RetrievalPage

READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)


def create_mcp_server(
    settings: Settings,
    sessions: sessionmaker,
    *,
    semantic_runtime: SemanticRuntime | None = None,
) -> MCPServer:
    semantic_runtime = semantic_runtime or SemanticRuntime(enabled=False)
    server = MCPServer(
        "Private Document Gateway",
        version=settings.app_version,
        instructions=(
            "Search before reading sections. Retrieval tools return relevance-ranked, "
            "source-attributed chunks under server-enforced character and estimated-token "
            "budgets. They never return raw files or a full document by default."
        ),
    )

    @server.tool(annotations=READ_ONLY)
    def list_documents(
        offset: Annotated[int, Field(ge=0, description="Zero-based document offset")] = 0,
        limit: Annotated[int, Field(ge=1, description="Page size; server-capped")] = 20,
    ) -> dict[str, Any]:
        """Discover available documents without returning any document text."""
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
        """Inspect one document's source, status, cache size, and chunk count; returns no text."""
        with sessions() as session:
            document = SQLiteDocumentRepository(session).get(document_id)
            if document is None:
                raise ValueError("Document not found.")
            return _document_metadata(document)

    @server.tool(annotations=READ_ONLY)
    def search_documents(
        query: Annotated[
            str, Field(min_length=1, description="Keywords or question to find across documents")
        ],
        top_k: Annotated[int | None, Field(ge=1, description="Maximum returned chunks")] = None,
        max_chars: Annotated[
            int | None, Field(ge=1, description="Total content character budget")
        ] = None,
        max_tokens: Annotated[
            int | None, Field(ge=1, description="Total estimated-token budget")
        ] = None,
        cursor: Annotated[
            str | None, Field(description="Opaque next_cursor from the previous identical search")
        ] = None,
        neighbor_window: Annotated[
            int,
            Field(ge=0, description="Optional adjacent chunks on each side; server-capped"),
        ] = 0,
        retrieval_mode: Annotated[
            str | None,
            Field(description="lexical, semantic, or hybrid; server default when omitted"),
        ] = None,
        document_ids: Annotated[
            list[str] | None,
            Field(description="Optional document UUID allowlist; at most 10"),
        ] = None,
        file_types: Annotated[
            list[str] | None,
            Field(description="Optional file extension filter, such as pdf or docx"),
        ] = None,
        heading: Annotated[
            str | None, Field(description="Optional exact Markdown heading filter")
        ] = None,
    ) -> dict[str, Any]:
        """Find the best bounded chunks across all ready documents.

        Use this when the relevant document is not yet known. Results include source and
        position metadata; the complete documents are never returned.
        """
        return _search_payload(
            settings,
            sessions,
            query=query,
            document_ids=document_ids,
            top_k=top_k,
            max_chars=max_chars,
            max_tokens=max_tokens,
            cursor=cursor,
            neighbor_window=neighbor_window,
            retrieval_mode=retrieval_mode,
            file_types=file_types,
            heading=heading,
            semantic_runtime=semantic_runtime,
        )

    @server.tool(annotations=READ_ONLY)
    def search_document(
        document_id: Annotated[str, Field(description="Document UUID to search within")],
        query: Annotated[str, Field(min_length=1, description="Keywords or question to find")],
        top_k: Annotated[int | None, Field(ge=1, description="Maximum returned chunks")] = None,
        max_chars: Annotated[
            int | None, Field(ge=1, description="Total content character budget")
        ] = None,
        max_tokens: Annotated[
            int | None, Field(ge=1, description="Total estimated-token budget")
        ] = None,
        cursor: Annotated[
            str | None, Field(description="Opaque next_cursor from the previous identical search")
        ] = None,
        neighbor_window: Annotated[
            int,
            Field(ge=0, description="Optional adjacent chunks on each side; server-capped"),
        ] = 0,
        include_neighbors: Annotated[
            bool, Field(description="Include at most one adjacent chunk on each side")
        ] = False,
        retrieval_mode: Annotated[
            str | None, Field(description="lexical, semantic, or hybrid")
        ] = None,
    ) -> dict[str, Any]:
        """Search one known document and return relevance-ranked source chunks under budget."""
        return _search_payload(
            settings,
            sessions,
            query=query,
            document_ids=[document_id],
            top_k=top_k,
            max_chars=max_chars,
            max_tokens=max_tokens,
            cursor=cursor,
            neighbor_window=max(neighbor_window, int(include_neighbors)),
            retrieval_mode=retrieval_mode,
            file_types=None,
            heading=None,
            semantic_runtime=semantic_runtime,
        )

    @server.tool(annotations=READ_ONLY)
    def get_relevant_chunks(
        query: Annotated[
            str, Field(min_length=1, description="Question or keywords describing needed context")
        ],
        document_ids: Annotated[
            list[str] | None,
            Field(description="Optional document UUID allowlist; at most 10"),
        ] = None,
        top_k: Annotated[int | None, Field(ge=1, description="Maximum returned chunks")] = None,
        max_chars: Annotated[
            int | None, Field(ge=1, description="Total content character budget")
        ] = None,
        max_tokens: Annotated[
            int | None, Field(ge=1, description="Total estimated-token budget")
        ] = None,
        cursor: Annotated[
            str | None, Field(description="Opaque next_cursor from the previous identical search")
        ] = None,
        neighbor_window: Annotated[
            int,
            Field(ge=0, description="Optional adjacent chunks on each side; server-capped"),
        ] = 0,
        retrieval_mode: Annotated[
            str | None, Field(description="lexical, semantic, or hybrid")
        ] = None,
        file_types: Annotated[
            list[str] | None, Field(description="Optional file extension filter")
        ] = None,
        heading: Annotated[
            str | None, Field(description="Optional exact Markdown heading filter")
        ] = None,
    ) -> dict[str, Any]:
        """Build a small, deduplicated context set from an optional document allowlist."""
        if document_ids is not None and len(document_ids) > 10:
            raise ValueError("At most 10 document IDs may be supplied.")
        return _search_payload(
            settings,
            sessions,
            query=query,
            document_ids=document_ids,
            top_k=top_k,
            max_chars=max_chars,
            max_tokens=max_tokens,
            cursor=cursor,
            neighbor_window=neighbor_window,
            retrieval_mode=retrieval_mode,
            file_types=file_types,
            heading=heading,
            semantic_runtime=semantic_runtime,
        )

    @server.tool(annotations=READ_ONLY)
    def get_document_section(
        document_id: Annotated[str, Field(description="Document UUID")],
        start_chunk: Annotated[int, Field(ge=0, description="Zero-based chunk index")] = 0,
        chunk_count: Annotated[
            int, Field(ge=1, description="Consecutive chunks; server-capped")
        ] = 3,
        max_chars: Annotated[
            int | None, Field(ge=1, description="Total content character budget")
        ] = None,
        max_tokens: Annotated[
            int | None, Field(ge=1, description="Total estimated-token budget")
        ] = None,
        cursor: Annotated[
            str | None, Field(description="Opaque next_cursor for the same document section")
        ] = None,
    ) -> dict[str, Any]:
        """Read a bounded chunk sequence after search identifies a useful position.

        Pagination is chunk based. Even the largest request remains subject to both server
        content budgets, so this tool does not return the full document by default.
        """
        try:
            with sessions() as session:
                repository = SQLiteDocumentRepository(session)
                page = FullTextSearchService(
                    settings,
                    repository,
                    SQLiteFtsSearchIndex(
                        session,
                        timeout_seconds=settings.search_timeout_seconds,
                    ),
                    semantic_runtime,
                ).section(
                    document_id,
                    start_chunk=start_chunk,
                    chunk_count=chunk_count,
                    max_chars=max_chars,
                    max_tokens=max_tokens,
                    cursor=cursor,
                )
        except AppError as exc:
            raise ValueError(exc.message) from exc
        return _page_payload(None, page)

    return server


def _search_payload(
    settings: Settings,
    sessions: sessionmaker,
    *,
    query: str,
    document_ids: list[str] | None,
    top_k: int | None,
    max_chars: int | None,
    max_tokens: int | None,
    cursor: str | None,
    neighbor_window: int,
    retrieval_mode: str | None,
    file_types: list[str] | None,
    heading: str | None,
    semantic_runtime: SemanticRuntime,
) -> dict[str, Any]:
    try:
        with sessions() as session:
            repository = SQLiteDocumentRepository(session)
            page = FullTextSearchService(
                settings,
                repository,
                SQLiteFtsSearchIndex(
                    session,
                    timeout_seconds=settings.search_timeout_seconds,
                ),
                semantic_runtime,
            ).search(
                query,
                document_ids=document_ids,
                top_k=top_k,
                max_chars=max_chars,
                max_tokens=max_tokens,
                cursor=cursor,
                neighbor_window=neighbor_window,
                retrieval_mode=retrieval_mode,
                filters=RetrievalFilters(
                    document_ids=tuple(document_ids or ()),
                    file_types=tuple(value.lower().lstrip(".") for value in (file_types or ())),
                    heading=heading,
                ),
            )
    except AppError as exc:
        raise ValueError(exc.message) from exc
    return _page_payload(query, page)


def _page_payload(query: str | None, page: RetrievalPage) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "items": [asdict(item) for item in page.items],
        "top_k": page.top_k,
        "max_chars": page.max_chars,
        "max_tokens": page.max_tokens,
        "next_cursor": page.next_cursor,
        "metrics": asdict(page.metrics),
        "requested_retrieval_mode": page.requested_retrieval_mode,
        "retrieval_mode": page.retrieval_mode,
        "fallback_reason": page.fallback_reason,
    }
    if query is not None:
        payload["query"] = query
    return payload


def _document_metadata(document) -> dict[str, Any]:
    return {
        "document_id": document.id,
        "document_name": document.original_filename,
        "content_type": document.content_type,
        "file_size": document.file_size,
        "sha256": document.sha256,
        "status": document.status,
        "chunk_count": document.chunk_count,
        "markdown_chars": document.markdown_chars,
        "markdown_estimated_tokens": document.markdown_tokens,
        "cache_available": bool(document.markdown_path),
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
