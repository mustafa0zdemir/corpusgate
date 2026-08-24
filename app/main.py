from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from mcp.server.transport_security import TransportSecuritySettings

from app.api.routes import router as documents_router
from app.chunking.markdown import MarkdownChunkStrategy
from app.core.config import Settings, get_settings
from app.core.database import Database
from app.core.errors import AppError
from app.core.security import ApiKeyMiddleware
from app.mcp.server import create_mcp_server
from app.parsers.markitdown import MarkItDownDocumentParser
from app.storage.local import LocalFileStorage

logger = logging.getLogger("private_document_gateway")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    database = Database(settings)
    storage = LocalFileStorage(settings.data_dir, settings.max_file_size_mb)
    parser = MarkItDownDocumentParser()
    chunker = MarkdownChunkStrategy(settings.chunk_size_chars, settings.chunk_overlap_chars)
    mcp_server = create_mcp_server(settings, database.session_factory)
    transport_security = TransportSecuritySettings(
        allowed_hosts=settings.allowed_host_list,
        allowed_origins=settings.cors_origin_list or ["http://localhost:*", "http://127.0.0.1:*"],
    )
    mcp_app = mcp_server.streamable_http_app(
        json_response=True,
        stateless_http=True,
        transport_security=transport_security,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        database.create_schema()
        async with mcp_server.session_manager.run():
            yield
        database.dispose()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Secure, self-hosted document conversion and retrieval gateway.",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.database = database
    app.state.storage = storage
    app.state.parser = parser
    app.state.chunker = chunker
    app.state.mcp_server = mcp_server

    app.add_middleware(ApiKeyMiddleware, settings=settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=[
            "Accept",
            "Content-Type",
            "Last-Event-ID",
            "Mcp-Protocol-Version",
            "Mcp-Session-Id",
            "X-API-Key",
        ],
        expose_headers=["Mcp-Session-Id"],
    )

    @app.exception_handler(AppError)
    async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request, _exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "The request parameters are invalid.",
                }
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(_request: Request, _exc: Exception) -> JSONResponse:
        logger.exception("Unhandled request error")
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "An internal server error occurred.",
                }
            },
        )

    @app.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok", "service": settings.app_name, "version": settings.app_version}

    app.include_router(documents_router)
    # Keep this last: Mount("/") is the fallback that preserves MCP's canonical /mcp path.
    app.mount("/", mcp_app)
    return app


app = create_app()


def run() -> None:
    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.host, port=settings.port)
