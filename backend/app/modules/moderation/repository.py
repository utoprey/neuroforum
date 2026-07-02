"""Data access for ``audit_log``."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.moderation.models import AuditLog


class ModerationRepository:
    """Thin DAL over ``audit_log``."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def log_action(
        self,
        actor_id: UUID,
        action: str,
        target_type: str,
        target_id: UUID,
        payload: dict[str, Any],
        ip: str | None,
        user_agent: str | None,
    ) -> AuditLog:
        row = AuditLog(
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            payload=payload,
            ip=ip,
            user_agent=user_agent,
        )
        self._db.add(row)
        await self._db.flush()
        return row

    async def list_audit(
        self,
        *,
        actor_id: UUID | None = None,
        target_type: str | None = None,
        target_id: UUID | None = None,
        action: str | None = None,
        since: datetime | None = None,
        limit: int,
        offset: int,
    ) -> list[AuditLog]:
        stmt = (
            select(AuditLog)
            .order_by(desc(AuditLog.created_at))
            .limit(limit)
            .offset(offset)
        )
        if actor_id is not None:
            stmt = stmt.where(AuditLog.actor_id == actor_id)
        if target_type is not None:
            stmt = stmt.where(AuditLog.target_type == target_type)
        if target_id is not None:
            stmt = stmt.where(AuditLog.target_id == target_id)
        if action is not None:
            stmt = stmt.where(AuditLog.action == action)
        if since is not None:
            stmt = stmt.where(AuditLog.created_at >= since)
        result = await self._db.execute(stmt)
        return list(result.scalars().all())


__all__ = ["ModerationRepository"]
