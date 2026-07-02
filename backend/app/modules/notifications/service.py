"""Notifications business logic: create + list + mark-read + unread count."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.models import Notification
from app.modules.notifications.repository import NotificationRepository
from app.modules.users.models import User


class NotificationService:
    """Service-layer wrapper around the notifications repository."""

    def __init__(self, repo: NotificationRepository, db: AsyncSession) -> None:
        self._repo = repo
        self._db = db

    async def create_notification(
        self,
        user_id: UUID,
        type: str,
        payload: dict[str, Any] | None = None,
    ) -> Notification:
        """Insert a single notification row. Payload defaults to ``{}``."""
        return await self._repo.create(user_id, type, payload or {})

    async def mark_read(
        self, user: User, ids: Iterable[UUID]
    ) -> int:
        return await self._repo.mark_read_bulk(user.id, ids)

    async def list_for_user(
        self,
        user: User,
        *,
        unread_only: bool = False,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Notification]:
        return await self._repo.list_for_user(
            user.id,
            limit=max(1, min(limit, 100)),
            offset=max(0, offset),
            unread_only=unread_only,
        )

    async def unread_count(self, user: User) -> int:
        return await self._repo.unread_count(user.id)


__all__ = ["NotificationService"]
