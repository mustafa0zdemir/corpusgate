from __future__ import annotations

from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.main import create_app
from tests.conftest import TEST_API_KEY, TEST_MCP_TOKEN


def test_mcp_http_requires_bearer_and_rejects_other_credentials(client: TestClient) -> None:
    missing = client.post("/mcp", json={})
    invalid = client.post("/mcp", headers={"Authorization": "Bearer invalid-token"}, json={})
    api_key_only = client.post("/mcp", headers={"X-API-Key": TEST_API_KEY}, json={})
    valid = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {TEST_MCP_TOKEN}"},
        json={},
    )

    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert api_key_only.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"
    assert valid.status_code != 401


def test_mcp_token_rotation_accepts_multiple_environment_tokens(settings) -> None:
    current = "current-mcp-token-0123456789abcdef"
    previous = "previous-mcp-token-0123456789abcde"
    rotated = settings.model_copy(update={"mcp_auth_tokens": SecretStr(f"{current},{previous}")})
    with TestClient(create_app(rotated)) as client:
        for token in (current, previous):
            response = client.post(
                "/mcp",
                headers={"Authorization": f"Bearer {token}"},
                json={},
            )
            assert response.status_code != 401


def test_mcp_token_can_be_loaded_and_rotated_from_secret_file(settings, tmp_path) -> None:
    secret_file = tmp_path / "mcp_token"
    first = "file-mcp-token-first-0123456789"
    second = "file-mcp-token-second-012345678"
    secret_file.write_text(first, encoding="utf-8")
    file_settings = settings.model_copy(
        update={
            "mcp_auth_tokens": None,
            "mcp_auth_token_file": secret_file,
        }
    )
    with TestClient(create_app(file_settings)) as client:
        accepted = client.post("/mcp", headers={"Authorization": f"Bearer {first}"}, json={})
        assert accepted.status_code != 401

        secret_file.write_text(second, encoding="utf-8")
        rotated = client.post("/mcp", headers={"Authorization": f"Bearer {second}"}, json={})
        retired = client.post("/mcp", headers={"Authorization": f"Bearer {first}"}, json={})
        assert rotated.status_code != 401
        assert retired.status_code == 401


def test_rate_limit_is_per_credential_and_health_remains_available(settings) -> None:
    limited = settings.model_copy(
        update={"rate_limit_requests": 2, "rate_limit_window_seconds": 60}
    )
    with TestClient(create_app(limited)) as client:
        headers = {"X-API-Key": TEST_API_KEY}
        assert client.get("/api/v1/documents", headers=headers).status_code == 200
        assert client.get("/api/v1/documents", headers=headers).status_code == 200
        blocked = client.get("/api/v1/documents", headers=headers)
        assert blocked.status_code == 429
        assert blocked.headers["retry-after"]
        assert client.get("/health").status_code == 200


def test_request_body_limit_rejects_before_upload_processing(settings) -> None:
    limited = settings.model_copy(update={"max_request_body_mb": 1})
    with TestClient(create_app(limited)) as client:
        response = client.post(
            "/api/v1/documents",
            headers={"X-API-Key": TEST_API_KEY},
            files={"file": ("large.txt", b"x" * (1024 * 1024 + 1), "text/plain")},
        )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_too_large"


def test_health_is_minimal_ready_is_public_and_secrets_are_not_logged(
    client: TestClient, capsys
) -> None:
    health = client.get("/health")
    ready = client.get("/ready")
    client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {TEST_MCP_TOKEN}-invalid"},
        json={"secret_marker": TEST_MCP_TOKEN},
    )
    logs = capsys.readouterr().err

    assert health.json() == {"status": "ok"}
    assert ready.json() == {"status": "ready"}
    assert TEST_MCP_TOKEN not in logs
    assert "secret_marker" not in logs
