from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import Path

from app.core.errors import AppError
from app.services.documents import DocumentService
from app.services.file_validation import SUPPORTED_CONTENT_TYPES


@dataclass(frozen=True, slots=True)
class ScanResult:
    discovered: int = 0
    indexed: int = 0
    deduplicated: int = 0
    replaced: int = 0
    skipped: int = 0
    failed: int = 0


class DocumentScanner:
    """Imports safe, regular files from a configured read-only inbox."""

    def __init__(self, inbox: Path, service: DocumentService):
        self.inbox = inbox
        self.service = service

    def scan(self) -> ScanResult:
        root = self.inbox.resolve(strict=True)
        if self.inbox.is_symlink() or not root.is_dir():
            raise ValueError("The documents inbox must be a real directory.")

        counters = {
            "discovered": 0,
            "indexed": 0,
            "deduplicated": 0,
            "replaced": 0,
            "skipped": 0,
            "failed": 0,
        }
        for entry in sorted(root.iterdir(), key=lambda path: path.name.casefold()):
            if entry.is_symlink() or not entry.is_file():
                counters["skipped"] += 1
                continue
            counters["discovered"] += 1
            if entry.name.startswith(".") or entry.suffix.casefold() not in SUPPORTED_CONTENT_TYPES:
                counters["skipped"] += 1
                continue
            try:
                content_type = mimetypes.guess_type(entry.name)[0] or "application/octet-stream"
                with entry.open("rb") as source:
                    result = self.service.upload(
                        source,
                        filename=entry.name,
                        content_type=content_type,
                    )
                if result.deduplicated:
                    counters["deduplicated"] += 1
                elif result.reindexed:
                    counters["replaced"] += 1
                else:
                    counters["indexed"] += 1
            except (AppError, OSError, ValueError):
                counters["failed"] += 1
        return ScanResult(**counters)
