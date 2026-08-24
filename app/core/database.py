from __future__ import annotations

import sqlite3
from collections.abc import Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import Settings


class Base(DeclarativeBase):
    pass


class Database:
    def __init__(self, settings: Settings):
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

    def session(self) -> Iterator[Session]:
        with self.session_factory() as session:
            yield session

    def dispose(self) -> None:
        self.engine.dispose()


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
