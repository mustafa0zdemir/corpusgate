from __future__ import annotations

import hmac

from fastapi import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import Settings


class ApiKeyMiddleware:
    """Authenticate every private HTTP and MCP route without logging the secret."""

    PUBLIC_PATHS = frozenset({"/health", "/docs", "/openapi.json", "/redoc"})

    def __init__(self, app: ASGIApp, settings: Settings):
        self.app = app
        self.expected_key = settings.api_key.get_secret_value()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] not in {"http", "websocket"}
            or scope.get("path") in self.PUBLIC_PATHS
            or scope.get("method") == "OPTIONS"
        ):
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        supplied = headers.get(b"x-api-key", b"").decode("utf-8", errors="ignore")
        if not supplied or not hmac.compare_digest(supplied, self.expected_key):
            response = JSONResponse(
                status_code=401,
                content={"error": {"code": "unauthorized", "message": "Invalid API key."}},
                headers={"WWW-Authenticate": "ApiKey"},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


def request_api_key(request: Request) -> str | None:
    """Expose only whether authentication happened; never return or log the configured key."""
    return request.headers.get("X-API-Key")
