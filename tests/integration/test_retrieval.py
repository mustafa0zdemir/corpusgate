from __future__ import annotations

from fastapi.testclient import TestClient


def _retrieval_document() -> bytes:
    return (
        "# Before\n\n"
        + "alpha context boundary material " * 15
        + "\n\n# Target\n\ncentralneedle onlytargetneedle "
        + "beta focused evidence details " * 15
        + "\n\n# After\n\n"
        + "gamma followup references notes " * 15
        + "\n\n# More\n\ncentralneedle "
        + "delta independent findings summary " * 15
    ).encode()


def _upload(client: TestClient, headers: dict[str, str]) -> str:
    response = client.post(
        "/api/v1/documents",
        headers=headers,
        files={"file": ("retrieval.md", _retrieval_document(), "text/markdown")},
    )
    assert response.status_code == 201, response.text
    return response.json()["document_id"]


def test_retrieval_enforces_both_budgets_and_reports_source_metrics(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    document_id = _upload(client, auth_headers)
    response = client.get(
        f"/api/v1/documents/{document_id}/search",
        headers=auth_headers,
        params={
            "q": "centralneedle",
            "top_k": 10,
            "max_chars": 80,
            "max_tokens": 12,
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["metrics"]["returned_chars"] <= 80
    assert payload["metrics"]["returned_estimated_tokens"] <= 12
    assert payload["metrics"]["returned_chunk_count"] == len(payload["items"])
    assert payload["metrics"]["full_document_estimated_tokens"] > 12
    assert payload["metrics"]["search_ms"] >= 0
    assert payload["metrics"]["cache_used"] is True
    item = payload["items"][0]
    assert item["document_id"] == document_id
    assert item["document_name"] == "retrieval.md"
    assert item["content_length"] == len(item["content"])
    assert item["position"]["chunk_index"] >= 0
    assert item["position"]["char_start"] < item["position"]["char_end"]


def test_retrieval_caps_parameters_and_supports_query_bound_cursor(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    document_id = _upload(client, auth_headers)
    capped = client.get(
        f"/api/v1/documents/{document_id}/search",
        headers=auth_headers,
        params={
            "q": "centralneedle",
            "top_k": 100,
            "max_chars": 250_000,
            "max_tokens": 64_000,
        },
    ).json()
    assert capped["top_k"] == 20
    assert capped["max_chars"] == 5_000
    assert capped["max_tokens"] == 1_000

    first = client.get(
        f"/api/v1/documents/{document_id}/search",
        headers=auth_headers,
        params={
            "q": "centralneedle",
            "top_k": 1,
            "max_chars": 250_000,
            "max_tokens": 64_000,
        },
    ).json()
    assert first["top_k"] == 1
    assert first["max_chars"] == 5_000
    assert first["max_tokens"] == 1_000
    assert first["next_cursor"]

    second = client.get(
        f"/api/v1/documents/{document_id}/search",
        headers=auth_headers,
        params={
            "q": "centralneedle",
            "top_k": 1,
            "cursor": first["next_cursor"],
        },
    )
    assert second.status_code == 200
    assert second.json()["items"][0]["chunk_id"] != first["items"][0]["chunk_id"]

    invalid = client.get(
        f"/api/v1/documents/{document_id}/search",
        headers=auth_headers,
        params={"q": "different query", "cursor": first["next_cursor"]},
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "invalid_cursor"


def test_neighbors_are_opt_in_limited_and_budgeted(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    document_id = _upload(client, auth_headers)
    default = client.get(
        f"/api/v1/documents/{document_id}/search",
        headers=auth_headers,
        params={"q": "onlytargetneedle", "top_k": 3},
    ).json()
    with_neighbors = client.get(
        f"/api/v1/documents/{document_id}/search",
        headers=auth_headers,
        params={
            "q": "onlytargetneedle",
            "top_k": 3,
            "neighbor_window": 3,
            "max_tokens": 200,
        },
    ).json()

    assert len(default["items"]) == 1
    assert {item["relation"] for item in with_neighbors["items"]} == {
        "match",
        "previous",
        "next",
    }
    assert with_neighbors["metrics"]["returned_estimated_tokens"] <= 200
    assert len({item["chunk_id"] for item in with_neighbors["items"]}) == len(
        with_neighbors["items"]
    )


def test_semantic_request_reports_fallback_and_invalid_mode_is_controlled(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    document_id = _upload(client, auth_headers)
    fallback = client.get(
        f"/api/v1/documents/{document_id}/search",
        headers=auth_headers,
        params={"q": "centralneedle", "retrieval_mode": "semantic"},
    )
    assert fallback.status_code == 200
    assert fallback.json()["requested_retrieval_mode"] == "semantic"
    assert fallback.json()["retrieval_mode"] == "lexical_fallback"
    assert fallback.json()["items"]

    invalid = client.get(
        f"/api/v1/documents/{document_id}/search",
        headers=auth_headers,
        params={"q": "centralneedle", "retrieval_mode": "unsupported"},
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "invalid_retrieval_mode"
