from __future__ import annotations

import io
import tarfile

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.maintenance.backup import BackupService
from app.maintenance.reindex import rebuild_cache


def test_restart_backup_restore_and_cache_rebuild(settings, auth_headers) -> None:
    with TestClient(create_app(settings)) as first_client:
        upload = first_client.post(
            "/api/v1/documents",
            headers=auth_headers,
            files={
                "file": (
                    "persistent.md",
                    b"# Persistent\n\nrestartproof backupterm cacheterm",
                    "text/markdown",
                )
            },
        )
        document_id = upload.json()["document_id"]

    with TestClient(create_app(settings)) as restarted_client:
        persisted = restarted_client.get(f"/api/v1/documents/{document_id}", headers=auth_headers)
        assert persisted.status_code == 200

    backup = BackupService(settings).create()
    assert backup.archive.is_file()
    assert backup.document_file_count == 1
    assert backup.cache_file_count == 1
    with tarfile.open(backup.archive, "r:gz") as bundle:
        members = bundle.getnames()
        assert "config/.env.example" in members
        assert all(not name.endswith("/.env") for name in members)
        assert all("token" not in name.lower() for name in members)

    for path in settings.documents_root.iterdir():
        path.unlink()
    for path in settings.cache_root.iterdir():
        path.unlink()
    settings.sqlite_database_path.unlink()

    BackupService(settings).restore(backup.archive)
    with TestClient(create_app(settings)) as restored_client:
        restored = restored_client.get(
            f"/api/v1/documents/{document_id}/search",
            headers=auth_headers,
            params={"q": "backupterm"},
        )
        assert restored.status_code == 200
        assert restored.json()["items"]

    for path in settings.cache_root.iterdir():
        path.unlink()
    result = rebuild_cache(settings)
    assert result == {"rebuilt": 1, "skipped": 0, "failed": 0}
    with TestClient(create_app(settings)) as rebuilt_client:
        markdown = rebuilt_client.get(
            f"/api/v1/documents/{document_id}/markdown", headers=auth_headers
        )
        assert markdown.status_code == 200
        assert "cacheterm" in markdown.json()["content"]


def test_restore_rejects_tar_traversal(settings) -> None:
    settings.backup_root.mkdir(parents=True)
    archive = settings.backup_root / "unsafe.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        member = tarfile.TarInfo("../outside.txt")
        content = b"unsafe"
        member.size = len(content)
        bundle.addfile(member, io.BytesIO(content))

    with pytest.raises(ValueError, match="unsafe entry"):
        BackupService(settings).restore(archive)


def test_cache_rebuild_continues_after_a_missing_source(
    settings, auth_headers: dict[str, str]
) -> None:
    with TestClient(create_app(settings)) as client:
        broken = client.post(
            "/api/v1/documents",
            headers=auth_headers,
            files={"file": ("broken.md", b"# Broken\n\nmissing source", "text/markdown")},
        ).json()
        healthy = client.post(
            "/api/v1/documents",
            headers=auth_headers,
            files={"file": ("healthy.md", b"# Healthy\n\nrebuild me", "text/markdown")},
        ).json()

    (settings.documents_root / f"{broken['document_id']}.md").unlink()
    for cache_file in settings.cache_root.iterdir():
        cache_file.unlink()

    assert rebuild_cache(settings) == {"rebuilt": 1, "skipped": 0, "failed": 1}
    with TestClient(create_app(settings)) as client:
        metadata = client.get(f"/api/v1/documents/{healthy['document_id']}", headers=auth_headers)
        assert metadata.status_code == 200
        assert metadata.json()["status"] == "ready"
