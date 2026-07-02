"""HTTP routes for the ``notifications`` module."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.modules.notifications.deps import get_notification_service
from app.modules.notifications.schemas import (
    MarkReadRequest,
    NotificationRead,
    UnreadCount,
)
from app.modules.notifications.service import NotificationService
from app.modules.users.deps import get_current_user
from app.modules.users.models import User

router = APIRouter(tags=["notifications"])


@router.get(
    "/me/notifications",
    response_model=list[NotificationRead],
    summary="List the current user's notifications, newest first",
)
async def list_my_notifications(
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[NotificationService, Depends(get_notification_service)],
    unread: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[NotificationRead]:
    rows = await svc.list_for_user(
        actor, unread_only=unread, limit=limit, offset=offset
    )
    return [
        NotificationRead(
            id=row.id,
            type=row.type,
            payload=dict(row.payload or {}),
            is_read=row.is_read,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.post(
    "/me/notifications/mark-read",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Mark a batch of notifications as read",
)
async def mark_notifications_read(
    payload: MarkReadRequest,
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[NotificationService, Depends(get_notification_service)],
) -> Response:
    await svc.mark_read(actor, payload.ids)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/me/notifications/unread-count",
    response_model=UnreadCount,
    summary="Return the number of unread notifications for the current user",
)
async def get_unread_count(
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[NotificationService, Depends(get_notification_service)],
) -> UnreadCount:
    count = await svc.unread_count(actor)
    return UnreadCount(count=count)


__all__ = ["router"]
