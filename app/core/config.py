from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

from app._version import __version__


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="PDG_",
        extra="ignore",
    )

    app_name: str = "Private Document Gateway"
    environment: str = "production"
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65_535)
    api_key: SecretStr = Field(min_length=24)
    mcp_auth_tokens: SecretStr | None = None
    mcp_auth_token_file: Path | None = None

    data_dir: Path = Path("data")
    documents_dir: Path | None = None
    inbox_dir: Path = Path("/inbox")
    cache_dir: Path | None = None
    backup_dir: Path | None = None
    database_url: str | None = None
    max_file_size_mb: int = Field(default=25, ge=1, le=1024)
    max_archive_uncompressed_mb: int = Field(default=250, ge=1, le=4096)
    upload_buffer_bytes: int = Field(default=1024 * 1024, ge=64 * 1024, le=8 * 1024 * 1024)
    max_request_body_mb: int | None = Field(default=None, ge=1, le=2048)
    min_free_disk_mb: int = Field(default=100, ge=0, le=102_400)

    chunk_size_tokens: int = Field(default=500, ge=50, le=8_000)
    chunk_overlap_tokens: int = Field(default=50, ge=0, le=1_000)
    min_chunk_tokens: int = Field(default=40, ge=1, le=1_000)
    default_page_size: int = Field(default=20, ge=1, le=100)
    max_page_size: int = Field(default=100, ge=1, le=500)
    default_search_top_k: int = Field(default=5, ge=1, le=50)
    max_search_top_k: int = Field(default=20, ge=1, le=100)
    max_neighbor_window: int = Field(default=1, ge=0, le=3)
    default_response_max_chars: int = Field(default=8_000, ge=200, le=100_000)
    max_response_chars: int = Field(default=24_000, ge=500, le=250_000)
    default_response_max_tokens: int = Field(default=2_000, ge=50, le=32_000)
    max_response_tokens: int = Field(default=6_000, ge=100, le=64_000)

    rate_limit_requests: int = Field(default=120, ge=1, le=100_000)
    rate_limit_window_seconds: int = Field(default=60, ge=1, le=3_600)
    log_level: str = "INFO"
    public_base_url: str | None = None
    max_concurrent_conversions: int = Field(default=1, ge=1, le=16)
    conversion_timeout_seconds: int = Field(default=120, ge=1, le=3_600)
    conversion_queue_timeout_seconds: int = Field(default=5, ge=0, le=300)
    search_timeout_seconds: int = Field(default=10, ge=1, le=300)

    semantic_enabled: bool = False
    semantic_fallback_enabled: bool = True
    default_retrieval_mode: str = "lexical"
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embedding_model_version: str = "fastembed-0.8.0-onnx-q"
    embedding_dimension: int = Field(default=384, ge=32, le=8_192)
    embedding_query_prefix: str = ""
    embedding_passage_prefix: str = ""
    embedding_cache_dir: Path = Path("/models")
    embedding_offline: bool = True
    embedding_batch_size: int = Field(default=32, ge=1, le=512)
    embedding_threads: int = Field(default=2, ge=1, le=64)
    max_concurrent_embeddings: int = Field(default=1, ge=1, le=8)
    embedding_timeout_seconds: int = Field(default=180, ge=1, le=3_600)
    embedding_queue_timeout_seconds: int = Field(default=5, ge=0, le=300)
    vector_store_url: str = "http://qdrant:6333"
    vector_collection: str = "pdg_chunks_v1"
    vector_store_timeout_seconds: int = Field(default=10, ge=1, le=300)
    semantic_min_score: float = Field(default=0.25, ge=-1.0, le=1.0)
    hybrid_rrf_k: int = Field(default=60, ge=1, le=1_000)
    max_results_per_document: int = Field(default=3, ge=0, le=100)

    cors_origins: str = ""
    allowed_hosts: str = "localhost,localhost:*,127.0.0.1,127.0.0.1:*"

    @field_validator("chunk_overlap_tokens")
    @classmethod
    def overlap_must_be_smaller_than_chunk(cls, value: int, info) -> int:
        chunk_size = info.data.get("chunk_size_tokens", 500)
        if value >= chunk_size:
            raise ValueError("chunk overlap must be smaller than chunk size")
        return value

    @field_validator("min_chunk_tokens")
    @classmethod
    def minimum_must_not_exceed_chunk_size(cls, value: int, info) -> int:
        chunk_size = info.data.get("chunk_size_tokens", 500)
        if value > chunk_size:
            raise ValueError("minimum chunk size must not exceed chunk size")
        return value

    @field_validator("default_retrieval_mode")
    @classmethod
    def retrieval_mode_must_be_supported(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"lexical", "semantic", "hybrid"}:
            raise ValueError("default retrieval mode must be lexical, semantic, or hybrid")
        return normalized

    @field_validator("log_level")
    @classmethod
    def log_level_must_be_supported(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}:
            raise ValueError("log level must be CRITICAL, ERROR, WARNING, INFO, or DEBUG")
        return normalized

    @model_validator(mode="after")
    def validate_contract(self) -> Settings:
        if self.default_page_size > self.max_page_size:
            raise ValueError("default page size must not exceed maximum page size")
        if self.default_search_top_k > self.max_search_top_k:
            raise ValueError("default search top_k must not exceed maximum search top_k")
        if self.default_response_max_chars > self.max_response_chars:
            raise ValueError("default character budget must not exceed maximum character budget")
        if self.default_response_max_tokens > self.max_response_tokens:
            raise ValueError("default token budget must not exceed maximum token budget")
        if (
            self.max_request_body_mb is not None
            and self.max_request_body_mb < self.max_file_size_mb
        ):
            raise ValueError("maximum request body must not be smaller than maximum file size")
        if self.semantic_enabled:
            vector_url = make_url(self.vector_store_url)
            if vector_url.get_backend_name() not in {"http", "https"} or not vector_url.host:
                raise ValueError("semantic search requires an HTTP(S) vector store URL")
            if not self.vector_collection.strip():
                raise ValueError("semantic search requires a vector collection name")
        return self

    @property
    def app_version(self) -> str:
        return __version__

    @property
    def uploads_dir(self) -> Path:
        return self.documents_root

    @property
    def markdown_dir(self) -> Path:
        return self.cache_root

    @property
    def documents_root(self) -> Path:
        return self.documents_dir or self.data_dir / "uploads"

    @property
    def cache_root(self) -> Path:
        return self.cache_dir or self.data_dir / "markdown"

    @property
    def backup_root(self) -> Path:
        return self.backup_dir or self.data_dir / "backups"

    @property
    def sqlite_database_path(self) -> Path:
        url = make_url(self.resolved_database_url)
        if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
            raise ValueError("Maintenance commands require a file-backed SQLite database.")
        return Path(url.database).resolve()

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.data_dir / 'gateway.db').as_posix()}"

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    @property
    def max_request_body_bytes(self) -> int:
        configured_mb = self.max_request_body_mb or self.max_file_size_mb + 2
        return configured_mb * 1024 * 1024

    @property
    def min_free_disk_bytes(self) -> int:
        return self.min_free_disk_mb * 1024 * 1024

    @property
    def max_archive_uncompressed_bytes(self) -> int:
        return self.max_archive_uncompressed_mb * 1024 * 1024

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def allowed_host_list(self) -> list[str]:
        return [item.strip() for item in self.allowed_hosts.split(",") if item.strip()]

    def active_mcp_tokens(self) -> tuple[str, ...]:
        values: list[str] = []
        if self.mcp_auth_tokens is not None:
            values.append(self.mcp_auth_tokens.get_secret_value())
        if self.mcp_auth_token_file is not None:
            try:
                values.append(self.mcp_auth_token_file.read_text(encoding="utf-8"))
            except OSError as exc:
                raise ValueError("The configured MCP token file cannot be read.") from exc
        if not values:
            values.append(self.api_key.get_secret_value())

        tokens = tuple(
            dict.fromkeys(
                token.strip()
                for value in values
                for token in value.replace("\n", ",").split(",")
                if token.strip()
            )
        )
        if not tokens or any(len(token) < 24 for token in tokens):
            raise ValueError("Every MCP authentication token must contain at least 24 characters.")
        return tokens


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
