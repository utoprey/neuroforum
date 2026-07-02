"""Data access for ``external_sources``."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.imports.models import ExternalSource, ExternalSourceRecord


class ExternalSourceRepository:
    """Thin DAL for ``external_sources``."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def add(self, record: ExternalSourceRecord) -> ExternalSourceRecord:
        self._db.add(record)
        await self._db.flush()
        return record

    async def get_by_source_and_id(
        self, source: ExternalSource, external_id: str
    ) -> ExternalSourceRecord | None:
        stmt = select(ExternalSourceRecord).where(
            ExternalSourceRecord.source == source,
            ExternalSourceRecord.external_id == external_id,
        )
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def get_for_article(
        self, article_id: UUID
    ) -> ExternalSourceRecord | None:
        stmt = select(ExternalSourceRecord).where(
            ExternalSourceRecord.article_id == article_id
        )
        return (await self._db.execute(stmt)).scalar_one_or_none()


__all__ = ["ExternalSourceRepository"]
