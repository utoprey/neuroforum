"""FastAPI dependencies for the ``auth`` module."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.modules.auth.repository import AuthRepository
from app.modules.auth.service import AuthService
from app.modules.users.deps import get_user_repository
from app.modules.users.repository import UserRepository


def get_auth_repository(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> AuthRepository:
    return AuthRepository(db)


def get_auth_service(
    db: Annotated[AsyncSession, Depends(get_session)],
    repo: Annotated[AuthRepository, Depends(get_auth_repository)],
    users: Annotated[UserRepository, Depends(get_user_repository)],
) -> AuthService:
    return AuthService(repo, users, settings, db)


__all__ = ["get_auth_repository", "get_auth_service"]
