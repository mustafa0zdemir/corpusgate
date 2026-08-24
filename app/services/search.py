from __future__ import annotations

import re
import unicodedata
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.core.errors import AppError, DocumentNotFoundError
from app.repositories.base import DocumentRepository, SearchCandidate

WORD_RE = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class SearchHit:
    document_id: str
    original_filename: str
    chunk_id: str
    chunk_index: int
    heading: str | None
    content: str
    score: float


class SearchService(ABC):
    @abstractmethod
    def search(
        self,
        query: str,
        *,
        document_id: str | None,
        top_k: int,
        max_chars: int,
    ) -> list[SearchHit]:
        raise NotImplementedError


class KeywordSearchService(SearchService):
    def __init__(self, repository: DocumentRepository):
        self.repository = repository

    def search(
        self,
        query: str,
        *,
        document_id: str | None,
        top_k: int,
        max_chars: int,
    ) -> list[SearchHit]:
        if document_id is not None and self.repository.get(document_id) is None:
            raise DocumentNotFoundError

        normalized_query = _normalize(query)
        terms = list(dict.fromkeys(WORD_RE.findall(normalized_query)))
        if not terms:
            raise AppError("Search query must contain text.", status_code=422, code="invalid_query")

        candidates = self.repository.search_candidates(
            terms,
            document_id=document_id,
            limit=max(top_k * 20, 50),
        )
        ranked = sorted(
            (
                (self._score(candidate, normalized_query, terms), candidate)
                for candidate in candidates
            ),
            key=lambda item: (-item[0], item[1].chunk.chunk_index),
        )

        hits: list[SearchHit] = []
        remaining = max_chars
        for score, candidate in ranked:
            if len(hits) >= top_k or remaining <= 0:
                break
            per_hit_limit = min(2_500, remaining)
            content = _snippet(candidate.chunk.content, terms, per_hit_limit)
            if not content:
                continue
            hits.append(
                SearchHit(
                    document_id=candidate.document.id,
                    original_filename=candidate.document.original_filename,
                    chunk_id=candidate.chunk.id,
                    chunk_index=candidate.chunk.chunk_index,
                    heading=candidate.chunk.heading,
                    content=content,
                    score=round(score, 3),
                )
            )
            remaining -= len(content)
        return hits

    @staticmethod
    def _score(candidate: SearchCandidate, query: str, terms: list[str]) -> float:
        content = _normalize(candidate.chunk.content)
        heading = _normalize(candidate.chunk.heading or "")
        score = sum(content.count(term) for term in terms)
        score += 2.5 * sum(heading.count(term) for term in terms)
        if query in content:
            score += 5
        return float(score)


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _snippet(content: str, terms: list[str], limit: int) -> str:
    if limit <= 0:
        return ""
    if len(content) <= limit:
        return content

    normalized = _normalize(content)
    positions = [normalized.find(term) for term in terms]
    first_match = min((position for position in positions if position >= 0), default=0)
    start = max(first_match - limit // 4, 0)
    end = min(start + limit, len(content))
    start = max(end - limit, 0)
    snippet = content[start:end]
    if start:
        snippet = "…" + snippet[1:]
    if end < len(content):
        snippet = snippet[:-1] + "…"
    return snippet
