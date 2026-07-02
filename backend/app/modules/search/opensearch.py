"""OpenSearch-backed implementation stub — fill in when scale demands it.

Selected via ``SEARCH_BACKEND=opensearch`` env. Every method raises
``NotImplementedError`` so misconfiguration fails fast at request time
rather than degrading silently.
"""

from __future__ import annotations

from app.modules.search.schemas import ArticleSearchHit, MessageSearchHit
from app.modules.users.schemas import UserPublic

_STUB_MSG = "OpenSearch backend stub — fill in when scaling out"


class OpenSearchSearchEngine:
    """Not-yet-implemented OpenSearch backend."""

    async def search_articles(
        self, q: str, limit: int
    ) -> list[ArticleSearchHit]:
        _ = (q, limit)
        raise NotImplementedError(_STUB_MSG)

    async def search_messages(
        self, q: str, limit: int
    ) -> list[MessageSearchHit]:
        _ = (q, limit)
        raise NotImplementedError(_STUB_MSG)

    async def search_users(
        self, q: str, limit: int
    ) -> list[UserPublic]:
        _ = (q, limit)
        raise NotImplementedError(_STUB_MSG)


__all__ = ["OpenSearchSearchEngine"]
