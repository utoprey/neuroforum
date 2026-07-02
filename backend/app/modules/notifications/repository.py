"""Data access for ``notifications``."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from uuid import UUID

from sqlalchemy import desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.models import Notification


class NotificationRepository:
    """Thin DAL over ``notifications``."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create(
        self, user_id: UUID, type_: str, payload: dict[str, Any]
    ) -> Notification:
        notif = Notification(user_id=user_id, type=type_, payload=payload)
        self._db.add(notif)
        await self._db.flush()
        return notif

    async def list_for_user(
        self,
        user_id: UUID,
        *,
        limit: int,
        offset: int,
        unread_only: bool = False,
    ) -> list[Notification]:
        stmt = (
            select(Notification)
            .where(Notification.user_id == user_id)
            .order_by(desc(Notification.created_at))
            .limit(limit)
            .offset(offset)
        )
        if unread_only:
            stmt = stmt.where(Notification.is_read.is_(False))
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def mark_read_bulk(
        self, user_id: UUID, ids: Iterable[UUID]
    ) -> int:
        """Flip ``is_read`` to True for the caller's rows; returns affected count."""
        ids_list = list(ids)
        if not ids_list:
            return 0
        stmt = (
            update(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.id.in_(ids_list),
                Notification.is_read.is_(False),
            )
            .values(is_read=True)
        )
        result = await self._db.execute(stmt)
        rc = getattr(result, "rowcount", 0)
        return int(rc) if rc is not None else 0

    async def unread_count(self, user_id: UUID) -> int:
        stmt = select(func.count()).where(
            Notification.user_id == user_id,
            Notification.is_read.is_(False),
        )
        return int((await self._db.execute(stmt)).scalar_one())


__all__ = ["NotificationRepository"]
