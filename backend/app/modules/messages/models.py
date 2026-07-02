"""SQLAlchemy 2.0 typed models for ``messages`` and ``message_revisions``.

Notes
-----
- ``content_tsv``: production migration replaces the column with a
  ``GENERATED ALWAYS AS (to_tsvector('russian', coalesce(content_text, '')))
  STORED`` definition plus a GIN index. On the ORM side we expose a deferred
  TSVECTOR with empty ``server_default`` so ``Base.metadata.create_all``
  succeeds in tests.
- ``path``: Postgres ``LTREE``. Subtree queries use the ``<@`` operator via
  ``sqlalchemy.text()``. The GIST index on ``path`` is added by the Alembic
  migration — not strictly required for tests (LTREE comparisons work on a
  plain B-tree-less column too, just less efficiently).
- The cross-module ``article_id`` / ``users.id`` FKs rely on the respective
  modules being loaded. Module discovery imports alphabetically (``articles``
  < ``messages``), but we still issue an explicit ``importlib.import_module``
  to keep direct REPL imports honest.
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
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.db import Base
from app.modules.messages.types import Ltree

# Make sure the real ``articles`` / ``users`` tables are registered before
# our FKs resolve against them. Alphabetical discovery already does this,
# but importing explicitly keeps direct ``python -c`` imports honest.
importlib.import_module("app.modules.articles.models")
importlib.import_module("app.modules.users.models")


class MessageStatus(str, enum.Enum):  # noqa: UP042 — spec requires `(str, enum.Enum)`
    """Lifecycle state of a message. Stored as Postgres enum ``message_status``."""

    VISIBLE = "visible"
    EDITED = "edited"
    HIDDEN_BY_MOD = "hidden_by_mod"
    DELETED_BY_AUTHOR = "deleted_by_author"


class Message(Base):
    """A threaded comment under an article. ProseMirror JSON in ``content``."""

    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_article_created_at", "article_id", "created_at"),
        Index("ix_messages_parent_created_at", "parent_id", "created_at"),
        # Newest-first author feed.
        Index(
            "ix_messages_author_created_at",
            "author_id",
            text("created_at DESC"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    article_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("articles.id", ondelete="CASCADE"),
        nullable=False,
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=True,
    )
    thread_root_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=True,
    )
    depth: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0"
    )
    # Materialised path. UUIDs with ``-`` replaced by ``_`` so each segment
    # is a valid LTREE label (LTREE labels are ``[A-Za-z0-9_]+``).
    path: Mapped[str] = mapped_column(Ltree(), nullable=False)
    author_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    content: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    content_text: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
    # See module docstring re: GENERATED column in production.
    content_tsv: Mapped[str | None] = mapped_column(
        TSVECTOR,
        nullable=True,
        deferred=True,
        server_default=text("''"),
    )
    reply_to_selection: Mapped[dict[str, object] | None] = mapped_column(
        JSONB, nullable=True
    )
    status: Mapped[MessageStatus] = mapped_column(
        SAEnum(
            MessageStatus,
            name="message_status",
            native_enum=True,
            create_type=True,
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
        default=MessageStatus.VISIBLE,
        server_default=MessageStatus.VISIBLE.value,
    )
    mentioned_user_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)),
        nullable=False,
        default=list,
        server_default=text("'{}'"),
    )
    reaction_counts: Mapped[dict[str, int]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
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

    revisions: Mapped[list[MessageRevision]] = relationship(
        "MessageRevision",
        back_populates="message",
        cascade="all, delete-orphan",
        lazy="noload",
    )


class MessageRevision(Base):
    """Immutable snapshot of a message taken before edits and soft deletes."""

    __tablename__ = "message_revisions"
    __table_args__ = (
        UniqueConstraint(
            "message_id",
            "revision",
            name="uq_message_revisions_message_id_revision",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    editor_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    # ``Role.value`` is at most ``"moderator"`` — 20 chars leaves headroom.
    editor_role_at_edit: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    edit_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    message: Mapped[Message] = relationship("Message", back_populates="revisions")


__all__ = ["Message", "MessageRevision", "MessageStatus"]
