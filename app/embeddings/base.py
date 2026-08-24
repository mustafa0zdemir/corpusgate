from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingUnavailableError(RuntimeError):
    """Raised when optional local embedding infrastructure cannot serve a request."""


class EmbeddingProvider(ABC):
    @property
    @abstractmethod
    def model_name(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def model_version(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def dimension(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def load(self) -> float:
        """Load the model once and return load duration in milliseconds."""
        raise NotImplementedError

    @abstractmethod
    def embed_query(self, query: str) -> list[float]:
        raise NotImplementedError

    @abstractmethod
    def embed_passages(self, passages: list[str]) -> list[list[float]]:
        raise NotImplementedError
