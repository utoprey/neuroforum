"""Pydantic v2 schemas for the ``imports`` module."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.articles.schemas import ArticleRead
from app.modules.imports.models import ExternalSource


class ArxivImportRequest(BaseModel):
    """Body for the moderator-triggered arXiv import."""

    model_config = ConfigDict(extra="forbid")

    url_or_id: str = Field(min_length=1, max_length=200)
    topic_id: UUID


class ArxivPreview(BaseModel):
    """Lightweight preview returned by the GET endpoint — no DB writes."""

    model_config = ConfigDict(extra="forbid")

    arxiv_id: str
    title: str
    authors: list[str]
    abstract: str
    categories: list[str]
    primary_category: str | None = None
    published_at: datetime | None = None
    doi: str | None = None
    pdf_url: str | None = None
    source_url: str


class ExternalSourceRead(BaseModel):
    """Read view for ``external_sources`` rows."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    article_id: UUID | None = None
    source: ExternalSource
    external_id: str
    version: str | None = None
    source_url: str
    pdf_url: str | None = None
    metadata_: dict[str, object] = Field(default_factory=dict, alias="metadata_")
    fetched_at: datetime
    published_at: datetime | None = None


class ArxivImportResponse(BaseModel):
    """Result of a successful import: draft article + external source row."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    article: ArticleRead
    source: ExternalSourceRead


__all__ = [
    "ArxivImportRequest",
    "ArxivImportResponse",
    "ArxivPreview",
    "ExternalSourceRead",
]
