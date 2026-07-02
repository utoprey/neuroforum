"""Pydantic v2 schemas for the ``articles`` module."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.articles.models import ArticleStatus
from app.modules.content.schemas import DocSchema
from app.modules.users.schemas import UserPublic


def _coerce_doc(value: Any) -> DocSchema:
    """Accept either a raw dict (HTTP JSON body) or an already-built ``DocSchema``."""
    if isinstance(value, DocSchema):
        return value
    if isinstance(value, dict):
        # ``validate_doc`` wraps Pydantic's ValidationError into ContentValidationError
        # — but here we're inside a field validator so we just re-raise so Pydantic
        # itself reports the error to the HTTP layer (FastAPI -> 422).
        return DocSchema.model_validate(value)
    raise ValueError("content must be a DocSchema or a JSON object")


# ---------------------------------------------------------------------------
# Create / update
# ---------------------------------------------------------------------------


class ArticleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    title: str = Field(min_length=1, max_length=300)
    slug: str | None = Field(default=None, max_length=200)
    summary: str | None = None
    content: DocSchema

    @field_validator("content", mode="before")
    @classmethod
    def _validate_content(cls, value: Any) -> DocSchema:
        return _coerce_doc(value)


class ArticleUpdate(BaseModel):
    """Patch payload. ``edit_reason`` is required when a mod/admin edits."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    title: str | None = Field(default=None, min_length=1, max_length=300)
    summary: str | None = None
    content: DocSchema | None = None
    edit_reason: str | None = None

    @field_validator("content", mode="before")
    @classmethod
    def _validate_content(cls, value: Any) -> DocSchema | None:
        if value is None:
            return None
        return _coerce_doc(value)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


class ArticleRead(BaseModel):
    """Full article view, includes ProseMirror content."""

    model_config = ConfigDict(from_attributes=True, arbitrary_types_allowed=True)

    id: UUID
    topic_id: UUID
    slug: str
    title: str
    summary: str | None = None
    content: DocSchema
    author: UserPublic
    status: ArticleStatus
    published_at: datetime | None = None
    view_count: int
    comment_count: int
    mentioned_user_ids: list[UUID] = Field(default_factory=list)
    reaction_counts: dict[str, int] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class ArticlePublic(BaseModel):
    """Listing view: no full content, just metadata + summary."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    topic_id: UUID
    title: str
    summary: str | None = None
    author: UserPublic
    status: ArticleStatus
    published_at: datetime | None = None
    view_count: int
    comment_count: int
    reaction_counts: dict[str, int] = Field(default_factory=dict)


class ArticleRevisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, arbitrary_types_allowed=True)

    id: UUID
    revision: int
    editor: UserPublic
    editor_role_at_edit: str
    title: str
    content: DocSchema
    edit_reason: str | None = None
    created_at: datetime


__all__ = [
    "ArticleCreate",
    "ArticlePublic",
    "ArticleRead",
    "ArticleRevisionRead",
    "ArticleUpdate",
]
