"""Pydantic v2 schemas for the ``forum`` module."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.forum.models import TopicKind
from app.modules.users.schemas import UserPublic

# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


class SectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    slug: str | None = Field(default=None, max_length=100)
    description: str | None = None
    position: int = 0
    icon: str | None = Field(default=None, max_length=50)


class SectionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    slug: str | None = Field(default=None, max_length=100)
    description: str | None = None
    position: int | None = None
    icon: str | None = Field(default=None, max_length=50)


class SectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    title: str
    description: str | None = None
    position: int
    icon: str | None = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Topics
# ---------------------------------------------------------------------------


class TopicCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=300)
    slug: str | None = Field(default=None, max_length=150)
    description: str | None = None
    kind: TopicKind = TopicKind.DISCUSSION


class TopicUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    is_locked: bool | None = None
    is_pinned: bool | None = None
    kind: TopicKind | None = None


class TopicRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    section_id: UUID
    section_slug: str
    slug: str
    title: str
    description: str | None = None
    is_locked: bool
    is_pinned: bool
    kind: TopicKind
    created_by: UserPublic
    created_at: datetime
    updated_at: datetime


class TopicLockToggle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    locked: bool


__all__ = [
    "SectionCreate",
    "SectionRead",
    "SectionUpdate",
    "TopicCreate",
    "TopicLockToggle",
    "TopicRead",
    "TopicUpdate",
]
