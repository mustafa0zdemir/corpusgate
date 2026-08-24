from __future__ import annotations

import re
from dataclasses import dataclass

from app.chunking.base import ChunkDraft, ChunkStrategy

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class _Section:
    heading: str | None
    text: str
    start: int


class MarkdownChunkStrategy(ChunkStrategy):
    def __init__(self, target_size: int = 2_000, overlap: int = 120):
        if target_size < 1:
            raise ValueError("target_size must be positive")
        if overlap < 0 or overlap >= target_size:
            raise ValueError("overlap must be non-negative and smaller than target_size")
        self.target_size = target_size
        self.overlap = overlap

    def split(self, markdown: str) -> list[ChunkDraft]:
        if not markdown.strip():
            return []

        drafts: list[ChunkDraft] = []
        for section in self._sections(markdown):
            for content, relative_start in self._split_section(section.text):
                leading = len(content) - len(content.lstrip())
                cleaned = content.strip()
                if not cleaned:
                    continue
                char_start = section.start + relative_start + leading
                drafts.append(
                    ChunkDraft(
                        chunk_index=len(drafts),
                        heading=section.heading,
                        content=cleaned,
                        char_start=char_start,
                        char_end=char_start + len(cleaned),
                    )
                )
        return drafts

    @staticmethod
    def _sections(markdown: str) -> list[_Section]:
        matches = list(HEADING_RE.finditer(markdown))
        if not matches:
            return [_Section(heading=None, text=markdown, start=0)]

        sections: list[_Section] = []
        if matches[0].start() > 0 and markdown[: matches[0].start()].strip():
            sections.append(_Section(None, markdown[: matches[0].start()], 0))

        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
            sections.append(
                _Section(match.group(2).strip(), markdown[match.start() : end], match.start())
            )
        return sections

    def _split_section(self, text: str) -> list[tuple[str, int]]:
        if len(text) <= self.target_size:
            return [(text, 0)]

        pieces: list[tuple[str, int]] = []
        start = 0
        while start < len(text):
            hard_end = min(start + self.target_size, len(text))
            end = hard_end
            if hard_end < len(text):
                minimum_break = start + max(self.target_size // 2, 1)
                window = text[start:hard_end]
                candidates = [window.rfind("\n\n"), window.rfind("\n"), window.rfind(" ")]
                best_break = max(candidates)
                if start + best_break >= minimum_break:
                    end = start + best_break

            pieces.append((text[start:end], start))
            if end >= len(text):
                break
            start = max(end - self.overlap, start + 1)
        return pieces
