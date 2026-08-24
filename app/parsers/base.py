from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class DocumentParser(ABC):
    @abstractmethod
    def parse(self, path: Path) -> str:
        raise NotImplementedError
