from io import BytesIO

import pytest

from app.core.errors import FileTooLargeError, InvalidFileError
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


def test_storage_blocks_path_traversal_and_oversize(tmp_path) -> None:
    storage = LocalFileStorage(tmp_path, max_file_size_mb=1)

    with pytest.raises(InvalidFileError):
        storage.resolve("../secret.txt")

    with pytest.raises(FileTooLargeError):
        storage.save_upload(
            BytesIO(b"12345"),
            document_id="too-large",
            extension=".txt",
            max_bytes=4,
            buffer_bytes=64,
        )
    assert not (tmp_path / "uploads" / "too-large.txt").exists()
