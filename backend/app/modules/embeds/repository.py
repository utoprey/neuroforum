"""Data access for the ``embeds`` cache."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.embeds.models import Embed


class EmbedRepository:
    """Thin DAL with an upsert helper for the cache."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get(self, url_hash: str) -> Embed | None:
        stmt = select(Embed).where(Embed.url_hash == url_hash)
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def upsert(self, embed: Embed) -> Embed:
        """ON CONFLICT (url_hash) DO UPDATE — refreshes ``data`` + timestamps."""
        stmt = (
            pg_insert(Embed)
            .values(
                url_hash=embed.url_hash,
                url=embed.url,
                provider=embed.provider,
                data=embed.data,
                fetched_at=embed.fetched_at,
                ttl_expires_at=embed.ttl_expires_at,
            )
            .on_conflict_do_update(
                index_elements=["url_hash"],
                set_={
                    "url": embed.url,
                    "provider": embed.provider,
                    "data": embed.data,
                    "fetched_at": embed.fetched_at,
                    "ttl_expires_at": embed.ttl_expires_at,
                },
            )
            .returning(Embed)
        )
        result = await self._db.execute(stmt)
        await self._db.flush()
        return result.scalar_one()

    async def delete_by_hash(self, url_hash: str) -> int:
        stmt = delete(Embed).where(Embed.url_hash == url_hash)
        result = await self._db.execute(stmt)
        await self._db.flush()
        # CursorResult exposes ``rowcount`` but the statically-typed
        # Result[Any] does not; cast through the runtime attribute.
        return int(getattr(result, "rowcount", 0) or 0)


__all__ = ["EmbedRepository"]
