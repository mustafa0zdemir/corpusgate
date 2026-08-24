from __future__ import annotations

import sqlite3
from collections.abc import Iterator

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import Settings


class Base(DeclarativeBase):
    pass


class Database:
    def __init__(self, settings: Settings):
        self.settings = settings
        database_url = settings.resolved_database_url
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        self.engine = create_engine(
            database_url,
            connect_args=connect_args,
            pool_pre_ping=True,
        )
        if database_url.startswith("sqlite"):
            _configure_sqlite(self.engine)
        self.session_factory = sessionmaker(
            bind=self.engine,
            class_=Session,
            expire_on_commit=False,
            autoflush=False,
        )

    def create_schema(self) -> None:
        from app.models.document import Chunk, Document  # noqa: F401

        Base.metadata.create_all(self.engine)
        if self.engine.url.get_backend_name() == "sqlite":
            self._migrate_sqlite_schema()
            self._backfill_token_counts()
            self._create_fts_index()

    def _migrate_sqlite_schema(self) -> None:
        additions = {
            "documents": {
                "markdown_tokens": "INTEGER NOT NULL DEFAULT 0",
            },
            "chunks": {
                "token_count": "INTEGER NOT NULL DEFAULT 0",
                "page_number": "INTEGER",
                "slide_number": "INTEGER",
                "sheet_name": "VARCHAR(255)",
            },
        }
        with self.engine.begin() as connection:
            for table, columns in additions.items():
                existing = {
                    row[1]
                    for row in connection.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
                }
                for column, definition in columns.items():
                    if column not in existing:
                        connection.exec_driver_sql(
                            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
                        )

    def _create_fts_index(self) -> None:
        with self.engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5("
                "chunk_id UNINDEXED, document_id UNINDEXED, heading, content, "
                "tokenize='unicode61 remove_diacritics 2')"
            )
            connection.exec_driver_sql(
                "DELETE FROM chunk_fts WHERE chunk_id NOT IN (SELECT id FROM chunks)"
            )
            connection.exec_driver_sql(
                "INSERT INTO chunk_fts(chunk_id, document_id, heading, content) "
                "SELECT c.id, c.document_id, COALESCE(c.heading, ''), c.content "
                "FROM chunks c WHERE NOT EXISTS ("
                "SELECT 1 FROM chunk_fts f WHERE f.chunk_id = c.id)"
            )

    def _backfill_token_counts(self) -> None:
        from app.chunking.tokens import ApproximateTokenEstimator

        estimator = ApproximateTokenEstimator()
        cache_root = self.settings.cache_root.resolve()
        with self.engine.begin() as connection:
            chunks = connection.exec_driver_sql(
                "SELECT id, content FROM chunks WHERE token_count = 0"
            ).fetchall()
            if chunks:
                connection.exec_driver_sql(
                    "UPDATE chunks SET token_count = ? WHERE id = ?",
                    [(estimator.estimate(content), chunk_id) for chunk_id, content in chunks],
                )

            documents = connection.exec_driver_sql(
                "SELECT id, markdown_path FROM documents "
                "WHERE markdown_tokens = 0 AND markdown_path IS NOT NULL"
            ).fetchall()
            updates: list[tuple[int, str]] = []
            for document_id, markdown_path in documents:
                relative_cache_path = markdown_path.removeprefix("markdown/")
                candidate = (cache_root / relative_cache_path).resolve()
                if cache_root not in candidate.parents or not candidate.is_file():
                    continue
                try:
                    updates.append((estimator.estimate(candidate.read_text("utf-8")), document_id))
                except (OSError, UnicodeError):
                    continue
            if updates:
                connection.exec_driver_sql(
                    "UPDATE documents SET markdown_tokens = ? WHERE id = ?",
                    updates,
                )

    def session(self) -> Iterator[Session]:
        with self.session_factory() as session:
            yield session

    def dispose(self) -> None:
        self.engine.dispose()

    def is_ready(self) -> bool:
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return True
        except Exception:
            return False


def _configure_sqlite(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
        if not isinstance(dbapi_connection, sqlite3.Connection):
            return
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()
