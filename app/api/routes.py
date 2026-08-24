from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, File, Query, Request, Response, UploadFile, status

from app.api.dependencies import DocumentServiceDependency, SearchServiceDependency
from app.schemas.documents import (
    ChunkListResponse,
    ChunkResponse,
    DocumentListResponse,
    DocumentMetadata,
    DocumentSummary,
    DocumentUploadResponse,
    MarkdownResponse,
    SearchHitResponse,
    SearchResponse,
)

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])


@router.post("", response_model=DocumentUploadResponse, status_code=status.HTTP_201_CREATED)
def upload_document(
    file: Annotated[UploadFile, File(description="A supported local document")],
    service: DocumentServiceDependency,
) -> DocumentUploadResponse:
    result = service.upload(
        file.file,
        filename=file.filename,
        content_type=file.content_type,
    )
    document = result.document
    return DocumentUploadResponse(
        document_id=document.id,
        original_filename=document.original_filename,
        content_type=document.content_type,
        file_size=document.file_size,
        status=document.status,
        created_at=document.created_at,
        deduplicated=result.deduplicated,
    )


@router.get("", response_model=DocumentListResponse)
def list_documents(
    service: DocumentServiceDependency,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 20,
) -> DocumentListResponse:
    documents, total = service.list(offset, limit)
    actual_limit = min(limit, service.settings.max_page_size)
    return DocumentListResponse(
        items=[DocumentSummary.model_validate(item) for item in documents],
        offset=offset,
        limit=actual_limit,
        total=total,
        has_more=offset + len(documents) < total,
    )


@router.get("/{document_id}", response_model=DocumentMetadata)
def get_document(document_id: str, service: DocumentServiceDependency) -> DocumentMetadata:
    return DocumentMetadata.model_validate(service.get(document_id))


@router.get("/{document_id}/markdown", response_model=MarkdownResponse)
def get_markdown(
    document_id: str,
    service: DocumentServiceDependency,
    offset: Annotated[int, Query(ge=0)] = 0,
    max_chars: Annotated[int, Query(ge=1, le=250_000)] = 8_000,
) -> MarkdownResponse:
    content, total = service.markdown(document_id, offset, max_chars)
    return MarkdownResponse(
        document_id=document_id,
        content=content,
        offset=offset,
        returned_chars=len(content),
        total_chars=total,
        has_more=offset + len(content) < total,
    )


@router.get("/{document_id}/chunks", response_model=ChunkListResponse)
def get_chunks(
    document_id: str,
    service: DocumentServiceDependency,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 20,
) -> ChunkListResponse:
    chunks, total = service.chunks(document_id, offset, limit)
    actual_limit = min(limit, service.settings.max_page_size)
    return ChunkListResponse(
        document_id=document_id,
        items=[ChunkResponse.model_validate(chunk) for chunk in chunks],
        offset=offset,
        limit=actual_limit,
        total=total,
        has_more=offset + len(chunks) < total,
    )


@router.get("/{document_id}/search", response_model=SearchResponse)
def search_document(
    document_id: str,
    request: Request,
    search_service: SearchServiceDependency,
    q: Annotated[str, Query(min_length=1, max_length=500)],
    top_k: Annotated[int, Query(ge=1, le=100)] = 5,
    max_chars: Annotated[int, Query(ge=1, le=250_000)] = 8_000,
) -> SearchResponse:
    settings = request.app.state.settings
    actual_top_k = min(top_k, settings.max_search_top_k)
    actual_max_chars = min(max_chars, settings.max_response_chars)
    hits = search_service.search(
        q,
        document_id=document_id,
        top_k=actual_top_k,
        max_chars=actual_max_chars,
    )
    return SearchResponse(
        query=q,
        items=[SearchHitResponse(**asdict(hit)) for hit in hits],
        top_k=actual_top_k,
        returned_chars=sum(len(hit.content) for hit in hits),
    )


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: str, service: DocumentServiceDependency) -> Response:
    service.delete(document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
