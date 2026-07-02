"""Pydantic v2 schemas for the ``embeds`` module."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class EmbedRequest(BaseModel):
    """Query payload: a URL to resolve."""

    model_config = ConfigDict(extra="forbid")

    url: HttpUrl


class EmbedData(BaseModel):
    """Provider-resolved embed payload — what the frontend actually renders."""

    model_config = ConfigDict(extra="forbid")

    iframe_src: str | None = None
    width: int
    height: int
    title: str | None = None
    thumbnail: str | None = None
    raw_meta: dict[str, object] = Field(default_factory=dict)


class EmbedResponse(BaseModel):
    """Cache-aware response: ``cached`` indicates whether this hit the cache."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    url: str
    data: EmbedData
    fetched_at: datetime
    cached: bool


__all__ = ["EmbedData", "EmbedRequest", "EmbedResponse"]
