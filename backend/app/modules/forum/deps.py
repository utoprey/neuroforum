"""FastAPI dependencies for the ``forum`` module."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.modules.forum.repository import ForumRepository
from app.modules.forum.service import ForumService


def get_forum_repository(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> ForumRepository:
    return ForumRepository(db)


def get_forum_service(
    db: Annotated[AsyncSession, Depends(get_session)],
    repo: Annotated[ForumRepository, Depends(get_forum_repository)],
) -> ForumService:
    return ForumService(repo, db)


__all__ = ["get_forum_repository", "get_forum_service"]
