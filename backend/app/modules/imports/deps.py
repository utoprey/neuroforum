"""FastAPI dependencies for the ``imports`` module."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.modules.articles.deps import get_article_service
from app.modules.articles.service import ArticleService
from app.modules.imports.repository import ExternalSourceRepository
from app.modules.imports.service import ImportService


def get_external_source_repository(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> ExternalSourceRepository:
    return ExternalSourceRepository(db)


def get_import_service(
    db: Annotated[AsyncSession, Depends(get_session)],
    repo: Annotated[
        ExternalSourceRepository, Depends(get_external_source_repository)
    ],
    articles: Annotated[ArticleService, Depends(get_article_service)],
) -> ImportService:
    return ImportService(repo, articles, db)


__all__ = ["get_external_source_repository", "get_import_service"]
