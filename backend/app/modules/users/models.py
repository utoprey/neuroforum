"""SQLAlchemy 2.0 typed models for ``users``, ``user_profiles``, ``user_stats``."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DDL,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    event,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.db import Base

# Ensure required Postgres extensions exist before any tables are created.
# In production these are created by the first Alembic migration; in tests
# we use ``Base.metadata.create_all`` directly, so we attach the DDL here.
for _extension in ("uuid-ossp", "citext", "pg_trgm", "ltree"):
    _ddl = DDL(f'CREATE EXTENSION IF NOT EXISTS "{_extension}"')  # type: ignore[no-untyped-call]
    event.listen(
        Base.metadata,
        "before_create",
        _ddl.execute_if(dialect="postgresql"),
    )

if TYPE_CHECKING:  # pragma: no cover
    pass


class Role(str, enum.Enum):  # noqa: UP042 — spec requires `(str, enum.Enum)`
    """User role. Stored as Postgres native enum ``user_role``."""

    USER = "user"
    MODERATOR = "moderator"
    ADMIN = "admin"
    AGENT = "agent"


class User(Base):
    """Account record. Both humans and LLM agents live here."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    # CITEXT for case-insensitive uniqueness; NULL for ``role='agent'``.
    email: Mapped[str | None] = mapped_column(CITEXT(), unique=True, nullable=True)
    # NULL for agents — they authenticate via bot tokens, not passwords.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[Role] = mapped_column(
        SAEnum(
            Role,
            name="user_role",
            native_enum=True,
            create_type=True,
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
        default=Role.USER,
        server_default=Role.USER.value,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Bumped by ``PresenceMiddleware`` on every authenticated request. Used
    # for "online now" badges (``is_online == last_seen_at within 5 min``).
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    profile: Mapped[UserProfile | None] = relationship(
        "UserProfile",
        uselist=False,
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    stats: Mapped[UserStats | None] = relationship(
        "UserStats",
        uselist=False,
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class UserProfile(Base):
    """1:1 with ``User``. Splits "vanity" fields from auth-critical ones."""

    __tablename__ = "user_profiles"
    # ORCID pattern: ^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$ — 19 chars, last is digit or X.
    __table_args__ = (
        CheckConstraint(
            r"orcid IS NULL OR orcid ~ '^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$'",
            name="orcid_format",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    orcid: Mapped[str | None] = mapped_column(String(19), nullable=True)
    social_links: Mapped[dict[str, str]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    locale: Mapped[str] = mapped_column(
        String(10), nullable=False, default="ru", server_default="ru"
    )
    timezone: Mapped[str] = mapped_column(
        String(50), nullable=False, default="UTC", server_default="UTC"
    )

    user: Mapped[User] = relationship("User", back_populates="profile")


class UserStats(Base):
    """1:1 with ``User``. Denormalized counters, kept fresh by service hooks."""

    __tablename__ = "user_stats"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    articles_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    messages_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    received_reactions_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    saved_articles_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    user: Mapped[User] = relationship("User", back_populates="stats")


__all__ = ["Role", "User", "UserProfile", "UserStats"]
