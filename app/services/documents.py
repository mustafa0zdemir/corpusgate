from __future__ import annotations

from dataclasses import dataclass
from typing import BinaryIO
from uuid import uuid4

from app.chunking.base import ChunkStrategy
from app.chunking.tokens import ApproximateTokenEstimator
from app.core.config import Settings
from app.core.errors import AppError, DocumentConversionError, DocumentNotFoundError
from app.models.document import Chunk, Document, DocumentStatus
from app.parsers.base import DocumentParser
from app.repositories.base import DocumentRepository
from app.services.file_validation import validate_file_signature, validate_upload_metadata
from app.storage.base import FileStorage


@dataclass(frozen=True, slots=True)
class UploadResult:
    document: Document
    deduplicated: bool


class DocumentService:
    def __init__(
        self,
        *,
        settings: Settings,
        repository: DocumentRepository,
        parser: DocumentParser,
        storage: FileStorage,
        chunker: ChunkStrategy,
    ):
        self.settings = settings
        self.repository = repository
        self.parser = parser
        self.storage = storage
        self.chunker = chunker
        self.token_estimator = ApproximateTokenEstimator()

    def upload(
        self,
        source: BinaryIO,
        *,
        filename: str | None,
        content_type: str | None,
    ) -> UploadResult:
        safe_filename, extension, normalized_type = validate_upload_metadata(filename, content_type)
        document_id = str(uuid4())
        stored = self.storage.save_upload(
            source,
            document_id=document_id,
            extension=extension,
            max_bytes=self.settings.max_file_size_bytes,
            buffer_bytes=self.settings.upload_buffer_bytes,
        )
        try:
            validate_file_signature(
                stored.absolute_path,
                extension,
                self.settings.max_archive_uncompressed_bytes,
            )
        except Exception:
            self.storage.delete(stored.relative_path)
            raise

        existing = self.repository.get_by_hash(stored.sha256)
        if existing is not None:
            self.storage.delete(stored.relative_path)
            if existing.status == DocumentStatus.failed.value:
                self._process(existing)
            return UploadResult(existing, deduplicated=True)

        document = Document(
            id=document_id,
            original_filename=safe_filename,
            content_type=normalized_type,
            extension=extension,
            file_size=stored.size,
            sha256=stored.sha256,
            storage_path=stored.relative_path,
            status=DocumentStatus.pending.value,
        )
        self.repository.create(document)
        self._process(document)
        return UploadResult(document, deduplicated=False)

    def _process(self, document: Document) -> None:
        self.repository.update_status(document, DocumentStatus.processing.value)
        try:
            markdown = self.parser.parse(self.storage.resolve(document.storage_path))
            markdown_path = self.storage.save_markdown(document.id, markdown)
            chunks = self.chunker.split(markdown, document_type=document.extension)
            self.repository.mark_ready(
                document,
                markdown_path=markdown_path,
                markdown_chars=len(markdown),
                markdown_tokens=self.token_estimator.estimate(markdown),
                chunks=chunks,
            )
        except AppError as exc:
            self.storage.delete(document.markdown_path)
            self.repository.update_status(document, DocumentStatus.failed.value, exc.message[:500])
            raise
        except Exception as exc:
            self.storage.delete(document.markdown_path)
            message = "The document could not be processed."
            self.repository.update_status(document, DocumentStatus.failed.value, message)
            raise DocumentConversionError(message) from exc

    def get(self, document_id: str) -> Document:
        document = self.repository.get(document_id)
        if document is None:
            raise DocumentNotFoundError
        return document

    def list(self, offset: int, limit: int) -> tuple[list[Document], int]:
        return self.repository.list(offset, min(limit, self.settings.max_page_size))

    def markdown(self, document_id: str, offset: int, max_chars: int) -> tuple[str, int]:
        document = self.get(document_id)
        if document.status != DocumentStatus.ready.value or not document.markdown_path:
            raise AppError("Document Markdown is not ready.", status_code=409, code="not_ready")
        content = self.storage.read_text(document.markdown_path)
        clamped_max = min(max_chars, self.settings.max_response_chars)
        return content[offset : offset + clamped_max], len(content)

    def chunks(self, document_id: str, offset: int, limit: int) -> tuple[list[Chunk], int]:
        self.get(document_id)
        return self.repository.list_chunks(
            document_id, offset, min(limit, self.settings.max_page_size)
        )

    def delete(self, document_id: str) -> None:
        document = self.get(document_id)
        self.storage.delete(document.storage_path)
        self.storage.delete(document.markdown_path)
        self.repository.delete(document)
