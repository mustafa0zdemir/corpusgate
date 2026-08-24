from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.models.document import Chunk, Document


class RetrievalMode(StrEnum):
    lexical = "lexical"
    semantic = "semantic"
    hybrid = "hybrid"
    lexical_fallback = "lexical_fallback"


@dataclass(frozen=True, slots=True)
class RetrievalFilters:
    document_ids: tuple[str, ...] = ()
    file_types: tuple[str, ...] = ()
    heading: str | None = None


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    document: Document
    chunk: Chunk
    score: float
    retrieval_mode: RetrievalMode
    lexical_rank: int | None = None
    semantic_rank: int | None = None
    semantic_score: float | None = None
    combined_rank: int | None = None
    matched_retrieval_modes: tuple[str, ...] = ()
