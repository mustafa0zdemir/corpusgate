from __future__ import annotations

import re
import unicodedata
from time import perf_counter

from app.core.config import Settings
from app.embeddings.base import EmbeddingUnavailableError
from app.repositories.base import DocumentRepository
from app.repositories.search import SearchIndex
from app.retrieval.base import RetrievalStrategy, StrategyResult
from app.retrieval.types import RankedCandidate, RetrievalFilters, RetrievalMode
from app.semantic.runtime import SemanticRuntime

WORD_RE = re.compile(r"\w+", re.UNICODE)


class LexicalRetrievalStrategy(RetrievalStrategy):
    def __init__(self, index: SearchIndex):
        self.index = index

    def retrieve(
        self,
        query: str,
        *,
        filters: RetrievalFilters,
        limit: int,
        offset: int = 0,
    ) -> StrategyResult:
        started = perf_counter()
        terms = list(dict.fromkeys(WORD_RE.findall(_normalize(query))))
        candidates = self.index.search(terms, filters=filters, limit=limit + 1, offset=offset)
        has_more = len(candidates) > limit
        ranked = [
            RankedCandidate(
                candidate.document,
                candidate.chunk,
                candidate.score,
                RetrievalMode.lexical,
                lexical_rank=offset + rank,
                matched_retrieval_modes=(RetrievalMode.lexical.value,),
            )
            for rank, candidate in enumerate(candidates[:limit], 1)
        ]
        return StrategyResult(
            ranked,
            RetrievalMode.lexical,
            RetrievalMode.lexical,
            has_more=has_more,
            timings_ms={"lexical_search_ms": round((perf_counter() - started) * 1000, 3)},
        )


class SemanticRetrievalStrategy(RetrievalStrategy):
    def __init__(
        self,
        settings: Settings,
        repository: DocumentRepository,
        runtime: SemanticRuntime,
    ):
        self.settings = settings
        self.repository = repository
        self.runtime = runtime

    def retrieve(
        self,
        query: str,
        *,
        filters: RetrievalFilters,
        limit: int,
        offset: int = 0,
    ) -> StrategyResult:
        if not self.runtime.available:
            raise EmbeddingUnavailableError(
                self.runtime.unavailable_reason or "Semantic search is disabled."
            )
        provider = self.runtime.provider
        store = self.runtime.store
        capacity = self.runtime.capacity
        assert provider is not None and store is not None and capacity is not None
        store.ensure_collection(
            provider.dimension,
            embedding_model=provider.model_name,
            embedding_version=provider.model_version,
        )
        embedding_started = perf_counter()
        query_vector = capacity.run(
            lambda: provider.embed_query(query),
            timeout=self.settings.embedding_timeout_seconds,
        )
        query_embedding_ms = round((perf_counter() - embedding_started) * 1000, 3)
        search_started = perf_counter()
        hits = store.search(
            query_vector,
            filters=filters,
            embedding_model=provider.model_name,
            embedding_version=provider.model_version,
            limit=limit + 1,
            offset=offset,
        )
        semantic_search_ms = round((perf_counter() - search_started) * 1000, 3)
        hits = [hit for hit in hits if hit.score >= self.settings.semantic_min_score]
        rows = self.repository.get_chunks_by_ids([hit.chunk_id for hit in hits[:limit]])
        by_id = {chunk.id: (document, chunk) for document, chunk in rows}
        candidates = []
        for rank, hit in enumerate(hits[:limit], 1):
            row = by_id.get(hit.chunk_id)
            if row is None:
                continue
            candidates.append(
                RankedCandidate(
                    row[0],
                    row[1],
                    hit.score,
                    RetrievalMode.semantic,
                    semantic_rank=offset + rank,
                    semantic_score=hit.score,
                    matched_retrieval_modes=(RetrievalMode.semantic.value,),
                )
            )
        return StrategyResult(
            candidates,
            RetrievalMode.semantic,
            RetrievalMode.semantic,
            has_more=len(hits) > limit,
            timings_ms={
                "query_embedding_ms": query_embedding_ms,
                "semantic_search_ms": semantic_search_ms,
            },
        )


class HybridRetrievalStrategy(RetrievalStrategy):
    def __init__(
        self,
        settings: Settings,
        lexical: LexicalRetrievalStrategy,
        semantic: SemanticRetrievalStrategy,
    ):
        self.settings = settings
        self.lexical = lexical
        self.semantic = semantic

    def retrieve(
        self,
        query: str,
        *,
        filters: RetrievalFilters,
        limit: int,
        offset: int = 0,
    ) -> StrategyResult:
        started = perf_counter()
        pool_size = max((offset + limit) * 3, 30)
        lexical = self.lexical.retrieve(query, filters=filters, limit=pool_size)
        semantic = self.semantic.retrieve(query, filters=filters, limit=pool_size)
        merged: dict[str, RankedCandidate] = {}
        scores: dict[str, float] = {}
        for result in (lexical, semantic):
            for candidate in result.candidates:
                rank = candidate.lexical_rank or candidate.semantic_rank
                assert rank is not None
                scores[candidate.chunk.id] = scores.get(candidate.chunk.id, 0.0) + 1.0 / (
                    self.settings.hybrid_rrf_k + rank
                )
                previous = merged.get(candidate.chunk.id)
                merged[candidate.chunk.id] = RankedCandidate(
                    candidate.document,
                    candidate.chunk,
                    scores[candidate.chunk.id],
                    RetrievalMode.hybrid,
                    lexical_rank=candidate.lexical_rank
                    or (previous.lexical_rank if previous else None),
                    semantic_rank=candidate.semantic_rank
                    or (previous.semantic_rank if previous else None),
                    semantic_score=candidate.semantic_score
                    if candidate.semantic_score is not None
                    else (previous.semantic_score if previous else None),
                    matched_retrieval_modes=tuple(
                        sorted(
                            set(candidate.matched_retrieval_modes)
                            | set(previous.matched_retrieval_modes if previous else ())
                        )
                    ),
                )
        ordered = sorted(
            merged.values(),
            key=lambda item: (-scores[item.chunk.id], item.chunk.id),
        )
        ranked = [
            RankedCandidate(
                item.document,
                item.chunk,
                scores[item.chunk.id],
                RetrievalMode.hybrid,
                lexical_rank=item.lexical_rank,
                semantic_rank=item.semantic_rank,
                semantic_score=item.semantic_score,
                combined_rank=offset + rank,
                matched_retrieval_modes=item.matched_retrieval_modes,
            )
            for rank, item in enumerate(ordered[offset : offset + limit], 1)
        ]
        return StrategyResult(
            ranked,
            RetrievalMode.hybrid,
            RetrievalMode.hybrid,
            has_more=offset + limit < len(ordered),
            timings_ms={
                **lexical.timings_ms,
                **semantic.timings_ms,
                "hybrid_search_ms": round((perf_counter() - started) * 1000, 3),
            },
        )


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()
