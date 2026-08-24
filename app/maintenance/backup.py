from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import tarfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from uuid import uuid4

from app.core.config import Settings, get_settings

ALLOWED_ARCHIVE_ROOTS = frozenset({"documents", "cache", "database", "config"})


@dataclass(frozen=True, slots=True)
class BackupResult:
    archive: Path
    document_file_count: int
    cache_file_count: int


class BackupService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def create(self) -> BackupResult:
        backup_root = self.settings.backup_root
        backup_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        backup_root = backup_root.resolve()
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        archive = backup_root / f"pdg-backup-{timestamp}-{uuid4().hex[:8]}.tar.gz"
        temporary_archive = archive.with_suffix(".tar.gz.part")

        with TemporaryDirectory(prefix="pdg-backup-", dir=backup_root) as temporary:
            staging = Path(temporary)
            document_count = _copy_tree_secure(
                self.settings.documents_root.resolve(), staging / "documents"
            )
            cache_count = _copy_tree_secure(self.settings.cache_root.resolve(), staging / "cache")
            database_dir = staging / "database"
            database_dir.mkdir(mode=0o700)
            _backup_sqlite(self.settings.sqlite_database_path, database_dir / "gateway.db")

            config_dir = staging / "config"
            config_dir.mkdir(mode=0o700)
            example = _find_config_example()
            if example is not None:
                shutil.copy2(example, config_dir / ".env.example")

            (staging / "manifest.json").write_text(
                json.dumps(
                    {
                        "format_version": 1,
                        "created_at": datetime.now(UTC).isoformat(),
                        "document_file_count": document_count,
                        "cache_file_count": cache_count,
                    },
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            with tarfile.open(temporary_archive, "w:gz") as bundle:
                for name in ("documents", "cache", "database", "config", "manifest.json"):
                    bundle.add(staging / name, arcname=name, recursive=True)

        os.chmod(temporary_archive, 0o600)
        os.replace(temporary_archive, archive)
        return BackupResult(archive, document_count, cache_count)

    def restore(self, archive: Path) -> None:
        archive = archive.resolve(strict=True)
        backup_root = self.settings.backup_root.resolve()
        if backup_root not in archive.parents:
            raise ValueError("The restore archive must be inside the configured backup directory.")

        with TemporaryDirectory(prefix="pdg-restore-", dir=backup_root) as temporary:
            staging = Path(temporary)
            with tarfile.open(archive, "r:gz") as bundle:
                _validate_archive(bundle)
                bundle.extractall(staging, filter="data")

            _replace_directory(staging / "documents", self.settings.documents_root)
            _replace_directory(staging / "cache", self.settings.cache_root)
            database_path = self.settings.sqlite_database_path
            database_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copy2(staging / "database" / "gateway.db", database_path)
            database_path.with_name(database_path.name + "-wal").unlink(missing_ok=True)
            database_path.with_name(database_path.name + "-shm").unlink(missing_ok=True)
            os.chmod(database_path, 0o600)


def _copy_tree_secure(source: Path, destination: Path) -> int:
    if source.is_symlink() or not source.is_dir():
        raise ValueError("Backup source roots must be real directories.")
    destination.mkdir(parents=True, mode=0o700)
    file_count = 0
    for entry in source.iterdir():
        if entry.is_symlink():
            raise ValueError("Symbolic links are not allowed in backup sources.")
        target = destination / entry.name
        if entry.is_dir():
            file_count += _copy_tree_secure(entry, target)
        elif entry.is_file():
            shutil.copy2(entry, target)
            file_count += 1
    return file_count


def _backup_sqlite(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise ValueError("The SQLite database does not exist.")
    with (
        sqlite3.connect(source) as source_connection,
        sqlite3.connect(destination) as destination_connection,
    ):
        source_connection.backup(destination_connection)
    os.chmod(destination, 0o600)


def _validate_archive(bundle: tarfile.TarFile) -> None:
    for member in bundle.getmembers():
        path = PurePosixPath(member.name)
        if (
            path.is_absolute()
            or ".." in path.parts
            or member.issym()
            or member.islnk()
            or not path.parts
            or (path.parts[0] not in ALLOWED_ARCHIVE_ROOTS and member.name != "manifest.json")
        ):
            raise ValueError("The backup archive contains an unsafe entry.")


def _replace_directory(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise ValueError("The backup archive is incomplete.")
    if destination.is_symlink():
        raise ValueError("Restore destinations must not be symbolic links.")
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    for entry in destination.iterdir():
        if entry.is_symlink() or entry.is_file():
            entry.unlink()
        elif entry.is_dir():
            shutil.rmtree(entry)
    shutil.copytree(source, destination, dirs_exist_ok=True)
    for root, directories, files in os.walk(destination):
        os.chmod(root, 0o700)
        for directory in directories:
            os.chmod(Path(root) / directory, 0o700)
        for file in files:
            os.chmod(Path(root) / file, 0o600)


def _find_config_example() -> Path | None:
    candidates = (Path.cwd() / ".env.example", Path("/app/.env.example"))
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backup or restore persistent gateway data.")
    parser.add_argument("--restore", type=Path, help="Restore the given archive")
    parser.add_argument(
        "--confirm-restore",
        action="store_true",
        help="Required with --restore because current persistent data is replaced",
    )
    arguments = parser.parse_args()
    service = BackupService(get_settings())
    if arguments.restore:
        if not arguments.confirm_restore:
            parser.error("--confirm-restore is required with --restore")
        service.restore(arguments.restore)
        print(json.dumps({"status": "restored"}))
        return
    result = service.create()
    print(
        json.dumps(
            {
                "status": "created",
                "archive": result.archive.name,
                "document_file_count": result.document_file_count,
                "cache_file_count": result.cache_file_count,
            }
        )
    )
