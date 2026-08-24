from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import text


class CountingParser:
    def __init__(self) -> None:
        self.calls = 0

    def parse(self, path: Path) -> str:
        self.calls += 1
        content = path.read_text(encoding="utf-8")
        if "BROKEN" in content:
            raise RuntimeError("fixture conversion failure")
        return content


def _upload(client: TestClient, headers: dict[str, str], content: str):
    return client.post(
        "/api/v1/documents",
        headers=headers,
        files={"file": ("versioned.md", content.encode(), "text/markdown")},
    )


def test_unchanged_upload_uses_cache_and_changed_upload_reindexes_atomically(
    client: TestClient, auth_headers: dict[str, str], settings
) -> None:
    parser = CountingParser()
    client.app.state.parser = parser
    first = _upload(
        client,
        auth_headers,
        "# Legacy Topic\n\nlegacyterm " + "stable context " * 30,
    )
    assert first.status_code == 201
    document_id = first.json()["document_id"]
    old_upload = next((settings.data_dir / "uploads").iterdir())
    old_markdown = next((settings.data_dir / "markdown").iterdir())

    unchanged = _upload(
        client,
        auth_headers,
        "# Legacy Topic\n\nlegacyterm " + "stable context " * 30,
    )
    assert unchanged.json()["deduplicated"] is True
    assert unchanged.json()["reindexed"] is False
    assert parser.calls == 1

    changed = _upload(
        client,
        auth_headers,
        "# Current Topic\n\ncurrentterm " + "fresh context " * 30,
    )
    assert changed.status_code == 201, changed.text
    assert changed.json()["document_id"] == document_id
    assert changed.json()["reindexed"] is True
    assert parser.calls == 2
    assert not old_upload.exists()
    assert not old_markdown.exists()

    current_search = client.get(
        f"/api/v1/documents/{document_id}/search",
        headers=auth_headers,
        params={"q": "currentterm"},
    )
    old_search = client.get(
        f"/api/v1/documents/{document_id}/search",
        headers=auth_headers,
        params={"q": "legacyterm"},
    )
    assert current_search.json()["items"]
    assert old_search.json()["items"] == []


def test_failed_reindex_keeps_previous_version_and_does_not_block_next_upload(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    parser = CountingParser()
    client.app.state.parser = parser
    first = _upload(client, auth_headers, "# Reliable\n\nkeepterm " + "context " * 30)
    document_id = first.json()["document_id"]

    broken = _upload(client, auth_headers, "# BROKEN\n\nreplacement")
    assert broken.status_code == 422
    metadata = client.get(f"/api/v1/documents/{document_id}", headers=auth_headers).json()
    assert metadata["status"] == "ready"
    preserved = client.get(
        f"/api/v1/documents/{document_id}/search",
        headers=auth_headers,
        params={"q": "keepterm"},
    )
    assert preserved.json()["items"]

    next_document = client.post(
        "/api/v1/documents",
        headers=auth_headers,
        files={"file": ("other.md", b"# Healthy\n\nnextterm", "text/markdown")},
    )
    assert next_document.status_code == 201


def test_fts_bm25_weights_heading_and_delete_cleans_index(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    parser = CountingParser()
    client.app.state.parser = parser
    response = client.post(
        "/api/v1/documents",
        headers=auth_headers,
        files={
            "file": (
                "ranking.md",
                (
                    "# Quantum Battery\n\n" + "introductory material " * 15 + "\n\n"
                    "# Appendix\n\nquantum battery appears in body " + "supporting material " * 15
                ).encode(),
                "text/markdown",
            )
        },
    )
    document_id = response.json()["document_id"]
    search = client.get(
        f"/api/v1/documents/{document_id}/search",
        headers=auth_headers,
        params={"q": "quantum battery", "top_k": 5},
    ).json()

    assert search["items"][0]["heading"] == "Quantum Battery"
    assert [item["score"] for item in search["items"]] == sorted(
        [item["score"] for item in search["items"]], reverse=True
    )

    client.delete(f"/api/v1/documents/{document_id}", headers=auth_headers)
    with client.app.state.database.session_factory() as session:
        indexed = session.execute(
            text("SELECT COUNT(*) FROM chunk_fts WHERE document_id = :document_id"),
            {"document_id": document_id},
        ).scalar_one()
    assert indexed == 0
