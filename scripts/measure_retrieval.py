from __future__ import annotations

import json
import os
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from pydantic import SecretStr

os.environ.setdefault("PDG_API_KEY", "measurement-api-key-0123456789")

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

API_KEY = "measurement-api-key-0123456789"


def sample_document() -> bytes:
    sections = [
        (
            "# Network Isolation\n\n"
            + "Private deployments keep document bytes inside operator controlled storage. " * 70
        ),
        (
            "# Incremental Indexing\n\n"
            "A changed document is detected by its unique content fingerprint. "
            + "The index update replaces stale rows in one local database transaction. "
            * 70
        ),
        (
            "# Retrieval Budgets\n\n"
            + "Every retrieval response stops when its configured content allowance is full. " * 70
        ),
        (
            "# Operations\n\n"
            + "Health checks and persistent volumes support a small self hosted installation. " * 70
        ),
    ]
    return "\n\n".join(sections).encode()


def main() -> None:
    with TemporaryDirectory(prefix="pdg-measurement-") as temporary:
        settings = Settings(
            api_key=SecretStr(API_KEY),
            environment="measurement",
            data_dir=temporary,
            database_url=f"sqlite:///{temporary}/measurement.db",
        )
        with TestClient(create_app(settings)) as client:
            upload = client.post(
                "/api/v1/documents",
                headers={"X-API-Key": API_KEY},
                files={
                    "file": (
                        "retrieval-measurement.md",
                        sample_document(),
                        "text/markdown",
                    )
                },
            )
            upload.raise_for_status()
            document_id = upload.json()["document_id"]
            search = client.get(
                f"/api/v1/documents/{document_id}/search",
                headers={"X-API-Key": API_KEY},
                params={
                    "q": "unique content fingerprint",
                    "top_k": 3,
                    "max_chars": 2_000,
                    "max_tokens": 240,
                },
            )
            search.raise_for_status()
            payload = search.json()
            metrics = payload["metrics"]
            full_tokens = metrics["full_document_estimated_tokens"]
            returned_tokens = metrics["returned_estimated_tokens"]
            reduction = round((1 - returned_tokens / full_tokens) * 100, 2)
            print(
                json.dumps(
                    {
                        **metrics,
                        "measured_token_reduction_percent": reduction,
                        "query": payload["query"],
                        "configured_max_tokens": payload["max_tokens"],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )


if __name__ == "__main__":
    main()
