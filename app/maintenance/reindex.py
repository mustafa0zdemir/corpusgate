from __future__ import annotations

import argparse
import json

from app.chunking.markdown import MarkdownChunkStrategy
from app.core.config import Settings, get_settings
from app.core.database import Database
from app.core.errors import AppError
from app.core.resources import OperationCapacity
from app.parsers.markitdown import MarkItDownDocumentParser
from app.repositories.sqlite import SQLiteDocumentRepository
from app.services.documents import DocumentService
from app.storage.local import LocalFileStorage


def rebuild_cache(settings: Settings, *, force: bool = False) -> dict[str, int]:
    database = Database(settings)
    database.create_schema()
    storage = LocalFileStorage(
        settings.data_dir,
        settings.max_file_size_mb,
        documents_dir=settings.documents_root,
        markdown_dir=settings.cache_root,
        min_free_bytes=settings.min_free_disk_bytes,
    )
    capacity = OperationCapacity(
        operation="conversion",
        capacity=settings.max_concurrent_conversions,
        queue_timeout=settings.conversion_queue_timeout_seconds,
    )
    rebuilt = 0
    skipped = 0
    failed = 0
    try:
        with database.session_factory() as session:
            repository = SQLiteDocumentRepository(session)
            service = DocumentService(
                settings=settings,
                repository=repository,
                parser=MarkItDownDocumentParser(),
                storage=storage,
                chunker=MarkdownChunkStrategy(
                    target_tokens=settings.chunk_size_tokens,
                    overlap_tokens=settings.chunk_overlap_tokens,
                    min_chunk_tokens=settings.min_chunk_tokens,
                ),
                conversion_capacity=capacity,
            )
            offset = 0
            while True:
                documents, total = repository.list(offset, settings.max_page_size)
                if not documents:
                    break
                for document in documents:
                    try:
                        if service.rebuild_cache(document, force=force):
                            rebuilt += 1
                        else:
                            skipped += 1
                    except AppError:
                        failed += 1
                offset += len(documents)
                if offset >= total:
                    break
    finally:
        capacity.shutdown()
        database.dispose()
    return {"rebuilt": rebuilt, "skipped": skipped, "failed": failed}


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild missing Markdown cache and chunk index.")
    parser.add_argument("--all", action="store_true", help="Rebuild even existing cache entries")
    arguments = parser.parse_args()
    print(json.dumps(rebuild_cache(get_settings(), force=arguments.all)))


if __name__ == "__main__":
    main()
