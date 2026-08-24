from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import urllib.error
import urllib.request
from dataclasses import asdict
from pathlib import Path

from pydantic import ValidationError

from app import __version__
from app.chunking.markdown import MarkdownChunkStrategy
from app.core.config import Settings, get_settings
from app.core.database import SCHEMA_VERSION, Database
from app.core.resources import OperationCapacity
from app.maintenance.backup import BackupService
from app.repositories.sqlite import SQLiteDocumentRepository
from app.semantic.runtime import create_semantic_runtime
from app.services.documents import DocumentService
from app.services.scanner import DocumentScanner
from app.services.semantic_index import SemanticIndexService
from app.storage.local import LocalFileStorage


def _print(payload: dict | list) -> None:
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str))


def _settings() -> Settings:
    try:
        return get_settings()
    except ValidationError as exc:
        errors = [
            {"setting": ".".join(map(str, error["loc"])), "message": error["msg"]}
            for error in exc.errors(include_input=False, include_url=False)
        ]
        _print({"status": "invalid_config", "errors": errors})
        raise SystemExit(2) from None


def _document_service(settings: Settings):
    from app.parsers.markitdown import MarkItDownDocumentParser

    database = Database(settings)
    database.create_schema()
    capacity = OperationCapacity(
        operation="conversion",
        capacity=settings.max_concurrent_conversions,
        queue_timeout=settings.conversion_queue_timeout_seconds,
    )
    runtime = create_semantic_runtime(settings)
    session = database.session_factory()
    repository = SQLiteDocumentRepository(session)
    semantic_index = (
        SemanticIndexService(settings, repository, runtime) if runtime.available else None
    )
    service = DocumentService(
        settings=settings,
        repository=repository,
        parser=MarkItDownDocumentParser(),
        storage=LocalFileStorage(
            settings.data_dir,
            settings.max_file_size_mb,
            documents_dir=settings.documents_root,
            markdown_dir=settings.cache_root,
            min_free_bytes=settings.min_free_disk_bytes,
        ),
        chunker=MarkdownChunkStrategy(
            target_tokens=settings.chunk_size_tokens,
            overlap_tokens=settings.chunk_overlap_tokens,
            min_chunk_tokens=settings.min_chunk_tokens,
        ),
        conversion_capacity=capacity,
        semantic_index=semantic_index,
    )
    return database, session, capacity, runtime, service


def command_status(settings: Settings) -> int:
    base_url = (settings.public_base_url or f"http://127.0.0.1:{settings.port}").rstrip("/")
    checks: dict[str, str] = {}
    for endpoint in ("health", "ready"):
        try:
            with urllib.request.urlopen(f"{base_url}/{endpoint}", timeout=3) as response:
                checks[endpoint] = "ok" if response.status == 200 else f"http_{response.status}"
        except (OSError, urllib.error.URLError):
            checks[endpoint] = "unreachable"
    healthy = all(value == "ok" for value in checks.values())
    _print({"status": "ok" if healthy else "unavailable", "version": __version__, **checks})
    return 0 if healthy else 1


def command_mcp_smoke(settings: Settings) -> int:
    import httpx2
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client

    async def exercise() -> dict[str, object]:
        base_url = (settings.public_base_url or f"http://127.0.0.1:{settings.port}").rstrip("/")
        token = settings.active_mcp_tokens()[0]
        async with httpx2.AsyncClient(
            headers={"Authorization": f"Bearer {token}"}, timeout=5
        ) as http_client:
            transport = streamable_http_client(
                f"{base_url}/mcp", http_client=http_client, terminate_on_close=False
            )
            async with Client(transport, mode="legacy") as client:
                tools = await client.list_tools()
                listed = await client.call_tool("list_documents", {"offset": 0, "limit": 1})
                if listed.is_error:
                    raise RuntimeError("The MCP list_documents smoke call failed.")
                return {
                    "tool_count": len(tools.tools),
                    "tools": sorted(tool.name for tool in tools.tools),
                }

    result = asyncio.run(exercise())
    _print({"status": "ok", "version": __version__, **result})
    return 0


def command_doctor(settings: Settings) -> int:
    checks: list[dict[str, str]] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "status": "ok" if ok else "error", "detail": detail})

    for name, path in (
        ("documents", settings.documents_root),
        ("cache", settings.cache_root),
        ("database", settings.sqlite_database_path.parent),
        ("backup", settings.backup_root),
    ):
        try:
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
            add(name, path.is_dir() and os.access(path, os.R_OK | os.W_OK), "readable and writable")
        except OSError as exc:
            add(name, False, type(exc).__name__)

    try:
        database = Database(settings)
        database.create_schema()
        add("database_connection", database.is_ready(), "SQLite is reachable")
        version = database.schema_version()
        add("schema", version == SCHEMA_VERSION, f"version {version}/{SCHEMA_VERSION}")
        database.dispose()
    except Exception as exc:
        add("database_connection", False, type(exc).__name__)

    try:
        usage = shutil.disk_usage(settings.data_dir.resolve())
        free_mb = usage.free // (1024 * 1024)
        add("disk_space", usage.free >= settings.min_free_disk_bytes, f"{free_mb} MiB free")
    except OSError as exc:
        add("disk_space", False, type(exc).__name__)

    if settings.semantic_enabled:
        runtime = create_semantic_runtime(settings)
        try:
            add(
                "vector_store",
                bool(runtime.store and runtime.store.health()),
                "configured endpoint",
            )
            cache_ready = settings.embedding_cache_dir.is_dir() and any(
                settings.embedding_cache_dir.iterdir()
            )
            add("embedding_model_cache", cache_ready, "local model cache")
        finally:
            runtime.close()
    else:
        checks.append({"check": "semantic", "status": "skipped", "detail": "disabled"})

    base_url = (settings.public_base_url or f"http://127.0.0.1:{settings.port}").rstrip("/")
    try:
        with urllib.request.urlopen(f"{base_url}/ready", timeout=3) as response:
            add("mcp_service", response.status == 200, "HTTP service is ready")
    except (OSError, urllib.error.URLError):
        checks.append({"check": "mcp_service", "status": "warning", "detail": "not running"})

    failed = any(check["status"] == "error" for check in checks)
    _print({"status": "error" if failed else "ok", "version": __version__, "checks": checks})
    return 1 if failed else 0


def command_scan(settings: Settings) -> int:
    database, session, capacity, runtime, service = _document_service(settings)
    try:
        result = DocumentScanner(settings.inbox_dir, service).scan()
        _print({"status": "completed", **asdict(result)})
        return 1 if result.failed else 0
    finally:
        session.close()
        capacity.shutdown()
        runtime.close()
        database.dispose()


def command_list_documents(settings: Settings, limit: int, offset: int) -> int:
    database = Database(settings)
    database.create_schema()
    try:
        with database.session_factory() as session:
            documents, total = SQLiteDocumentRepository(session).list(offset, min(limit, 100))
            _print(
                {
                    "items": [
                        {
                            "document_id": item.id,
                            "document_name": item.original_filename,
                            "status": item.status,
                            "file_type": item.extension,
                            "chunks": item.chunk_count,
                            "updated_at": item.updated_at,
                        }
                        for item in documents
                    ],
                    "offset": offset,
                    "limit": min(limit, 100),
                    "total": total,
                }
            )
        return 0
    finally:
        database.dispose()


def command_reindex(settings: Settings, force: bool, semantic: bool) -> int:
    from app.maintenance.reindex import rebuild_cache
    from app.maintenance.semantic import reindex_semantic

    result: dict[str, object] = {"cache": rebuild_cache(settings, force=force)}
    if semantic:
        runtime = create_semantic_runtime(settings)
        if not runtime.available:
            _print({"status": "error", "message": "semantic runtime is unavailable"})
            return 1
        try:
            result["semantic"] = reindex_semantic(settings, runtime, force=force)
        finally:
            runtime.close()
    _print({"status": "completed", **result})
    return 0


def command_backup(settings: Settings) -> int:
    result = BackupService(settings).create()
    _print(
        {
            "status": "created",
            "archive": result.archive.name,
            "document_file_count": result.document_file_count,
            "cache_file_count": result.cache_file_count,
        }
    )
    return 0


def command_restore(settings: Settings, archive: Path, confirm: bool) -> int:
    if not confirm:
        _print({"status": "confirmation_required", "message": "pass --confirm-restore"})
        return 2
    BackupService(settings).restore(archive)
    _print({"status": "restored"})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="private-document-gateway-admin")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("version")
    subcommands.add_parser("status")
    subcommands.add_parser("doctor")
    subcommands.add_parser("mcp-smoke")
    subcommands.add_parser("scan")
    listing = subcommands.add_parser("list-documents")
    listing.add_argument("--limit", type=int, default=20)
    listing.add_argument("--offset", type=int, default=0)
    reindex = subcommands.add_parser("reindex")
    reindex.add_argument("--force", action="store_true")
    reindex.add_argument("--semantic", action="store_true")
    subcommands.add_parser("backup")
    restore = subcommands.add_parser("restore")
    restore.add_argument("archive", type=Path)
    restore.add_argument("--confirm-restore", action="store_true")
    return parser


def main() -> None:
    arguments = build_parser().parse_args()
    if arguments.command == "version":
        _print({"name": "Private Document Gateway", "version": __version__})
        return
    settings = _settings()
    handlers = {
        "status": lambda: command_status(settings),
        "doctor": lambda: command_doctor(settings),
        "mcp-smoke": lambda: command_mcp_smoke(settings),
        "scan": lambda: command_scan(settings),
        "list-documents": lambda: command_list_documents(
            settings, arguments.limit, arguments.offset
        ),
        "reindex": lambda: command_reindex(settings, arguments.force, arguments.semantic),
        "backup": lambda: command_backup(settings),
        "restore": lambda: command_restore(settings, arguments.archive, arguments.confirm_restore),
    }
    try:
        raise SystemExit(handlers[arguments.command]())
    except (OSError, ValueError, RuntimeError) as exc:
        _print({"status": "error", "error_type": type(exc).__name__, "message": str(exc)})
        raise SystemExit(1) from None
    except Exception as exc:
        _print(
            {
                "status": "error",
                "error_type": type(exc).__name__,
                "message": "The operation failed; inspect the sanitized service logs.",
            }
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
