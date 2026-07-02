"""Business logic for the ``embeds`` module."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.embeds.exceptions import UnsupportedProvider
from app.modules.embeds.models import Embed
from app.modules.embeds.providers import find_provider
from app.modules.embeds.repository import EmbedRepository
from app.modules.embeds.schemas import EmbedData, EmbedResponse

# Cached embed entries are considered fresh for 7 days.
_TTL = timedelta(days=7)


class EmbedService:
    """Resolves embed URLs through a cache + provider whitelist."""

    def __init__(self, repo: EmbedRepository, db: AsyncSession) -> None:
        self._repo = repo
        self._db = db

    async def fetch_embed(self, url: str) -> EmbedResponse:
        """Return a ``EmbedResponse`` for ``url``, hitting the cache when fresh."""
        url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()

        cached = await self._repo.get(url_hash)
        now = datetime.now(UTC)
        if cached is not None and cached.ttl_expires_at > now:
            return EmbedResponse(
                provider=cached.provider,
                url=cached.url,
                data=EmbedData.model_validate(cached.data),
                fetched_at=cached.fetched_at,
                cached=True,
            )

        provider = find_provider(url)
        if provider is None:
            raise UnsupportedProvider(url)

        data = await provider.fetch(url)
        embed = Embed(
            url_hash=url_hash,
            url=url,
            provider=provider.name,
            # ``mode='json'`` so HttpUrl / nested types serialise cleanly.
            data=data.model_dump(mode="json"),
            fetched_at=now,
            ttl_expires_at=now + _TTL,
        )
        await self._repo.upsert(embed)

        return EmbedResponse(
            provider=provider.name,
            url=url,
            data=data,
            fetched_at=now,
            cached=False,
        )

    async def invalidate(self, url: str) -> int:
        """Drop the cache row for ``url``. Returns number of rows deleted."""
        url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return await self._repo.delete_by_hash(url_hash)


__all__ = ["EmbedService"]
