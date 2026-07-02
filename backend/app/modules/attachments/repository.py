"""Data access for ``attachments`` / ``attachment_usages``."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.attachments.models import Attachment, AttachmentUsage


class AttachmentRepository:
    """Thin DAL: no business logic."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def add(self, attachment: Attachment) -> Attachment:
        self._db.add(attachment)
        await self._db.flush()
        return attachment

    async def get(self, attachment_id: UUID) -> Attachment | None:
        stmt = select(Attachment).where(Attachment.id == attachment_id)
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def delete(self, attachment: Attachment) -> None:
        await self._db.delete(attachment)
        await self._db.flush()

    async def add_usage(self, usage: AttachmentUsage) -> AttachmentUsage:
        self._db.add(usage)
        await self._db.flush()
        return usage

    async def find_usage(
        self,
        attachment_id: UUID,
        entity_type: str,
        entity_id: UUID,
    ) -> AttachmentUsage | None:
        stmt = select(AttachmentUsage).where(
            AttachmentUsage.attachment_id == attachment_id,
            AttachmentUsage.entity_type == entity_type,
            AttachmentUsage.entity_id == entity_id,
        )
        return (await self._db.execute(stmt)).scalar_one_or_none()


__all__ = ["AttachmentRepository"]
