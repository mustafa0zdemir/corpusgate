from __future__ import annotations

from pathlib import Path

from markitdown import MarkItDown

from app.core.errors import DocumentConversionError
from app.parsers.base import DocumentParser


class MarkItDownDocumentParser(DocumentParser):
    def __init__(self) -> None:
        self._converter = MarkItDown(enable_plugins=False)

    def parse(self, path: Path) -> str:
        try:
            result = self._converter.convert_local(str(path))
            markdown = result.text_content
        except Exception as exc:
            raise DocumentConversionError(
                "This file could not be converted by the installed MarkItDown adapters."
            ) from exc

        if not isinstance(markdown, str):
            raise DocumentConversionError("The converter did not produce text output.")
        return markdown.strip()
