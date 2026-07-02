"""FastAPI dependencies for the ``dm`` module."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.modules.dm.repository import DMRepository
from app.modules.dm.service import DMService
from app.modules.users.repository import UserRepository


def get_dm_repository(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> DMRepository:
    return DMRepository(db)


def get_dm_service(
    db: Annotated[AsyncSession, Depends(get_session)],
    repo: Annotated[DMRepository, Depends(get_dm_repository)],
) -> DMService:
    return DMService(repo, UserRepository(db), db)


__all__ = ["get_dm_repository", "get_dm_service"]
