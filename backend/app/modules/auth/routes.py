"""HTTP routes for the ``auth`` module."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.ratelimit import limiter
from app.modules.auth.deps import get_auth_service
from app.modules.auth.exceptions import (
    InvalidCredentials,
    RefreshTokenNotFound,
    TokenExpired,
    TokenRevoked,
)
from app.modules.auth.schemas import LoginRequest, RefreshRequest, TokenPair
from app.modules.auth.service import AuthService, RequestMeta
from app.modules.users.deps import get_current_user
from app.modules.users.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


def _meta_from(request: Request) -> RequestMeta:
    return RequestMeta(
        user_agent=request.headers.get("user-agent"),
        ip=request.client.host if request.client else None,
    )


@router.post("/login", response_model=TokenPair, summary="Log in (JSON body)")
@limiter.limit("10/minute")  # brute-force guard
async def login(
    payload: LoginRequest,
    request: Request,
    svc: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenPair:
    try:
        user = await svc.authenticate(
            payload.username_or_email, payload.password.get_secret_value()
        )
    except InvalidCredentials as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    return await svc.issue_token_pair(user, _meta_from(request))


@router.post(
    "/refresh", response_model=TokenPair, summary="Rotate a refresh token"
)
async def refresh(
    payload: RefreshRequest,
    request: Request,
    svc: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenPair:
    try:
        return await svc.rotate_refresh(payload.refresh_token, _meta_from(request))
    except (RefreshTokenNotFound, TokenExpired, TokenRevoked) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except InvalidCredentials as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer valid",
        ) from exc


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke the supplied refresh token (idempotent)",
)
async def logout(
    payload: RefreshRequest,
    _current_user: Annotated[User, Depends(get_current_user)],
    svc: Annotated[AuthService, Depends(get_auth_service)],
) -> None:
    await svc.revoke_refresh(payload.refresh_token)
    return None


__all__ = ["router"]
