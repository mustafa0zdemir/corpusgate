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


class ChunkStrategy(ABC):
    @abstractmethod
    def split(self, markdown: str) -> list[ChunkDraft]:
        raise NotImplementedError
