from app.chunking.markdown import MarkdownChunkStrategy
from app.chunking.tokens import ApproximateTokenEstimator


def test_markdown_chunker_obeys_token_limit_and_preserves_heading() -> None:
    markdown = "# Intro\n\n" + ("alpha beta gamma " * 80) + "\n\n## Details\n\nshort section"
    chunks = MarkdownChunkStrategy(target_tokens=60, overlap_tokens=6, min_chunk_tokens=8).split(
        markdown
    )

    assert len(chunks) > 2
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert chunks[0].heading == "Intro"
    assert chunks[-1].heading == "Details"
    assert all(chunk.token_count <= 60 for chunk in chunks)
    assert all(chunk.char_start < chunk.char_end for chunk in chunks)


def test_markdown_chunker_carries_page_slide_and_sheet_metadata() -> None:
    page_chunks = MarkdownChunkStrategy(min_chunk_tokens=1).split("## Page 3\n\nPage content")
    slide_chunks = MarkdownChunkStrategy(min_chunk_tokens=1).split(
        "<!-- Slide number: 4 -->\n\n# Roadmap\n\nSlide content", document_type="pptx"
    )
    sheet_chunks = MarkdownChunkStrategy(min_chunk_tokens=1).split(
        "## Revenue\n\n| Month | Total |\n|---|---|\n| Jan | 10 |", document_type="xlsx"
    )

    assert page_chunks[0].page_number == 3
    assert slide_chunks[0].slide_number == 4
    assert slide_chunks[0].heading == "Roadmap"
    assert sheet_chunks[0].sheet_name == "Revenue"


def test_markdown_chunker_merges_tiny_chunks_and_removes_duplicates() -> None:
    markdown = "# A\n\ntiny\n\n# B\n\nsmall\n\n# C\n\nsmall"
    chunks = MarkdownChunkStrategy(target_tokens=40, overlap_tokens=2, min_chunk_tokens=12).split(
        markdown
    )

    normalized = [" ".join(chunk.content.casefold().split()) for chunk in chunks]
    assert len(normalized) == len(set(normalized))
    assert len(chunks) < 3


def test_token_estimator_truncates_to_exact_estimated_budget() -> None:
    estimator = ApproximateTokenEstimator()
    content = "A moderately long sentence with punctuation, numbers 12345 and Türkçe içerik."
    truncated = estimator.truncate(content, 8)

    assert estimator.estimate(truncated) <= 8
    assert len(truncated) < len(content)


def test_markdown_chunker_handles_empty_content() -> None:
    assert MarkdownChunkStrategy().split("  \n") == []
