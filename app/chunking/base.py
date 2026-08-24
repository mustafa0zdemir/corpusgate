from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ChunkDraft:
    chunk_index: int
    heading: str | None
    content: str
    char_start: int
    char_end: int
    token_count: int
    page_number: int | None = None
    slide_number: int | None = None
    sheet_name: str | None = None


class ChunkStrategy(ABC):
    @abstractmethod
    def split(self, markdown: str, *, document_type: str | None = None) -> list[ChunkDraft]:
        raise NotImplementedError
