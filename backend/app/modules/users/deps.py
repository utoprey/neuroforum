"""FastAPI dependencies: service wiring, current-user auth, role checks."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import InvalidTokenError, decode_token
from app.modules.users.exceptions import UserNotFound
from app.modules.users.models import Role, User
from app.modules.users.repository import UserRepository
from app.modules.users.service import UserService

# auto_error=False so endpoints can do optional auth ("show me extra fields
# if logged in, otherwise the public view") without raising.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def get_user_repository(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> UserRepository:
    return UserRepository(db)


def get_user_service(
    db: Annotated[AsyncSession, Depends(get_session)],
    repo: Annotated[UserRepository, Depends(get_user_repository)],
) -> UserService:
    return UserService(repo, db)


_CREDENTIALS_EXC = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    token: Annotated[str | None, Depends(oauth2_scheme)],
    svc: Annotated[UserService, Depends(get_user_service)],
) -> User:
    """Decode JWT, fetch user, ensure active. Raises 401 otherwise."""
    if not token:
        raise _CREDENTIALS_EXC
    try:
        claims = decode_token(token)
    except InvalidTokenError as exc:
        raise _CREDENTIALS_EXC from exc
    if claims.get("type") != "access":
        raise _CREDENTIALS_EXC
    sub = claims.get("sub")
    if not sub:
        raise _CREDENTIALS_EXC
    try:
        user_id = UUID(str(sub))
    except (ValueError, TypeError) as exc:
        raise _CREDENTIALS_EXC from exc
    try:
        user = await svc.get_by_id(user_id)
    except UserNotFound as exc:
        raise _CREDENTIALS_EXC from exc
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")
    return user


def require_roles(
    *allowed: Role,
) -> Callable[[User], Coroutine[Any, Any, User]]:
    """Dependency factory: enforce that ``current_user.role`` is in ``allowed``."""
    allowed_set = set(allowed)

    async def _checker(
        current_user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        if current_user.role not in allowed_set:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient role",
            )
        return current_user

    return _checker


__all__ = [
    "get_current_user",
    "get_user_repository",
    "get_user_service",
    "oauth2_scheme",
    "require_roles",
]
