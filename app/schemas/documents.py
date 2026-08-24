from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.document import DocumentStatus


class DocumentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: str = Field(validation_alias="id")
    original_filename: str
    content_type: str
    file_size: int
    status: DocumentStatus
    chunk_count: int
    created_at: datetime
    updated_at: datetime


class DocumentUploadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: str
    original_filename: str
    content_type: str
    file_size: int
    status: DocumentStatus
    created_at: datetime
    deduplicated: bool = False
    reindexed: bool = False


class DocumentMetadata(DocumentSummary):
    extension: str
    sha256: str
    markdown_chars: int
    markdown_tokens: int
    error_message: str | None = None


class DocumentListResponse(BaseModel):
    items: list[DocumentSummary]
    offset: int
    limit: int
    total: int
    has_more: bool


class MarkdownResponse(BaseModel):
    document_id: str
    content: str
    offset: int
    returned_chars: int
    total_chars: int
    has_more: bool


class ChunkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    chunk_id: str = Field(validation_alias="id")
    chunk_index: int
    heading: str | None
    content: str
    char_start: int
    char_end: int
    token_count: int
    page_number: int | None
    slide_number: int | None
    sheet_name: str | None


class ChunkListResponse(BaseModel):
    document_id: str
    items: list[ChunkResponse]
    offset: int
    limit: int
    total: int
    has_more: bool


class SearchHitResponse(BaseModel):
    document_id: str
    original_filename: str
    chunk_id: str
    chunk_index: int
    heading: str | None
    content: str
    score: float


class SearchResponse(BaseModel):
    query: str
    items: list[SearchHitResponse]
    top_k: int
    returned_chars: int
