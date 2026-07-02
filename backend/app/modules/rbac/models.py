"""SQLAlchemy model for ``user_bans``."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Table,
    Text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.db import Base


def _ensure_placeholder_table(name: str) -> None:
    """Register a minimal ``id UUID PK`` placeholder so cross-module FKs resolve.

    The ``forum`` and ``articles`` modules redefine these tables with their
    full schemas when they are loaded — and SQLAlchemy short-circuits a
    second ``Table(name, metadata, ...)`` with ``extend_existing=False``
    because the table already exists in the metadata. Each redefinition is
    expected to use ``extend_existing=True`` to merge columns.

    Until the ``forum``/``articles`` modules land, these placeholders make
    rbac's cross-module FKs resolvable at metadata-build time *and* at
    DDL-create time (so tests can spin up the schema with only the
    foundation modules loaded).
    """
    if name in Base.metadata.tables:
        return
    Table(
        name,
        Base.metadata,
        Column("id", PG_UUID(as_uuid=True), primary_key=True),
        # ``info`` marks this as a placeholder so downstream tooling can
        # detect it and the future forum/articles agents can opt to drop &
        # recreate it cleanly.
        info={"placeholder_for": ("forum", "articles")},
    )


# Cross-module FK targets — see use_alter=True below.
_ensure_placeholder_table("sections")
_ensure_placeholder_table("topics")


class BanScope(str, enum.Enum):  # noqa: UP042 — spec requires `(str, enum.Enum)`
    """Where the ban applies. Stored as Postgres native enum ``ban_scope``."""

    GLOBAL = "global"
    SECTION = "section"
    TOPIC = "topic"


class UserBan(Base):
    """One row per ban action. ``lifted_at`` flips to a timestamp when unbanned."""

    __tablename__ = "user_bans"
    __table_args__ = (
        # Permission check on every authed request — keep this tight.
        Index(
            "ix_user_bans_user_id_expires_at",
            "user_id",
            "expires_at",
        ),
        # Scope ↔ target column consistency.
        CheckConstraint(
            "(scope = 'global'  AND section_id IS NULL AND topic_id IS NULL) OR "
            "(scope = 'section' AND section_id IS NOT NULL AND topic_id IS NULL) OR "
            "(scope = 'topic'   AND section_id IS NULL AND topic_id IS NOT NULL)",
            name="scope_target_consistency",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    banned_by: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[BanScope] = mapped_column(
        SAEnum(
            BanScope,
            name="ban_scope",
            native_enum=True,
            create_type=True,
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
    )
    # Cross-module FK to ``sections.id`` — table created by ``forum`` module
    # later. ``use_alter`` defers FK creation until both tables exist so
    # Alembic autogenerate doesn't hit a cycle.
    section_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "sections.id",
            use_alter=True,
            name="fk_user_bans_section_id_sections",
            ondelete="CASCADE",
            deferrable=True,
        ),
        nullable=True,
    )
    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "topics.id",
            use_alter=True,
            name="fk_user_bans_topic_id_topics",
            ondelete="CASCADE",
            deferrable=True,
        ),
        nullable=True,
    )
    starts_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lifted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lifted_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    lift_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = ["BanScope", "UserBan"]
