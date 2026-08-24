from __future__ import annotations

import sqlite3

import pytest
from pydantic import SecretStr, ValidationError

from app import __version__
from app.cli import command_scan
from app.core.config import Settings
from app.core.database import SCHEMA_VERSION, Database
from app.repositories.sqlite import SQLiteDocumentRepository


def test_version_has_one_canonical_release_value() -> None:
    assert __version__ == "0.1.0"


def test_product_identity_and_environment_contract_are_corpusgate() -> None:
    settings = Settings(api_key=SecretStr("a" * 24))

    assert settings.app_name == "CorpusGate"
    assert Settings.model_config["env_prefix"] == "CORPUSGATE_"
    assert settings.vector_collection == "corpusgate_chunks_v1"


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"port": 70_000}, "less than or equal to 65535"),
        (
            {"default_retrieval_mode": "unsupported"},
            "default retrieval mode must be lexical, semantic, or hybrid",
        ),
        (
            {"chunk_size_tokens": 100, "chunk_overlap_tokens": 100},
            "chunk overlap must be smaller than chunk size",
        ),
        (
            {"max_response_chars": 1_000, "default_response_max_chars": 2_000},
            "default character budget must not exceed maximum character budget",
        ),
    ],
)
def test_invalid_configuration_fails_early(override: dict, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        Settings(api_key=SecretStr("a" * 24), **override)


def test_database_schema_is_versioned_and_future_schema_is_rejected(settings) -> None:
    database = Database(settings)
    database.create_schema()
    assert database.schema_version() == SCHEMA_VERSION
    database.dispose()

    path = settings.sqlite_database_path
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO schema_migrations(version) VALUES (?)", (SCHEMA_VERSION + 1,)
        )

    future_database = Database(settings)
    with pytest.raises(RuntimeError, match="newer than supported"):
        future_database.create_schema()
    future_database.dispose()


def test_scan_imports_supported_inbox_files_and_skips_hidden_files(settings, tmp_path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "guide.md").write_text("# Guide\n\nPrivate bounded retrieval.", encoding="utf-8")
    (inbox / ".env").write_text("SECRET=not-indexed", encoding="utf-8")
    configured = settings.model_copy(update={"inbox_dir": inbox})

    assert command_scan(configured) == 0

    database = Database(configured)
    database.create_schema()
    with database.session_factory() as session:
        documents, total = SQLiteDocumentRepository(session).list(0, 10)
        assert total == 1
        assert documents[0].original_filename == "guide.md"
    database.dispose()
