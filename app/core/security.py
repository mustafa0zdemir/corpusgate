from __future__ import annotations

import hashlib
import hmac
from collections import defaultdict, deque
from threading import Lock
from time import monotonic

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import Settings


class _RequestBodyTooLarge(Exception):
    pass


class RequestBodyLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        content_length = headers.get(b"content-length", b"")
        try:
            declared_size = int(content_length) if content_length else 0
        except ValueError:
            declared_size = 0
        if declared_size > self.max_bytes:
            await self._reject(scope, receive, send)
            return

        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _RequestBodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _RequestBodyTooLarge:
            await self._reject(scope, receive, send)

    @staticmethod
    async def _reject(scope: Scope, receive: Receive, send: Send) -> None:
        await _error_response(
            scope,
            receive,
            send,
            status_code=413,
            code="request_too_large",
            message="The request body exceeds the configured limit.",
            headers={},
        )


class SlidingWindowRateLimiter:
    def __init__(self, requests: int, window_seconds: int):
        self.requests = requests
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, identity: str) -> tuple[bool, int]:
        now = monotonic()
        threshold = now - self.window_seconds
        with self._lock:
            events = self._events[identity]
            while events and events[0] <= threshold:
                events.popleft()
            if len(events) >= self.requests:
                retry_after = max(int(events[0] + self.window_seconds - now) + 1, 1)
                return False, retry_after
            events.append(now)
            return True, 0


class BearerTokenProvider:
    """Read active tokens without exposing them and allow file-based rotation."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.settings.active_mcp_tokens()

    def matches(self, supplied: str) -> bool:
        matched = False
        for expected in self.settings.active_mcp_tokens():
            matched |= hmac.compare_digest(supplied, expected)
        return matched


class AuthenticationMiddleware:
    """Use Bearer auth for MCP and X-API-Key for REST without logging credentials."""

    PUBLIC_PATHS = frozenset({"/health", "/ready", "/docs", "/openapi.json", "/redoc"})

    def __init__(self, app: ASGIApp, settings: Settings):
        self.app = app
        self.expected_api_key = settings.api_key.get_secret_value()
        self.token_provider = BearerTokenProvider(settings)
        self.rate_limiter = SlidingWindowRateLimiter(
            settings.rate_limit_requests,
            settings.rate_limit_window_seconds,
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] not in {"http", "websocket"}
            or scope.get("path") in self.PUBLIC_PATHS
            or scope.get("method") == "OPTIONS"
        ):
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        path = scope.get("path", "")
        if path == "/mcp" or path.startswith("/mcp/"):
            supplied = _bearer_token(headers.get(b"authorization", b""))
            valid = bool(supplied) and self.token_provider.matches(supplied)
            scheme = "Bearer"
        else:
            supplied = headers.get(b"x-api-key", b"").decode("utf-8", errors="ignore")
            valid = bool(supplied) and hmac.compare_digest(supplied, self.expected_api_key)
            scheme = "ApiKey"

        identity = _credential_identity(supplied) if valid else _network_identity(scope)
        allowed, retry_after = self.rate_limiter.check(identity)
        if not allowed:
            await _error_response(
                scope,
                receive,
                send,
                status_code=429,
                code="rate_limited",
                message="Too many requests.",
                headers={"Retry-After": str(retry_after)},
            )
            return

        if not valid:
            await _error_response(
                scope,
                receive,
                send,
                status_code=401,
                code="unauthorized",
                message="Authentication required.",
                headers={"WWW-Authenticate": scheme},
            )
            return

        scope.setdefault("state", {})["authenticated"] = True
        await self.app(scope, receive, send)


def _bearer_token(header: bytes) -> str:
    value = header.decode("utf-8", errors="ignore").strip()
    scheme, separator, token = value.partition(" ")
    if (
        not separator
        or scheme.casefold() != "bearer"
        or not token
        or any(character.isspace() for character in token)
    ):
        return ""
    return token


def _credential_identity(credential: str) -> str:
    return "credential:" + hashlib.sha256(credential.encode()).hexdigest()


def _network_identity(scope: Scope) -> str:
    client = scope.get("client")
    host = client[0] if client else "unknown"
    return f"network:{host}"


async def _error_response(
    scope: Scope,
    receive: Receive,
    send: Send,
    *,
    status_code: int,
    code: str,
    message: str,
    headers: dict[str, str],
) -> None:
    response = JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
        headers=headers,
    )
    await response(scope, receive, send)
