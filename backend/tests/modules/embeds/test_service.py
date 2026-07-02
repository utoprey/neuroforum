"""Service-layer tests for the ``embeds`` cache."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.embeds.exceptions import UnsupportedProvider
from app.modules.embeds.repository import EmbedRepository
from app.modules.embeds.service import EmbedService


@pytest.fixture
def embeds_svc(db_session: AsyncSession) -> EmbedService:
    return EmbedService(EmbedRepository(db_session), db_session)


async def test_cache_miss_then_hit(embeds_svc: EmbedService) -> None:
    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    first = await embeds_svc.fetch_embed(url)
    assert first.cached is False
    assert first.provider == "youtube"
    assert first.data.iframe_src == "https://www.youtube.com/embed/dQw4w9WgXcQ"

    second = await embeds_svc.fetch_embed(url)
    assert second.cached is True
    assert second.provider == "youtube"
    assert second.data.iframe_src == first.data.iframe_src


async def test_unsupported_provider(embeds_svc: EmbedService) -> None:
    with pytest.raises(UnsupportedProvider):
        await embeds_svc.fetch_embed("https://example.com/foo")


async def test_invalidate_clears_cache(embeds_svc: EmbedService) -> None:
    url = "https://gist.github.com/octocat/abc123def456"
    first = await embeds_svc.fetch_embed(url)
    assert first.cached is False
    second = await embeds_svc.fetch_embed(url)
    assert second.cached is True

    deleted = await embeds_svc.invalidate(url)
    assert deleted == 1

    third = await embeds_svc.fetch_embed(url)
    assert third.cached is False
