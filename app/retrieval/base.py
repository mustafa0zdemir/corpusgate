from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.retrieval.types import RankedCandidate, RetrievalFilters, RetrievalMode


@dataclass(frozen=True, slots=True)
class StrategyResult:
    candidates: list[RankedCandidate]
    requested_mode: RetrievalMode
    actual_mode: RetrievalMode
    has_more: bool = False
    fallback_reason: str | None = None


class RetrievalStrategy(ABC):
    @abstractmethod
    def retrieve(
        self,
        query: str,
        *,
        filters: RetrievalFilters,
        limit: int,
        offset: int = 0,
    ) -> StrategyResult:
        raise NotImplementedError
