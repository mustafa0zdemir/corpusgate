from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.chunking.base import ChunkStrategy
from app.core.config import Settings
from app.core.resources import OperationCapacity
from app.parsers.base import DocumentParser
from app.repositories.base import DocumentRepository
from app.repositories.sqlite import SQLiteDocumentRepository
from app.repositories.sqlite_fts import SQLiteFtsSearchIndex
from app.services.documents import DocumentService
from app.services.search import FullTextSearchService
from app.storage.base import FileStorage


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.database.session_factory() as session:
        yield session


SessionDependency = Annotated[Session, Depends(get_session)]


def get_repository(session: SessionDependency) -> DocumentRepository:
    return SQLiteDocumentRepository(session)


RepositoryDependency = Annotated[DocumentRepository, Depends(get_repository)]


def get_document_service(request: Request, repository: RepositoryDependency) -> DocumentService:
    settings: Settings = request.app.state.settings
    parser: DocumentParser = request.app.state.parser
    storage: FileStorage = request.app.state.storage
    chunker: ChunkStrategy = request.app.state.chunker
    conversion_capacity: OperationCapacity = request.app.state.conversion_capacity
    return DocumentService(
        settings=settings,
        repository=repository,
        parser=parser,
        storage=storage,
        chunker=chunker,
        conversion_capacity=conversion_capacity,
    )


DocumentServiceDependency = Annotated[DocumentService, Depends(get_document_service)]


def get_search_service(
    request: Request,
    session: SessionDependency,
    repository: RepositoryDependency,
) -> FullTextSearchService:
    return FullTextSearchService(
        request.app.state.settings,
        repository,
        SQLiteFtsSearchIndex(
            session,
            timeout_seconds=request.app.state.settings.search_timeout_seconds,
        ),
    )


SearchServiceDependency = Annotated[FullTextSearchService, Depends(get_search_service)]
