"""FastAPI dependencies for the ``saved`` module."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.modules.saved.repository import SavedRepository
from app.modules.saved.service import SavedService


def get_saved_repository(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> SavedRepository:
    return SavedRepository(db)


def get_saved_service(
    db: Annotated[AsyncSession, Depends(get_session)],
    repo: Annotated[SavedRepository, Depends(get_saved_repository)],
) -> SavedService:
    return SavedService(repo, db)


__all__ = ["get_saved_repository", "get_saved_service"]
