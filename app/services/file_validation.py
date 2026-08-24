from __future__ import annotations

import re
import unicodedata
import zipfile
from pathlib import Path

from app.core.errors import InvalidFileError

SUPPORTED_CONTENT_TYPES: dict[str, set[str]] = {
    ".pdf": {"application/pdf", "application/x-pdf"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    ".pptx": {"application/vnd.openxmlformats-officedocument.presentationml.presentation"},
    ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    ".txt": {"text/plain"},
    ".md": {"text/markdown", "text/plain"},
    ".markdown": {"text/markdown", "text/plain"},
    ".html": {"text/html", "application/xhtml+xml"},
    ".htm": {"text/html", "application/xhtml+xml"},
}

GENERIC_CONTENT_TYPES = {"", "application/octet-stream"}
OFFICE_MARKERS = {".docx": "word/", ".pptx": "ppt/", ".xlsx": "xl/"}


def validate_upload_metadata(
    filename: str | None, content_type: str | None
) -> tuple[str, str, str]:
    safe_name = sanitize_filename(filename)
    extension = Path(safe_name).suffix.casefold()
    if extension not in SUPPORTED_CONTENT_TYPES:
        supported = ", ".join(sorted(SUPPORTED_CONTENT_TYPES))
        raise InvalidFileError(f"Unsupported file extension. Supported extensions: {supported}.")

    normalized_type = (content_type or "").split(";", 1)[0].strip().casefold()
    if normalized_type not in SUPPORTED_CONTENT_TYPES[extension] | GENERIC_CONTENT_TYPES:
        raise InvalidFileError("The declared MIME type does not match the file extension.")
    return safe_name, extension, normalized_type or "application/octet-stream"


def validate_file_signature(path: Path, extension: str, max_archive_bytes: int) -> None:
    if extension == ".pdf":
        with path.open("rb") as source:
            signature = source.read(5)
        if signature != b"%PDF-":
            raise InvalidFileError("The uploaded file is not a valid PDF.")
        return

    if extension in OFFICE_MARKERS:
        _validate_office_archive(path, OFFICE_MARKERS[extension], max_archive_bytes)
        return

    sample = path.read_bytes()[: 64 * 1024]
    if b"\x00" in sample:
        raise InvalidFileError("The uploaded text file contains binary data.")
    try:
        sample.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InvalidFileError("Text, Markdown, and HTML files must use UTF-8 encoding.") from exc


def sanitize_filename(filename: str | None) -> str:
    if not filename:
        raise InvalidFileError("A filename is required.")
    normalized = unicodedata.normalize("NFKC", filename).replace("\\", "/").split("/")[-1]
    normalized = re.sub(r"[\x00-\x1f\x7f]", "", normalized).strip()
    if not normalized or normalized in {".", ".."}:
        raise InvalidFileError("The filename is invalid.")
    return normalized[:255]


def _validate_office_archive(path: Path, marker: str, max_archive_bytes: int) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if not any(member.filename.startswith(marker) for member in members):
                raise InvalidFileError("The file contents do not match the Office extension.")
            if sum(member.file_size for member in members) > max_archive_bytes:
                raise InvalidFileError(
                    "The Office archive expands beyond the configured safety limit.",
                    status_code=413,
                    code="archive_too_large",
                )
    except zipfile.BadZipFile as exc:
        raise InvalidFileError("The uploaded Office document is not a valid archive.") from exc
