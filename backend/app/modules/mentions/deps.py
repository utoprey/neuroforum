"""FastAPI dependencies for the ``mentions`` module."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.modules.mentions.repository import MentionRepository
from app.modules.mentions.service import MentionService


def get_mention_repository(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> MentionRepository:
    return MentionRepository(db)


def get_mention_service(
    db: Annotated[AsyncSession, Depends(get_session)],
    repo: Annotated[MentionRepository, Depends(get_mention_repository)],
) -> MentionService:
    return MentionService(repo, db)


__all__ = ["get_mention_repository", "get_mention_service"]
