"""Data access for ``user_bans``."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.rbac.models import BanScope, UserBan


class RbacRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get(self, ban_id: UUID) -> UserBan | None:
        stmt = select(UserBan).where(UserBan.id == ban_id)
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def list_active_bans(
        self,
        user_id: UUID,
        *,
        scope: BanScope | None = None,
        section_id: UUID | None = None,
        topic_id: UUID | None = None,
    ) -> list[UserBan]:
        """Active = ``lifted_at IS NULL`` AND not yet expired."""
        now = datetime.now(UTC)
        conds = [
            UserBan.user_id == user_id,
            UserBan.lifted_at.is_(None),
            or_(UserBan.expires_at.is_(None), UserBan.expires_at > now),
        ]
        if scope is not None:
            conds.append(UserBan.scope == scope)
        if section_id is not None:
            conds.append(UserBan.section_id == section_id)
        if topic_id is not None:
            conds.append(UserBan.topic_id == topic_id)
        stmt = select(UserBan).where(and_(*conds))
        return list((await self._db.execute(stmt)).scalars().all())

    async def create_ban(self, ban: UserBan) -> UserBan:
        self._db.add(ban)
        await self._db.flush()
        return ban

    async def lift_ban(
        self, ban: UserBan, *, lifted_by: UUID, reason: str
    ) -> UserBan:
        ban.lifted_at = datetime.now(UTC)
        ban.lifted_by = lifted_by
        ban.lift_reason = reason
        await self._db.flush()
        return ban


__all__ = ["RbacRepository"]
