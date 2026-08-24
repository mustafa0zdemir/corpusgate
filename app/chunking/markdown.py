from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass, replace

from app.chunking.base import ChunkDraft, ChunkStrategy
from app.chunking.tokens import ApproximateTokenEstimator, TokenEstimator, TokenSpan

BOUNDARY_RE = re.compile(
    r"^(?:(?P<marks>#{1,6})\s+(?P<heading>.+?)\s*|"
    r"(?P<slide><!--\s*Slide number:\s*(?P<slide_number>\d+)\s*-->))$",
    re.IGNORECASE | re.MULTILINE,
)
PAGE_RE = re.compile(r"^(?:page|sayfa)\s+(\d+)\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class _Section:
    heading: str | None
    text: str
    start: int
    page_number: int | None
    slide_number: int | None
    sheet_name: str | None


class MarkdownChunkStrategy(ChunkStrategy):
    def __init__(
        self,
        target_tokens: int = 500,
        overlap_tokens: int = 50,
        min_chunk_tokens: int = 40,
        estimator: TokenEstimator | None = None,
    ):
        if target_tokens < 1:
            raise ValueError("target_tokens must be positive")
        if overlap_tokens < 0 or overlap_tokens >= target_tokens:
            raise ValueError("overlap_tokens must be non-negative and smaller than target_tokens")
        if min_chunk_tokens < 1 or min_chunk_tokens > target_tokens:
            raise ValueError("min_chunk_tokens must be between 1 and target_tokens")
        self.target_tokens = target_tokens
        self.overlap_tokens = overlap_tokens
        self.min_chunk_tokens = min_chunk_tokens
        self.estimator = estimator or ApproximateTokenEstimator()

    def split(self, markdown: str, *, document_type: str | None = None) -> list[ChunkDraft]:
        if not markdown.strip():
            return []

        provisional: list[ChunkDraft] = []
        for section in self._sections(markdown, document_type):
            for content, relative_start in self._split_section(section.text):
                leading = len(content) - len(content.lstrip())
                cleaned = content.strip()
                if not cleaned or self._is_marker_only(cleaned):
                    continue
                char_start = section.start + relative_start + leading
                provisional.append(
                    ChunkDraft(
                        chunk_index=len(provisional),
                        heading=section.heading,
                        content=cleaned,
                        char_start=char_start,
                        char_end=char_start + len(cleaned),
                        token_count=self.estimator.estimate(cleaned),
                        page_number=section.page_number,
                        slide_number=section.slide_number,
                        sheet_name=section.sheet_name,
                    )
                )

        merged = self._merge_tiny_and_remove_duplicates(markdown, provisional)
        return [replace(chunk, chunk_index=index) for index, chunk in enumerate(merged)]

    @staticmethod
    def _is_marker_only(content: str) -> bool:
        return bool(re.fullmatch(r"<!--\s*Slide number:\s*\d+\s*-->", content, re.I))

    @staticmethod
    def _sections(markdown: str, document_type: str | None) -> list[_Section]:
        matches = list(BOUNDARY_RE.finditer(markdown))
        if not matches:
            return [_Section(None, markdown, 0, None, None, None)]

        sections: list[_Section] = []
        heading: str | None = None
        page_number: int | None = None
        slide_number: int | None = None
        sheet_name: str | None = None
        normalized_type = (document_type or "").lower().lstrip(".")

        if matches[0].start() > 0 and markdown[: matches[0].start()].strip():
            sections.append(_Section(None, markdown[: matches[0].start()], 0, None, None, None))

        for index, match in enumerate(matches):
            if match.group("slide"):
                slide_number = int(match.group("slide_number"))
            else:
                heading = match.group("heading").strip()
                page_match = PAGE_RE.match(heading)
                if page_match:
                    page_number = int(page_match.group(1))
                if normalized_type == "xlsx" and len(match.group("marks")) == 2:
                    sheet_name = heading

            end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
            sections.append(
                _Section(
                    heading=heading,
                    text=markdown[match.start() : end],
                    start=match.start(),
                    page_number=page_number,
                    slide_number=slide_number,
                    sheet_name=sheet_name,
                )
            )
        return sections

    def _split_section(self, text: str) -> list[tuple[str, int]]:
        spans = self.estimator.spans(text)
        if len(spans) <= self.target_tokens:
            return [(text, 0)]

        pieces: list[tuple[str, int]] = []
        span_ends = [span.end for span in spans]
        token_start = 0
        while token_start < len(spans):
            token_end = min(token_start + self.target_tokens, len(spans))
            char_start = spans[token_start].start
            char_end = spans[token_end - 1].end
            if token_end < len(spans):
                char_end, token_end = self._preferred_break(
                    text,
                    spans,
                    span_ends,
                    token_start,
                    token_end,
                    char_start,
                    char_end,
                )

            pieces.append((text[char_start:char_end], char_start))
            if token_end >= len(spans):
                break
            token_start = max(token_end - self.overlap_tokens, token_start + 1)
        return pieces

    def _preferred_break(
        self,
        text: str,
        spans: list[TokenSpan],
        span_ends: list[int],
        token_start: int,
        token_end: int,
        char_start: int,
        char_end: int,
    ) -> tuple[int, int]:
        minimum_token = token_start + max(self.target_tokens * 3 // 5, 1)
        minimum_char = spans[min(minimum_token, token_end - 1)].start
        window = text[char_start:char_end]
        candidates = [window.rfind("\n\n"), window.rfind("\n"), window.rfind(" ")]
        best = max(candidates)
        candidate_end = char_start + best
        if best > 0 and candidate_end >= minimum_char:
            adjusted_end = bisect_right(span_ends, candidate_end)
            if adjusted_end > token_start:
                return candidate_end, adjusted_end
        return char_end, token_end

    def _merge_tiny_and_remove_duplicates(
        self, markdown: str, chunks: list[ChunkDraft]
    ) -> list[ChunkDraft]:
        result: list[ChunkDraft] = []
        fingerprints: set[str] = set()
        for chunk in chunks:
            fingerprint = self._fingerprint(chunk.content)
            if fingerprint and fingerprint in fingerprints:
                continue

            if result and (
                result[-1].token_count < self.min_chunk_tokens
                or chunk.token_count < self.min_chunk_tokens
            ):
                previous = result[-1]
                merged_content = markdown[previous.char_start : chunk.char_end].strip()
                merged_tokens = self.estimator.estimate(merged_content)
                if merged_tokens <= self.target_tokens:
                    merged = replace(
                        previous,
                        content=merged_content,
                        char_end=chunk.char_end,
                        token_count=merged_tokens,
                        page_number=previous.page_number or chunk.page_number,
                        slide_number=previous.slide_number or chunk.slide_number,
                        sheet_name=previous.sheet_name or chunk.sheet_name,
                    )
                    result[-1] = merged
                    fingerprints.discard(self._fingerprint(previous.content))
                    fingerprints.add(self._fingerprint(merged.content))
                    continue

            result.append(chunk)
            if fingerprint:
                fingerprints.add(fingerprint)
        return result

    @staticmethod
    def _fingerprint(content: str) -> str:
        return " ".join(content.casefold().split())
