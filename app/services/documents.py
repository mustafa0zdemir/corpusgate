from __future__ import annotations

import logging
from dataclasses import dataclass
from time import perf_counter
from typing import BinaryIO
from uuid import uuid4

from app.chunking.base import ChunkStrategy
from app.chunking.tokens import ApproximateTokenEstimator
from app.core.config import Settings
from app.core.errors import AppError, DocumentConversionError, DocumentNotFoundError
from app.core.resources import OperationCapacity
from app.models.document import Chunk, Document, DocumentStatus
from app.parsers.base import DocumentParser
from app.repositories.base import DocumentRepository
from app.services.file_validation import validate_file_signature, validate_upload_metadata
from app.storage.base import FileStorage, StoredFile

logger = logging.getLogger("private_document_gateway.documents")


@dataclass(frozen=True, slots=True)
class UploadResult:
    document: Document
    deduplicated: bool
    reindexed: bool = False


class DocumentService:
    def __init__(
        self,
        *,
        settings: Settings,
        repository: DocumentRepository,
        parser: DocumentParser,
        storage: FileStorage,
        chunker: ChunkStrategy,
        conversion_capacity: OperationCapacity,
    ):
        self.settings = settings
        self.repository = repository
        self.parser = parser
        self.storage = storage
        self.chunker = chunker
        self.token_estimator = ApproximateTokenEstimator()
        self.conversion_capacity = conversion_capacity

    def upload(
        self,
        source: BinaryIO,
        *,
        filename: str | None,
        content_type: str | None,
    ) -> UploadResult:
        safe_filename, extension, normalized_type = validate_upload_metadata(filename, content_type)
        upload_id = str(uuid4())
        stored = self.storage.save_upload(
            source,
            document_id=upload_id,
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
            logger.info(
                "document_upload",
                extra={
                    "event": "document_upload",
                    "document_id": existing.id,
                    "file_type": extension,
                    "cache_hit": True,
                    "chunk_count": existing.chunk_count,
                },
            )
            return UploadResult(existing, deduplicated=True)

        current = self.repository.get_latest_by_filename(safe_filename)
        if current is not None:
            return self._replace(
                current,
                stored,
                original_filename=safe_filename,
                content_type=normalized_type,
                extension=extension,
            )

        document = Document(
            id=upload_id,
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
        started = perf_counter()
        self.repository.update_status(document, DocumentStatus.processing.value)
        markdown_path: str | None = None
        try:
            markdown = self._parse(self.storage.resolve(document.storage_path))
            markdown_path = self.storage.save_markdown(
                document.id, markdown, cache_key=document.sha256[:12]
            )
            chunks = self.chunker.split(markdown, document_type=document.extension)
            self.repository.mark_ready(
                document,
                markdown_path=markdown_path,
                markdown_chars=len(markdown),
                markdown_tokens=self.token_estimator.estimate(markdown),
                chunks=chunks,
            )
            logger.info(
                "document_processed",
                extra={
                    "event": "document_processed",
                    "document_id": document.id,
                    "file_type": document.extension,
                    "cache_hit": False,
                    "chunk_count": len(chunks),
                    "duration_ms": round((perf_counter() - started) * 1000, 3),
                },
            )
        except AppError as exc:
            self.storage.delete(markdown_path)
            self.repository.update_status(document, DocumentStatus.failed.value, exc.message[:500])
            self._log_failure(document, exc, started)
            raise
        except Exception as exc:
            self.storage.delete(markdown_path)
            message = "The document could not be processed."
            self.repository.update_status(document, DocumentStatus.failed.value, message)
            self._log_failure(document, exc, started)
            raise DocumentConversionError(message) from exc

    def _replace(
        self,
        document: Document,
        stored: StoredFile,
        *,
        original_filename: str,
        content_type: str,
        extension: str,
    ) -> UploadResult:
        started = perf_counter()
        old_storage_path = document.storage_path
        old_markdown_path = document.markdown_path
        new_markdown_path: str | None = None
        try:
            markdown = self._parse(
                stored.absolute_path,
                on_late_complete=lambda: self.storage.delete(stored.relative_path),
            )
            new_markdown_path = self.storage.save_markdown(
                document.id, markdown, cache_key=stored.sha256[:12]
            )
            chunks = self.chunker.split(markdown, document_type=extension)
            self.repository.replace_content(
                document,
                original_filename=original_filename,
                content_type=content_type,
                extension=extension,
                file_size=stored.size,
                sha256=stored.sha256,
                storage_path=stored.relative_path,
                markdown_path=new_markdown_path,
                markdown_chars=len(markdown),
                markdown_tokens=self.token_estimator.estimate(markdown),
                chunks=chunks,
            )
        except AppError as exc:
            if exc.code != "conversion_timeout":
                self.storage.delete(stored.relative_path)
            self.storage.delete(new_markdown_path)
            self._log_failure(document, exc, started)
            raise
        except Exception as exc:
            self.storage.delete(stored.relative_path)
            self.storage.delete(new_markdown_path)
            self._log_failure(document, exc, started)
            raise DocumentConversionError("The document could not be processed.") from exc

        self.storage.delete(old_storage_path)
        self.storage.delete(old_markdown_path)
        logger.info(
            "document_reindexed",
            extra={
                "event": "document_reindexed",
                "document_id": document.id,
                "file_type": extension,
                "cache_hit": False,
                "chunk_count": document.chunk_count,
                "duration_ms": round((perf_counter() - started) * 1000, 3),
            },
        )
        return UploadResult(document, deduplicated=False, reindexed=True)

    def _parse(
        self,
        path,
        *,
        on_late_complete=None,
    ) -> str:
        return self.conversion_capacity.run(
            lambda: self.parser.parse(path),
            timeout=self.settings.conversion_timeout_seconds,
            on_late_complete=on_late_complete,
        )

    @staticmethod
    def _log_failure(document: Document, exc: Exception, started: float) -> None:
        logger.warning(
            "document_processing_failed",
            extra={
                "event": "document_processing_failed",
                "document_id": document.id,
                "file_type": document.extension,
                "error_type": type(exc).__name__,
                "duration_ms": round((perf_counter() - started) * 1000, 3),
            },
        )

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
