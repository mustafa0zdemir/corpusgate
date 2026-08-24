from __future__ import annotations

import threading
from pathlib import Path
from time import perf_counter
from typing import Any

from app.embeddings.base import EmbeddingProvider, EmbeddingUnavailableError


class FastEmbedEmbeddingProvider(EmbeddingProvider):
    """Lazy, process-local CPU embedding provider backed by ONNX Runtime."""

    def __init__(
        self,
        *,
        model_name: str,
        model_version: str,
        dimension: int,
        cache_dir: Path,
        batch_size: int,
        threads: int,
        offline: bool,
        query_prefix: str = "",
        passage_prefix: str = "",
    ):
        self._model_name = model_name
        self._model_version = model_version
        self._dimension = dimension
        self.cache_dir = cache_dir
        self.batch_size = batch_size
        self.threads = threads
        self.offline = offline
        self.query_prefix = query_prefix
        self.passage_prefix = passage_prefix
        self._model: Any | None = None
        self._load_ms = 0.0
        self._lock = threading.Lock()

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def model_version(self) -> str:
        return self._model_version

    @property
    def dimension(self) -> int:
        return self._dimension

    def load(self) -> float:
        if self._model is not None:
            return self._load_ms
        with self._lock:
            if self._model is not None:
                return self._load_ms
            started = perf_counter()
            try:
                from fastembed import TextEmbedding

                self.cache_dir.mkdir(parents=True, exist_ok=True)
                self._model = TextEmbedding(
                    model_name=self.model_name,
                    cache_dir=str(self.cache_dir),
                    threads=self.threads,
                    providers=["CPUExecutionProvider"],
                    cuda=False,
                    local_files_only=self.offline,
                )
                actual_dimension = int(TextEmbedding.get_embedding_size(self.model_name))
                if actual_dimension != self.dimension:
                    self._model = None
                    raise EmbeddingUnavailableError(
                        "Configured embedding dimension does not match the local model."
                    )
            except EmbeddingUnavailableError:
                raise
            except Exception as exc:
                self._model = None
                raise EmbeddingUnavailableError(
                    "The local embedding model is unavailable."
                ) from exc
            self._load_ms = round((perf_counter() - started) * 1000, 3)
            return self._load_ms

    def embed_query(self, query: str) -> list[float]:
        model = self._require_model()
        try:
            vector = next(iter(model.embed(self.query_prefix + query, batch_size=1)))
            return self._validated_vector(vector.tolist())
        except EmbeddingUnavailableError:
            raise
        except Exception as exc:
            raise EmbeddingUnavailableError("The query embedding could not be generated.") from exc

    def embed_passages(self, passages: list[str]) -> list[list[float]]:
        if not passages:
            return []
        model = self._require_model()
        prepared = [self.passage_prefix + passage for passage in passages]
        try:
            return [
                self._validated_vector(vector.tolist())
                for vector in model.embed(prepared, batch_size=self.batch_size)
            ]
        except EmbeddingUnavailableError:
            raise
        except Exception as exc:
            raise EmbeddingUnavailableError("Passage embeddings could not be generated.") from exc

    def _require_model(self):
        self.load()
        if self._model is None:
            raise EmbeddingUnavailableError("The local embedding model is unavailable.")
        return self._model

    def _validated_vector(self, vector: list[float]) -> list[float]:
        if len(vector) != self.dimension:
            raise EmbeddingUnavailableError(
                "The embedding output dimension does not match the configured vector index."
            )
        return [float(value) for value in vector]
