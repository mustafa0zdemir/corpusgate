from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.retrieval.types import RetrievalFilters
from app.vectorstores.base import (
    VectorDimensionMismatchError,
    VectorRecord,
    VectorSearchHit,
    VectorStore,
    VectorStoreUnavailableError,
)


class QdrantVectorStore(VectorStore):
    """Qdrant adapter; vendor types do not escape this module."""

    def __init__(self, *, url: str, collection: str, timeout_seconds: int):
        try:
            from qdrant_client import QdrantClient
        except ImportError as exc:
            raise VectorStoreUnavailableError(
                "Semantic dependencies are not installed in this image."
            ) from exc
        self.collection = collection
        self.timeout_seconds = timeout_seconds
        self.client = QdrantClient(url=url, timeout=timeout_seconds, prefer_grpc=False)

    def ensure_collection(
        self,
        dimension: int,
        *,
        embedding_model: str,
        embedding_version: str,
    ) -> None:
        models = _models()
        try:
            if not self.client.collection_exists(self.collection):
                self.client.create_collection(
                    collection_name=self.collection,
                    vectors_config=models.VectorParams(
                        size=dimension,
                        distance=models.Distance.COSINE,
                        on_disk=True,
                    ),
                    on_disk_payload=True,
                    metadata={
                        "embedding_model": embedding_model,
                        "embedding_version": embedding_version,
                        "dimension": dimension,
                    },
                    timeout=self.timeout_seconds,
                )
                for field in (
                    "document_id",
                    "file_type",
                    "heading",
                    "embedding_model",
                    "embedding_version",
                    "content_hash",
                ):
                    self.client.create_payload_index(
                        collection_name=self.collection,
                        field_name=field,
                        field_schema=models.PayloadSchemaType.KEYWORD,
                        wait=True,
                    )
                return
            information = self.client.get_collection(self.collection)
            vectors = information.config.params.vectors
            actual_dimension = getattr(vectors, "size", None)
            if actual_dimension != dimension:
                raise VectorDimensionMismatchError(
                    "The Qdrant collection dimension does not match the embedding model."
                )
        except VectorDimensionMismatchError:
            raise
        except Exception as exc:
            raise VectorStoreUnavailableError("The vector store is unavailable.") from exc

    def health(self) -> bool:
        try:
            return bool(self.client.collection_exists(self.collection))
        except Exception:
            return False

    def list_document_records(
        self,
        document_id: str,
        *,
        embedding_model: str,
        embedding_version: str,
    ) -> list[VectorRecord]:
        models = _models()
        records: list[VectorRecord] = []
        offset = None
        query_filter = models.Filter(
            must=[
                _match("document_id", document_id),
                _match("embedding_model", embedding_model),
                _match("embedding_version", embedding_version),
            ]
        )
        try:
            while True:
                points, offset = self.client.scroll(
                    collection_name=self.collection,
                    scroll_filter=query_filter,
                    limit=256,
                    offset=offset,
                    with_payload=True,
                    with_vectors=True,
                    timeout=self.timeout_seconds,
                )
                records.extend(_record_from_point(point) for point in points)
                if offset is None:
                    break
        except Exception as exc:
            raise VectorStoreUnavailableError("Vector metadata could not be read.") from exc
        return records

    def upsert(self, records: list[VectorRecord]) -> None:
        if not records:
            return
        models = _models()
        points = [
            models.PointStruct(
                id=record.chunk_id,
                vector=record.vector,
                payload={
                    "document_id": record.document_id,
                    "chunk_id": record.chunk_id,
                    "document_name": record.document_name,
                    "file_type": record.file_type,
                    "heading": record.heading,
                    "position": record.position,
                    "content_hash": record.content_hash,
                    "embedding_model": record.embedding_model,
                    "embedding_version": record.embedding_version,
                    "embedding_dimension": len(record.vector),
                    "indexed_at": record.indexed_at.astimezone(UTC).isoformat(),
                },
            )
            for record in records
        ]
        try:
            self.client.upsert(
                collection_name=self.collection,
                points=points,
                wait=True,
                timeout=self.timeout_seconds,
            )
        except Exception as exc:
            raise VectorStoreUnavailableError("Vectors could not be persisted.") from exc

    def delete_chunks(self, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        models = _models()
        try:
            self.client.delete(
                collection_name=self.collection,
                points_selector=models.PointIdsList(points=chunk_ids),
                wait=True,
                timeout=self.timeout_seconds,
            )
        except Exception as exc:
            raise VectorStoreUnavailableError("Stale vectors could not be removed.") from exc

    def delete_document(self, document_id: str) -> None:
        models = _models()
        try:
            if not self.client.collection_exists(self.collection):
                return
            self.client.delete(
                collection_name=self.collection,
                points_selector=models.FilterSelector(
                    filter=models.Filter(must=[_match("document_id", document_id)])
                ),
                wait=True,
                timeout=self.timeout_seconds,
            )
        except Exception as exc:
            raise VectorStoreUnavailableError("Document vectors could not be removed.") from exc

    def search(
        self,
        query_vector: list[float],
        *,
        filters: RetrievalFilters,
        embedding_model: str,
        embedding_version: str,
        limit: int,
        offset: int = 0,
    ) -> list[VectorSearchHit]:
        if limit <= 0:
            return []
        models = _models()
        must = [
            _match("embedding_model", embedding_model),
            _match("embedding_version", embedding_version),
        ]
        if filters.document_ids:
            must.append(_match_any("document_id", list(filters.document_ids)))
        if filters.file_types:
            must.append(_match_any("file_type", list(filters.file_types)))
        if filters.heading:
            must.append(_match("heading", filters.heading))
        try:
            response = self.client.query_points(
                collection_name=self.collection,
                query=query_vector,
                query_filter=models.Filter(must=must),
                limit=limit,
                offset=offset,
                with_payload=True,
                with_vectors=False,
                timeout=self.timeout_seconds,
            )
        except Exception as exc:
            raise VectorStoreUnavailableError("Semantic search is unavailable.") from exc
        return [
            VectorSearchHit(
                chunk_id=str(point.id),
                score=float(point.score),
                payload=dict(point.payload or {}),
            )
            for point in response.points
        ]

    def close(self) -> None:
        try:
            self.client.close()
        except Exception:
            return


def _models():
    from qdrant_client import models

    return models


def _match(key: str, value: str):
    models = _models()
    return models.FieldCondition(key=key, match=models.MatchValue(value=value))


def _match_any(key: str, values: list[str]):
    models = _models()
    return models.FieldCondition(key=key, match=models.MatchAny(any=values))


def _record_from_point(point) -> VectorRecord:
    payload: dict[str, Any] = dict(point.payload or {})
    raw_vector = point.vector
    if isinstance(raw_vector, dict):
        raw_vector = next(iter(raw_vector.values()), [])
    indexed_at = datetime.fromisoformat(payload["indexed_at"])
    return VectorRecord(
        chunk_id=str(payload["chunk_id"]),
        document_id=str(payload["document_id"]),
        document_name=str(payload["document_name"]),
        file_type=str(payload["file_type"]),
        heading=payload.get("heading"),
        position=dict(payload.get("position") or {}),
        content_hash=str(payload["content_hash"]),
        embedding_model=str(payload["embedding_model"]),
        embedding_version=str(payload["embedding_version"]),
        indexed_at=indexed_at,
        vector=[float(value) for value in (raw_vector or [])],
    )
