"""SQLAlchemy 2.0 typed model for ``mentions``.

A ``mention`` row is polymorphic over its ``source_type`` — no DB-level FK
on ``source_id`` (because the target table varies). Application code is
responsible for inserting consistent values; the index on
``(source_type, source_id)`` keeps backfill-on-edit queries cheap.
"""

from __future__ import annotations

import enum
import importlib
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    UniqueConstraint,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.db import Base

# Ensure the ``users`` table is registered before our FK resolves.
importlib.import_module("app.modules.users.models")


class MentionSourceType(str, enum.Enum):  # noqa: UP042 — spec requires `(str, enum.Enum)`
    """Where the mention originated. Stored as Postgres enum ``mention_source_type``."""

    ARTICLE = "article"
    MESSAGE = "message"
    DIRECT_MESSAGE = "direct_message"


class Mention(Base):
    """One row per ``(source_type, source_id, mentioned_user_id)`` mention."""

    __tablename__ = "mentions"
    __table_args__ = (
        # Cheap "my mentions" feed.
        Index(
            "ix_mentions_mentioned_created",
            "mentioned_user_id",
            text("created_at DESC"),
        ),
        # Backfill on edit: "find every mention currently tied to this source".
        Index("ix_mentions_source", "source_type", "source_id"),
        # De-duplication: re-saving the same article shouldn't double-mention.
        UniqueConstraint(
            "source_type",
            "source_id",
            "mentioned_user_id",
            name="uq_mentions_source_user",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_type: Mapped[MentionSourceType] = mapped_column(
        SAEnum(
            MentionSourceType,
            name="mention_source_type",
            native_enum=True,
            create_type=True,
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
    )
    # Polymorphic — no DB-level FK because the table varies with source_type.
    source_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False
    )
    mentioned_user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Author FK has NO CASCADE so the mention history survives an account
    # deletion (we keep it for moderation audit). The mentioned user IS
    # cascaded above because they own the receiving inbox.
    author_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = ["Mention", "MentionSourceType"]
