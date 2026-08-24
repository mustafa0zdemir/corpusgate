from app.chunking.markdown import MarkdownChunkStrategy


def test_markdown_chunker_preserves_heading_and_order() -> None:
    markdown = "# Intro\n\n" + ("alpha beta gamma " * 35) + "\n\n## Details\n\nshort section"
    chunks = MarkdownChunkStrategy(target_size=180, overlap=20).split(markdown)

    assert len(chunks) > 2
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert chunks[0].heading == "Intro"
    assert chunks[-1].heading == "Details"
    assert all(len(chunk.content) <= 180 for chunk in chunks)
    assert all(chunk.char_start < chunk.char_end for chunk in chunks)


def test_markdown_chunker_handles_empty_content() -> None:
    assert MarkdownChunkStrategy().split("  \n") == []
