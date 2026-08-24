from __future__ import annotations

from fastapi.testclient import TestClient


def _upload(client: TestClient, headers: dict[str, str], content: bytes = b""):
    payload = content or (
        b"# Product Notes\n\nPrivate gateway keeps documents local.\n\n"
        b"## Search\n\nKeyword search returns relevant chunks only."
    )
    return client.post(
        "/api/v1/documents",
        headers=headers,
        files={"file": ("notes.md", payload, "text/markdown")},
    )


def test_health_is_public_but_document_api_requires_key(client: TestClient) -> None:
    assert client.get("/health").json()["status"] == "ok"
    response = client.get("/api/v1/documents")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_upload_convert_cache_chunk_search_and_delete(
    client: TestClient,
    auth_headers: dict[str, str],
    settings,
) -> None:
    response = _upload(client, auth_headers)
    assert response.status_code == 201, response.text
    uploaded = response.json()
    assert uploaded["status"] == "ready"
    assert uploaded["original_filename"] == "notes.md"
    document_id = uploaded["document_id"]

    stored_files = list((settings.data_dir / "uploads").iterdir())
    assert len(stored_files) == 1
    assert stored_files[0].name == f"{document_id}.md"
    markdown_files = list((settings.data_dir / "markdown").iterdir())
    assert len(markdown_files) == 1
    markdown_file = markdown_files[0]
    assert markdown_file.name.startswith(f"{document_id}-")
    assert markdown_file.exists()

    metadata = client.get(f"/api/v1/documents/{document_id}", headers=auth_headers)
    assert metadata.status_code == 200
    assert metadata.json()["chunk_count"] >= 1
    assert "storage_path" not in metadata.json()

    markdown = client.get(
        f"/api/v1/documents/{document_id}/markdown",
        headers=auth_headers,
        params={"max_chars": 25},
    ).json()
    assert markdown["returned_chars"] == 25
    assert markdown["has_more"] is True

    chunks = client.get(f"/api/v1/documents/{document_id}/chunks", headers=auth_headers).json()
    assert chunks["items"][0]["heading"] == "Product Notes"

    search = client.get(
        f"/api/v1/documents/{document_id}/search",
        headers=auth_headers,
        params={"q": "relevant chunks", "top_k": 2, "max_chars": 300},
    )
    assert search.status_code == 200, search.text
    assert search.json()["items"][0]["document_id"] == document_id
    assert "relevant chunks" in search.json()["items"][0]["content"].lower()

    duplicate = _upload(client, auth_headers)
    assert duplicate.status_code == 201
    assert duplicate.json()["document_id"] == document_id
    assert duplicate.json()["deduplicated"] is True
    assert len(list((settings.data_dir / "uploads").iterdir())) == 1

    deleted = client.delete(f"/api/v1/documents/{document_id}", headers=auth_headers)
    assert deleted.status_code == 204
    assert not stored_files[0].exists()
    assert not markdown_file.exists()
    assert client.get(f"/api/v1/documents/{document_id}", headers=auth_headers).status_code == 404


def test_rejects_unsupported_and_spoofed_files(
    client: TestClient, auth_headers: dict[str, str], settings
) -> None:
    unsupported = client.post(
        "/api/v1/documents",
        headers=auth_headers,
        files={"file": ("malware.exe", b"MZ", "application/octet-stream")},
    )
    assert unsupported.status_code == 415

    spoofed_pdf = client.post(
        "/api/v1/documents",
        headers=auth_headers,
        files={"file": ("fake.pdf", b"not a pdf", "application/pdf")},
    )
    assert spoofed_pdf.status_code == 415
    assert list((settings.data_dir / "uploads").iterdir()) == []


def test_filename_is_metadata_only(
    client: TestClient, auth_headers: dict[str, str], settings
) -> None:
    response = client.post(
        "/api/v1/documents",
        headers=auth_headers,
        files={"file": ("../../notes.txt", b"safe text", "text/plain")},
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["original_filename"] == "notes.txt"
    upload = next((settings.data_dir / "uploads").iterdir())
    assert upload.parent == (settings.data_dir / "uploads")
    assert upload.name.startswith(payload["document_id"])
