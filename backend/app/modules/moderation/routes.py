"""HTTP routes for the ``moderation`` module."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from app.modules.moderation.deps import get_moderation_service
from app.modules.moderation.exceptions import (
    ArticleNotFound,
    InsufficientRole,
    UserNotFound,
)
from app.modules.moderation.schemas import (
    AssignRoleRequest,
    AuditLogRead,
    HideArticleRequest,
)
from app.modules.moderation.service import ModerationService
from app.modules.users.deps import require_roles
from app.modules.users.models import Role, User
from app.modules.users.schemas import UserRead

router = APIRouter(prefix="/moderation", tags=["moderation"])


# ---------------------------------------------------------------------------
# Article hide / unhide (mod or admin)
# ---------------------------------------------------------------------------


@router.post(
    "/articles/{article_id}/hide",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Hide an article (moderator or admin)",
)
async def hide_article(
    article_id: UUID,
    payload: HideArticleRequest,
    request: Request,
    actor: Annotated[
        User, Depends(require_roles(Role.MODERATOR, Role.ADMIN))
    ],
    svc: Annotated[ModerationService, Depends(get_moderation_service)],
) -> Response:
    try:
        await svc.hide_article(actor, article_id, payload.reason, request)
    except ArticleNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Article not found"
        ) from exc
    except InsufficientRole as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/articles/{article_id}/unhide",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Unhide a previously hidden article (moderator or admin)",
)
async def unhide_article(
    article_id: UUID,
    payload: HideArticleRequest,
    request: Request,
    actor: Annotated[
        User, Depends(require_roles(Role.MODERATOR, Role.ADMIN))
    ],
    svc: Annotated[ModerationService, Depends(get_moderation_service)],
) -> Response:
    try:
        await svc.unhide_article(actor, article_id, payload.reason, request)
    except ArticleNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Article not found"
        ) from exc
    except InsufficientRole as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Role assignment (admin only)
# ---------------------------------------------------------------------------


@router.post(
    "/users/{user_id}/role",
    response_model=UserRead,
    summary="Reassign a user's role (admin only)",
)
async def assign_role(
    user_id: UUID,
    payload: AssignRoleRequest,
    request: Request,
    actor: Annotated[User, Depends(require_roles(Role.ADMIN))],
    svc: Annotated[ModerationService, Depends(get_moderation_service)],
) -> User:
    try:
        return await svc.assign_role(actor, user_id, payload.role, request)
    except UserNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        ) from exc
    except InsufficientRole as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc


# ---------------------------------------------------------------------------
# Audit log read (admin only)
# ---------------------------------------------------------------------------


@router.get(
    "/audit",
    response_model=list[AuditLogRead],
    summary="List audit log entries (admin only)",
)
async def list_audit(
    actor: Annotated[User, Depends(require_roles(Role.ADMIN))],
    svc: Annotated[ModerationService, Depends(get_moderation_service)],
    actor_id: Annotated[UUID | None, Query()] = None,
    target_type: Annotated[str | None, Query(max_length=50)] = None,
    target_id: Annotated[UUID | None, Query()] = None,
    action: Annotated[str | None, Query(max_length=50)] = None,
    since: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AuditLogRead]:
    try:
        rows = await svc.list_audit(
            actor,
            actor_id=actor_id,
            target_type=target_type,
            target_id=target_id,
            action=action,
            since=since,
            limit=limit,
            offset=offset,
        )
    except InsufficientRole as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    return [
        AuditLogRead(
            id=row.id,
            actor_id=row.actor_id,
            action=row.action,
            target_type=row.target_type,
            target_id=row.target_id,
            payload=dict(row.payload or {}),
            ip=str(row.ip) if row.ip else None,
            user_agent=row.user_agent,
            created_at=row.created_at,
        )
        for row in rows
    ]


__all__ = ["router"]
