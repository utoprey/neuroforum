"""FastAPI dependencies for the ``moderation`` module."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.modules.moderation.repository import ModerationRepository
from app.modules.moderation.service import ModerationService


def get_moderation_repository(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> ModerationRepository:
    return ModerationRepository(db)


def get_moderation_service(
    db: Annotated[AsyncSession, Depends(get_session)],
    repo: Annotated[
        ModerationRepository, Depends(get_moderation_repository)
    ],
) -> ModerationService:
    return ModerationService(repo, db)


__all__ = ["get_moderation_repository", "get_moderation_service"]
