from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

os.environ.setdefault("PDG_API_KEY", "test-api-key-0123456789abcdef")

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

TEST_API_KEY = "test-api-key-0123456789abcdef"


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        api_key=SecretStr(TEST_API_KEY),
        environment="test",
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        chunk_size_tokens=100,
        chunk_overlap_tokens=10,
        min_chunk_tokens=10,
        max_file_size_mb=1,
        default_response_max_chars=2_000,
        max_response_chars=5_000,
        default_response_max_tokens=500,
        max_response_tokens=1_000,
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"X-API-Key": TEST_API_KEY}
