import stat
from collections import namedtuple
from io import BytesIO

import pytest

from app.core.errors import FileTooLargeError, InsufficientStorageError, InvalidFileError
from app.storage.local import LocalFileStorage


def test_storage_uses_generated_path_and_hash(tmp_path) -> None:
    storage = LocalFileStorage(tmp_path, max_file_size_mb=1)
    stored = storage.save_upload(
        BytesIO(b"private content"),
        document_id="a1b2c3",
        extension=".txt",
        max_bytes=100,
        buffer_bytes=64,
    )

    assert stored.relative_path == "uploads/a1b2c3.txt"
    assert stored.absolute_path.read_bytes() == b"private content"
    assert len(stored.sha256) == 64
    assert stat.S_IMODE(stored.absolute_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(storage.uploads_dir.stat().st_mode) & 0o022 == 0


def test_storage_blocks_path_traversal_and_oversize(tmp_path) -> None:
    storage = LocalFileStorage(tmp_path, max_file_size_mb=1)

    with pytest.raises(InvalidFileError):
        storage.resolve("../secret.txt")

    with pytest.raises(InvalidFileError):
        storage.resolve("/etc/passwd")

    with pytest.raises(InvalidFileError):
        storage.resolve("uploads\\..\\secret.txt")

    with pytest.raises(FileTooLargeError):
        storage.save_upload(
            BytesIO(b"12345"),
            document_id="too-large",
            extension=".txt",
            max_bytes=4,
            buffer_bytes=64,
        )
    assert not (tmp_path / "uploads" / "too-large.txt").exists()


def test_storage_blocks_symlink_escape(tmp_path) -> None:
    storage = LocalFileStorage(tmp_path / "data", max_file_size_mb=1)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    (storage.uploads_dir / "escape").symlink_to(outside, target_is_directory=True)

    with pytest.raises(InvalidFileError):
        storage.resolve("uploads/escape/secret.txt")


def test_storage_reports_reserved_disk_exhaustion(tmp_path, monkeypatch) -> None:
    usage = namedtuple("usage", "total used free")
    storage = LocalFileStorage(
        tmp_path,
        max_file_size_mb=1,
        min_free_bytes=100,
    )
    monkeypatch.setattr("app.storage.local.shutil.disk_usage", lambda _path: usage(100, 95, 5))

    with pytest.raises(InsufficientStorageError):
        storage.save_upload(
            BytesIO(b"content"),
            document_id="no-space",
            extension=".txt",
            max_bytes=100,
            buffer_bytes=64,
        )
