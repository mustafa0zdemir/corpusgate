from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="PDG_",
        extra="ignore",
    )

    app_name: str = "Private Document Gateway"
    app_version: str = "0.2.0"
    environment: str = "production"
    host: str = "0.0.0.0"
    port: int = 8000
    api_key: SecretStr = Field(min_length=24)

    data_dir: Path = Path("data")
    database_url: str | None = None
    max_file_size_mb: int = Field(default=25, ge=1, le=1024)
    max_archive_uncompressed_mb: int = Field(default=250, ge=1, le=4096)
    upload_buffer_bytes: int = Field(default=1024 * 1024, ge=64 * 1024, le=8 * 1024 * 1024)

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

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def markdown_dir(self) -> Path:
        return self.data_dir / "markdown"

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.data_dir / 'gateway.db').as_posix()}"

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    @property
    def max_archive_uncompressed_bytes(self) -> int:
        return self.max_archive_uncompressed_mb * 1024 * 1024

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def allowed_host_list(self) -> list[str]:
        return [item.strip() for item in self.allowed_hosts.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
