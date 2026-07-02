"""Pydantic v2 schemas for the ``saved`` module."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.modules.articles.schemas import ArticlePublic


class SavedArticleRead(BaseModel):
    """Single saved-article entry — denormalises the article payload for fast feeds."""

    model_config = ConfigDict(from_attributes=True)

    article_id: UUID
    saved_at: datetime
    article: ArticlePublic


__all__ = ["SavedArticleRead"]
