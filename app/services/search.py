from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import unicodedata
from abc import ABC, abstractmethod
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from app.chunking.tokens import ApproximateTokenEstimator, TokenEstimator
from app.core.config import Settings
from app.core.errors import AppError, DocumentNotFoundError
from app.models.document import Chunk, Document
from app.repositories.base import DocumentRepository
from app.repositories.search import SearchIndex

WORD_RE = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class ChunkPosition:
    chunk_index: int
    char_start: int
    char_end: int
    page_number: int | None
    slide_number: int | None
    sheet_name: str | None


@dataclass(frozen=True, slots=True)
class SearchHit:
    document_id: str
    document_name: str
    chunk_id: str
    heading: str | None
    position: ChunkPosition
    score: float
    content: str
    content_length: int
    token_count: int
    relation: str = "match"


@dataclass(frozen=True, slots=True)
class RetrievalMetrics:
    full_document_estimated_tokens: int
    returned_estimated_tokens: int
    returned_chars: int
    returned_chunk_count: int
    search_ms: float
    cache_used: bool


@dataclass(frozen=True, slots=True)
class RetrievalPage:
    items: list[SearchHit]
    next_cursor: str | None
    top_k: int
    max_chars: int
    max_tokens: int
    metrics: RetrievalMetrics


class SearchService(ABC):
    @abstractmethod
    def search(
        self,
        query: str,
        *,
        document_ids: list[str] | None = None,
        top_k: int | None = None,
        max_chars: int | None = None,
        max_tokens: int | None = None,
        cursor: str | None = None,
        neighbor_window: int = 0,
    ) -> RetrievalPage:
        raise NotImplementedError


class FullTextSearchService(SearchService):
    def __init__(
        self,
        settings: Settings,
        repository: DocumentRepository,
        index: SearchIndex,
        estimator: TokenEstimator | None = None,
    ):
        self.settings = settings
        self.repository = repository
        self.index = index
        self.estimator = estimator or ApproximateTokenEstimator()

    def search(
        self,
        query: str,
        *,
        document_ids: list[str] | None = None,
        top_k: int | None = None,
        max_chars: int | None = None,
        max_tokens: int | None = None,
        cursor: str | None = None,
        neighbor_window: int = 0,
    ) -> RetrievalPage:
        started = perf_counter()
        normalized_ids = list(dict.fromkeys(document_ids or [])) or None
        documents = self._validate_documents(normalized_ids)
        terms = list(dict.fromkeys(WORD_RE.findall(_normalize(query))))
        if not terms:
            raise AppError("Search query must contain text.", status_code=422, code="invalid_query")

        actual_top_k = min(
            top_k or self.settings.default_search_top_k,
            self.settings.max_search_top_k,
        )
        actual_chars = min(
            max_chars or self.settings.default_response_max_chars,
            self.settings.max_response_chars,
        )
        actual_tokens = min(
            max_tokens or self.settings.default_response_max_tokens,
            self.settings.max_response_tokens,
        )
        actual_neighbors = min(max(neighbor_window, 0), self.settings.max_neighbor_window)
        fingerprint = _cursor_fingerprint("search", query, normalized_ids)
        offset = _decode_cursor(cursor, fingerprint) if cursor else 0

        batch_size = max(actual_top_k * 20, 50)
        candidates = self.index.search(
            terms,
            document_ids=normalized_ids,
            limit=batch_size + 1,
            offset=offset,
        )
        has_index_more = len(candidates) > batch_size
        candidates = candidates[:batch_size]
        budget = _ContentBudget(actual_chars, actual_tokens, self.estimator)
        selected: list[SearchHit] = []
        selected_chunks: list[Chunk] = []
        matched_documents: dict[str, Document] = {document.id: document for document in documents}
        consumed = 0

        for candidate in candidates:
            consumed += 1
            matched_documents[candidate.document.id] = candidate.document
            related = [candidate.chunk]
            if actual_neighbors:
                neighbors = self.repository.get_neighbor_chunks(
                    candidate.document.id,
                    candidate.chunk.chunk_index,
                    actual_neighbors,
                )
                related.extend(
                    sorted(
                        (chunk for chunk in neighbors if chunk.id != candidate.chunk.id),
                        key=lambda chunk: (
                            abs(chunk.chunk_index - candidate.chunk.chunk_index),
                            chunk.chunk_index,
                        ),
                    )
                )

            for chunk in related:
                if len(selected) >= actual_top_k or budget.exhausted:
                    break
                if _is_duplicate_or_overlapping(chunk, selected_chunks):
                    continue
                content = budget.take(chunk.content)
                if not content:
                    continue
                relation = _relation(chunk.chunk_index, candidate.chunk.chunk_index)
                selected.append(
                    _hit(
                        candidate.document,
                        chunk,
                        content,
                        candidate.score if relation == "match" else candidate.score / 2,
                        relation,
                        self.estimator,
                    )
                )
                selected_chunks.append(chunk)

            if len(selected) >= actual_top_k or budget.exhausted:
                break

        has_more = consumed < len(candidates) or has_index_more
        next_cursor = _encode_cursor(offset + consumed, fingerprint) if has_more else None
        full_tokens = sum(document.markdown_tokens for document in matched_documents.values())
        metrics = RetrievalMetrics(
            full_document_estimated_tokens=full_tokens,
            returned_estimated_tokens=budget.used_tokens,
            returned_chars=budget.used_chars,
            returned_chunk_count=len(selected),
            search_ms=round((perf_counter() - started) * 1000, 3),
            cache_used=True,
        )
        return RetrievalPage(
            items=selected,
            next_cursor=next_cursor,
            top_k=actual_top_k,
            max_chars=actual_chars,
            max_tokens=actual_tokens,
            metrics=metrics,
        )

    def section(
        self,
        document_id: str,
        *,
        start_chunk: int = 0,
        chunk_count: int = 3,
        max_chars: int | None = None,
        max_tokens: int | None = None,
        cursor: str | None = None,
    ) -> RetrievalPage:
        started = perf_counter()
        document = self.repository.get(document_id)
        if document is None:
            raise DocumentNotFoundError
        actual_count = min(chunk_count, self.settings.max_page_size)
        actual_chars = min(
            max_chars or self.settings.default_response_max_chars,
            self.settings.max_response_chars,
        )
        actual_tokens = min(
            max_tokens or self.settings.default_response_max_tokens,
            self.settings.max_response_tokens,
        )
        fingerprint = _cursor_fingerprint("section", document_id, None)
        offset = _decode_cursor(cursor, fingerprint) if cursor else start_chunk
        chunks, total = self.repository.list_chunks(document_id, offset, actual_count + 1)
        has_index_more = len(chunks) > actual_count
        chunks = chunks[:actual_count]
        budget = _ContentBudget(actual_chars, actual_tokens, self.estimator)
        selected: list[SearchHit] = []
        consumed = 0
        for chunk in chunks:
            consumed += 1
            if budget.exhausted:
                break
            content = budget.take(chunk.content)
            if not content:
                continue
            selected.append(_hit(document, chunk, content, 0.0, "section", self.estimator))

        has_more = offset + consumed < total or has_index_more
        next_cursor = _encode_cursor(offset + consumed, fingerprint) if has_more else None
        return RetrievalPage(
            items=selected,
            next_cursor=next_cursor,
            top_k=actual_count,
            max_chars=actual_chars,
            max_tokens=actual_tokens,
            metrics=RetrievalMetrics(
                full_document_estimated_tokens=document.markdown_tokens,
                returned_estimated_tokens=budget.used_tokens,
                returned_chars=budget.used_chars,
                returned_chunk_count=len(selected),
                search_ms=round((perf_counter() - started) * 1000, 3),
                cache_used=True,
            ),
        )

    def _validate_documents(self, document_ids: list[str] | None) -> list[Document]:
        if document_ids is None:
            return []
        documents: list[Document] = []
        for document_id in document_ids:
            document = self.repository.get(document_id)
            if document is None:
                raise DocumentNotFoundError
            documents.append(document)
        return documents


class _ContentBudget:
    def __init__(self, max_chars: int, max_tokens: int, estimator: TokenEstimator):
        self.max_chars = max_chars
        self.max_tokens = max_tokens
        self.estimator = estimator
        self.used_chars = 0
        self.used_tokens = 0

    @property
    def exhausted(self) -> bool:
        return self.used_chars >= self.max_chars or self.used_tokens >= self.max_tokens

    def take(self, content: str) -> str:
        remaining_chars = self.max_chars - self.used_chars
        remaining_tokens = self.max_tokens - self.used_tokens
        if remaining_chars <= 0 or remaining_tokens <= 0:
            return ""
        selected = self.estimator.truncate(content[:remaining_chars], remaining_tokens)
        if not selected:
            return ""
        selected_tokens = self.estimator.estimate(selected)
        self.used_chars += len(selected)
        self.used_tokens += selected_tokens
        return selected


def _hit(
    document: Document,
    chunk: Chunk,
    content: str,
    score: float,
    relation: str,
    estimator: TokenEstimator,
) -> SearchHit:
    return SearchHit(
        document_id=document.id,
        document_name=document.original_filename,
        chunk_id=chunk.id,
        heading=chunk.heading,
        position=ChunkPosition(
            chunk_index=chunk.chunk_index,
            char_start=chunk.char_start,
            char_end=chunk.char_end,
            page_number=chunk.page_number,
            slide_number=chunk.slide_number,
            sheet_name=chunk.sheet_name,
        ),
        score=round(score, 8),
        content=content,
        content_length=len(content),
        token_count=estimator.estimate(content),
        relation=relation,
    )


def _relation(chunk_index: int, matched_index: int) -> str:
    if chunk_index < matched_index:
        return "previous"
    if chunk_index > matched_index:
        return "next"
    return "match"


def _is_duplicate_or_overlapping(chunk: Chunk, selected: list[Chunk]) -> bool:
    fingerprint = " ".join(chunk.content.casefold().split())
    words = set(WORD_RE.findall(fingerprint))
    for previous in selected:
        if chunk.id == previous.id:
            return True
        previous_fingerprint = " ".join(previous.content.casefold().split())
        if fingerprint == previous_fingerprint:
            return True
        if chunk.document_id == previous.document_id:
            overlap = max(
                0,
                min(chunk.char_end, previous.char_end) - max(chunk.char_start, previous.char_start),
            )
            shorter = min(
                chunk.char_end - chunk.char_start,
                previous.char_end - previous.char_start,
            )
            if shorter > 0 and overlap / shorter >= 0.7:
                return True
        previous_words = set(WORD_RE.findall(previous_fingerprint))
        if len(words) >= 10 and len(previous_words) >= 10:
            similarity = len(words & previous_words) / min(len(words), len(previous_words))
            if similarity >= 0.9:
                return True
    return False


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _cursor_fingerprint(kind: str, value: str, document_ids: list[str] | None) -> str:
    payload = json.dumps(
        [kind, _normalize(value), sorted(document_ids or [])],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _encode_cursor(offset: int, fingerprint: str) -> str:
    payload = json.dumps(
        {"v": 1, "offset": offset, "fingerprint": fingerprint},
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(cursor: str, expected_fingerprint: str) -> int:
    try:
        padding = "=" * (-len(cursor) % 4)
        payload: dict[str, Any] = json.loads(base64.urlsafe_b64decode(cursor + padding))
        offset = payload["offset"]
        if (
            payload.get("v") != 1
            or payload.get("fingerprint") != expected_fingerprint
            or not isinstance(offset, int)
            or offset < 0
        ):
            raise ValueError
        return offset
    except (binascii.Error, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AppError(
            "Invalid or expired cursor.", status_code=422, code="invalid_cursor"
        ) from exc
