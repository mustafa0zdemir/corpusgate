from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import BinaryIO

from app.core.errors import FileTooLargeError, InvalidFileError
from app.storage.base import FileStorage, StoredFile


class LocalFileStorage(FileStorage):
    def __init__(self, data_dir: Path, max_file_size_mb: int):
        self.data_dir = data_dir.resolve()
        self.uploads_dir = self.data_dir / "uploads"
        self.markdown_dir = self.data_dir / "markdown"
        self.max_file_size_mb = max_file_size_mb
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.markdown_dir.mkdir(parents=True, exist_ok=True)

    def save_upload(
        self,
        source: BinaryIO,
        *,
        document_id: str,
        extension: str,
        max_bytes: int,
        buffer_bytes: int,
    ) -> StoredFile:
        relative_path = f"uploads/{document_id}{extension}"
        destination = self.resolve(relative_path)
        temporary = destination.with_suffix(destination.suffix + ".part")
        digest = hashlib.sha256()
        total = 0

        try:
            source.seek(0)
            with temporary.open("xb") as target:
                while block := source.read(buffer_bytes):
                    total += len(block)
                    if total > max_bytes:
                        raise FileTooLargeError(self.max_file_size_mb)
                    digest.update(block)
                    target.write(block)
            if total == 0:
                raise InvalidFileError("Empty files are not accepted.")
            os.chmod(temporary, 0o600)
            os.replace(temporary, destination)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

        return StoredFile(relative_path, destination, total, digest.hexdigest())

    def save_markdown(self, document_id: str, content: str, *, cache_key: str | None = None) -> str:
        if cache_key is not None and not re.fullmatch(r"[a-f0-9]{12}", cache_key):
            raise InvalidFileError("Invalid Markdown cache key.")
        suffix = f"-{cache_key}" if cache_key else ""
        relative_path = f"markdown/{document_id}{suffix}.md"
        destination = self.resolve(relative_path)
        temporary = destination.with_suffix(".md.part")
        temporary.write_text(content, encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
        return relative_path

    def read_text(self, relative_path: str) -> str:
        return self.resolve(relative_path).read_text(encoding="utf-8")

    def resolve(self, relative_path: str) -> Path:
        candidate = (self.data_dir / relative_path).resolve()
        if candidate != self.data_dir and self.data_dir not in candidate.parents:
            raise InvalidFileError("Invalid storage path.")
        return candidate

    def delete(self, relative_path: str | None) -> None:
        if relative_path:
            self.resolve(relative_path).unlink(missing_ok=True)
