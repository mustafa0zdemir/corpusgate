from __future__ import annotations

import errno
import hashlib
import os
import re
import shutil
import stat
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from app.core.errors import FileTooLargeError, InsufficientStorageError, InvalidFileError
from app.storage.base import FileStorage, StoredFile


class LocalFileStorage(FileStorage):
    def __init__(
        self,
        data_dir: Path,
        max_file_size_mb: int,
        *,
        documents_dir: Path | None = None,
        markdown_dir: Path | None = None,
        min_free_bytes: int = 0,
    ):
        self.data_dir = data_dir.resolve()
        self.uploads_dir = documents_dir or data_dir / "uploads"
        self.markdown_dir = markdown_dir or data_dir / "markdown"
        self.max_file_size_mb = max_file_size_mb
        self.min_free_bytes = min_free_bytes
        self._prepare_root(self.uploads_dir)
        self._prepare_root(self.markdown_dir)
        self.uploads_dir = self.uploads_dir.resolve()
        self.markdown_dir = self.markdown_dir.resolve()

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
        self._ensure_capacity(self.uploads_dir)

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
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            self._raise_storage_error(exc)
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
        encoded = content.encode("utf-8")
        self._ensure_capacity(self.markdown_dir, len(encoded))
        try:
            temporary.write_bytes(encoded)
            os.chmod(temporary, 0o600)
            os.replace(temporary, destination)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            self._raise_storage_error(exc)
        return relative_path

    def read_text(self, relative_path: str) -> str:
        return self.resolve(relative_path).read_text(encoding="utf-8")

    def resolve(self, relative_path: str) -> Path:
        if not relative_path or "\\" in relative_path:
            raise InvalidFileError("Invalid storage path.")
        path = PurePosixPath(relative_path)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise InvalidFileError("Invalid storage path.")
        if len(path.parts) < 2:
            raise InvalidFileError("Invalid storage path.")

        roots = {"uploads": self.uploads_dir, "markdown": self.markdown_dir}
        root = roots.get(path.parts[0])
        if root is None:
            raise InvalidFileError("Invalid storage path.")
        candidate = root.joinpath(*path.parts[1:]).resolve()
        if root not in candidate.parents:
            raise InvalidFileError("Invalid storage path.")
        return candidate

    def delete(self, relative_path: str | None) -> None:
        if relative_path:
            try:
                self.resolve(relative_path).unlink(missing_ok=True)
            except OSError as exc:
                self._raise_storage_error(exc)

    def is_ready(self) -> bool:
        return all(
            root.is_dir() and os.access(root, os.R_OK | os.W_OK | os.X_OK)
            for root in (self.uploads_dir, self.markdown_dir)
        )

    @staticmethod
    def _prepare_root(root: Path) -> None:
        if root.is_symlink():
            raise InvalidFileError("Storage roots must not be symbolic links.")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        details = root.stat()
        if not stat.S_ISDIR(details.st_mode):
            raise InvalidFileError("The configured storage root is not a directory.")
        if details.st_uid != os.geteuid():
            raise InvalidFileError("The configured storage root has an invalid owner.")
        if stat.S_IMODE(details.st_mode) & 0o022:
            raise InvalidFileError("The configured storage root is group or world writable.")
        if not os.access(root, os.R_OK | os.W_OK | os.X_OK):
            raise InvalidFileError("The configured storage root is not writable.")

    def _ensure_capacity(self, root: Path, required_bytes: int = 0) -> None:
        try:
            free = shutil.disk_usage(root).free
        except OSError as exc:
            self._raise_storage_error(exc)
            return
        if free - required_bytes < self.min_free_bytes:
            raise InsufficientStorageError

    @staticmethod
    def _raise_storage_error(exc: OSError) -> None:
        if exc.errno in {errno.ENOSPC, errno.EDQUOT}:
            raise InsufficientStorageError from exc
        raise exc
