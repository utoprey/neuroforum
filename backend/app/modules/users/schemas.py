"""Pydantic v2 schemas for the ``users`` module."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    field_validator,
)

from app.modules.reactions.models import ReactionKind
from app.modules.users.models import Role

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]+$")
ORCID_RE = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")


# ---------------------------------------------------------------------------
# Profile / stats
# ---------------------------------------------------------------------------


class ProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    display_name: str | None = None
    bio: str | None = None
    avatar_url: str | None = None
    orcid: str | None = None
    social_links: dict[str, Any] = Field(default_factory=dict)
    locale: str = "ru"
    timezone: str = "UTC"


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, max_length=100)
    bio: str | None = None
    avatar_url: str | None = Field(default=None, max_length=500)
    orcid: str | None = Field(default=None, max_length=19)
    social_links: dict[str, Any] | None = None
    locale: str | None = Field(default=None, max_length=10)
    timezone: str | None = Field(default=None, max_length=50)

    @field_validator("orcid")
    @classmethod
    def _orcid_pattern(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        if not ORCID_RE.match(v):
            raise ValueError("ORCID must match pattern ####-####-####-###[0-9X]")
        return v


class StatsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    articles_count: int = 0
    messages_count: int = 0
    received_reactions_count: int = 0
    saved_articles_count: int = 0
    updated_at: datetime | None = None


# ---------------------------------------------------------------------------
# User create / read
# ---------------------------------------------------------------------------


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=3, max_length=50)
    email: EmailStr
    password: SecretStr = Field(min_length=8)

    @field_validator("username")
    @classmethod
    def _username_pattern(cls, v: str) -> str:
        if not USERNAME_RE.match(v):
            raise ValueError(
                "Username must contain only ASCII letters, digits, and underscores"
            )
        return v


class UserRead(BaseModel):
    """Self-view of a user — includes private fields (email, stats)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    email: str | None = None
    role: Role
    is_active: bool
    created_at: datetime
    last_seen_at: datetime | None = None
    is_online: bool = False
    profile: ProfileRead | None = None
    stats: StatsRead | None = None


class UserPublic(BaseModel):
    """Public view of any user — what other accounts see."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    display_name: str | None = None
    avatar_url: str | None = None
    role: Role
    is_online: bool = False
    last_seen_at: datetime | None = None


# ---------------------------------------------------------------------------
# Recent topics — populated by ``forum``/``articles`` modules later.
# ---------------------------------------------------------------------------


class RecentTopic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    title: str
    last_message_at: datetime | None = None


class RecentMessage(BaseModel):
    """A user's recent message with topic/article context for the profile feed."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    article_id: UUID
    article_title: str
    article_slug: str
    topic_id: UUID
    topic_slug: str
    # First 200 characters of ``content_text`` for the feed preview.
    snippet: str
    created_at: datetime


class UserReactionItem(BaseModel):
    """A reaction left by the user, on either an article or a message.

    Returned by ``GET /users/{username}/reactions`` — a unified, time-sorted
    feed across both ``article_reactions`` and ``message_reactions``. The
    ``article_*`` fields always describe the article that owns the target
    (for message reactions, that's the article the comment lives under).
    """

    model_config = ConfigDict(from_attributes=True)

    target_type: Literal["article", "message"]
    target_id: UUID
    kind: ReactionKind
    reacted_at: datetime
    article_id: UUID
    article_slug: str
    article_title: str
    # First 200 chars of the target's ``content_text`` for the feed preview.
    snippet: str


__all__ = [
    "ProfileRead",
    "ProfileUpdate",
    "RecentMessage",
    "RecentTopic",
    "StatsRead",
    "UserCreate",
    "UserPublic",
    "UserReactionItem",
    "UserRead",
]
