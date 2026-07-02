"""Pydantic v2 schemas for the ``search`` module."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.articles.schemas import ArticlePublic
from app.modules.users.schemas import UserPublic


class ArticleSearchHit(BaseModel):
    """Single ranked article hit + ts_headline snippet."""

    model_config = ConfigDict(from_attributes=True)

    article: ArticlePublic
    rank: float
    snippet: str = ""


class MessageSearchHit(BaseModel):
    """Single ranked message hit. We don't denormalise the whole message."""

    model_config = ConfigDict(from_attributes=True)

    message_id: UUID
    article_id: UUID
    snippet: str = ""
    rank: float


class UnifiedSearchResult(BaseModel):
    """Wire shape for ``GET /search?type=all``."""

    articles: list[ArticleSearchHit] = Field(default_factory=list)
    messages: list[MessageSearchHit] = Field(default_factory=list)
    users: list[UserPublic] = Field(default_factory=list)


__all__ = [
    "ArticleSearchHit",
    "MessageSearchHit",
    "UnifiedSearchResult",
]
