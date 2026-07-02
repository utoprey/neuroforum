"""``SearchEngine`` Protocol — two concrete backends behind a tight interface.

DI in ``search/deps.py`` picks the concrete class based on ``SEARCH_BACKEND``
config. Routes only ever depend on the Protocol so backends can be swapped
without touching the HTTP layer.
"""

from __future__ import annotations

from typing import Protocol

from app.modules.search.schemas import ArticleSearchHit, MessageSearchHit
from app.modules.users.schemas import UserPublic


class SearchEngine(Protocol):
    """Async search Protocol implemented by both Postgres and OpenSearch backends."""

    async def search_articles(
        self, q: str, limit: int
    ) -> list[ArticleSearchHit]: ...

    async def search_messages(
        self, q: str, limit: int
    ) -> list[MessageSearchHit]: ...

    async def search_users(
        self, q: str, limit: int
    ) -> list[UserPublic]: ...


__all__ = ["SearchEngine"]
