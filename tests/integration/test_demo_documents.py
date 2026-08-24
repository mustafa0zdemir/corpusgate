from __future__ import annotations

from app.parsers.markitdown import MarkItDownDocumentParser
from scripts.generate_demo_documents import generate_documents


def test_generated_office_demo_documents_convert_without_external_data(tmp_path) -> None:
    parser = MarkItDownDocumentParser()
    generated = generate_documents(tmp_path)
    converted = {path.suffix: parser.parse(path) for path in generated}
    assert "bounded relevant chunks" in converted[".docx"]
    assert "Lexical index" in converted[".xlsx"]
