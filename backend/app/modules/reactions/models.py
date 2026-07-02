"""SQLAlchemy 2.0 typed models for ``article_reactions`` and ``message_reactions``.

Both tables share a single Postgres enum ``reaction_kind`` — see
``docs/data-model.md`` for the fixed neuro-themed glyph set. The enum type
is created exactly once (declared with ``create_type=True`` on the
``ArticleReaction`` side; the ``MessageReaction`` mapping reuses the same
type with ``create_type=False`` so DDL doesn't try to create it twice).
"""

from __future__ import annotations

import enum
import importlib
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    PrimaryKeyConstraint,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.db import Base

# Make sure FK targets are registered before our PKs/FKs resolve. ``users``
# always loads first; ``articles`` and ``messages`` come earlier than
# ``reactions`` in alphabetical order, but the explicit import keeps direct
# REPL usage honest.
importlib.import_module("app.modules.users.models")
importlib.import_module("app.modules.articles.models")
importlib.import_module("app.modules.messages.models")


class ReactionKind(str, enum.Enum):  # noqa: UP042 — spec requires `(str, enum.Enum)`
    """Fixed neuro-themed reaction set. Stored as Postgres enum ``reaction_kind``."""

    BRAIN = "brain"
    SYNAPSE = "synapse"
    NEURON = "neuron"
    MICROSCOPE = "microscope"
    DNA = "dna"
    MINDBLOWN = "mindblown"
    PETRI = "petri"
    LIGHTBULB = "lightbulb"


class ArticleReaction(Base):
    """One row per ``(user, article, kind)`` reaction."""

    __tablename__ = "article_reactions"
    __table_args__ = (
        PrimaryKeyConstraint(
            "user_id",
            "article_id",
            "kind",
            name="pk_article_reactions",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    article_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("articles.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[ReactionKind] = mapped_column(
        # ``create_type=True`` is the canonical declaration; ``MessageReaction``
        # references the same enum with ``create_type=False``.
        SAEnum(
            ReactionKind,
            name="reaction_kind",
            native_enum=True,
            create_type=True,
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MessageReaction(Base):
    """One row per ``(user, message, kind)`` reaction."""

    __tablename__ = "message_reactions"
    __table_args__ = (
        PrimaryKeyConstraint(
            "user_id",
            "message_id",
            "kind",
            name="pk_message_reactions",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[ReactionKind] = mapped_column(
        SAEnum(
            ReactionKind,
            name="reaction_kind",
            native_enum=True,
            # Reuse the type owned by ``ArticleReaction`` above — don't try
            # to ``CREATE TYPE`` it a second time.
            create_type=False,
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = ["ArticleReaction", "MessageReaction", "ReactionKind"]
