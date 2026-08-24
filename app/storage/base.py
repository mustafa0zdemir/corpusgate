from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO


@dataclass(frozen=True, slots=True)
class StoredFile:
    relative_path: str
    absolute_path: Path
    size: int
    sha256: str


class FileStorage(ABC):
    @abstractmethod
    def save_upload(
        self,
        source: BinaryIO,
        *,
        document_id: str,
        extension: str,
        max_bytes: int,
        buffer_bytes: int,
    ) -> StoredFile:
        raise NotImplementedError

    @abstractmethod
    def save_markdown(self, document_id: str, content: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def read_text(self, relative_path: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def resolve(self, relative_path: str) -> Path:
        raise NotImplementedError

    @abstractmethod
    def delete(self, relative_path: str | None) -> None:
        raise NotImplementedError
