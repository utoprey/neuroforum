"""FastAPI dependencies for ``rbac``."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.modules.rbac.repository import RbacRepository
from app.modules.rbac.service import RbacService
from app.modules.users.deps import get_user_repository
from app.modules.users.repository import UserRepository


def get_rbac_repository(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> RbacRepository:
    return RbacRepository(db)


def get_rbac_service(
    db: Annotated[AsyncSession, Depends(get_session)],
    repo: Annotated[RbacRepository, Depends(get_rbac_repository)],
    users: Annotated[UserRepository, Depends(get_user_repository)],
) -> RbacService:
    return RbacService(repo, users, db)


__all__ = ["get_rbac_repository", "get_rbac_service"]
