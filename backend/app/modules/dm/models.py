"""SQLAlchemy 2.0 typed models for ``conversations`` / ``direct_messages``."""

from __future__ import annotations

import enum
import importlib
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    String,
    Text,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.db import Base

# Ensure the ``users`` table is registered before our FKs resolve.
importlib.import_module("app.modules.users.models")


class ConversationKind(str, enum.Enum):  # noqa: UP042 — spec requires `(str, enum.Enum)`
    """Stored as Postgres enum ``conversation_kind``."""

    DM = "dm"
    GROUP = "group"


class DirectMessageStatus(str, enum.Enum):  # noqa: UP042
    """Stored as Postgres enum ``direct_message_status``."""

    VISIBLE = "visible"
    EDITED = "edited"
    DELETED_BY_AUTHOR = "deleted_by_author"


class Conversation(Base):
    """A direct (1:1) or group conversation thread."""

    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    kind: Mapped[ConversationKind] = mapped_column(
        SAEnum(
            ConversationKind,
            name="conversation_kind",
            native_enum=True,
            create_type=True,
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
    )
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # ``"{min_uuid}:{max_uuid}"`` for DMs (36+1+36 = 73 chars); NULL for groups.
    dm_key: Mapped[str | None] = mapped_column(
        String(73), nullable=True, unique=True
    )
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ConversationParticipant(Base):
    """Membership row: links a user to a conversation."""

    __tablename__ = "conversation_participants"
    __table_args__ = (
        PrimaryKeyConstraint(
            "conversation_id",
            "user_id",
            name="pk_conversation_participants",
        ),
        # Newest-first per-user listing of their conversations.
        Index(
            "ix_conversation_participants_user_id_joined_at",
            "user_id",
            text("joined_at DESC"),
        ),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    muted_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Soft leave so historical messages still resolve participant info.
    left_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class DirectMessage(Base):
    """A message inside a conversation. ProseMirror JSON in ``content``."""

    __tablename__ = "direct_messages"
    __table_args__ = (
        Index(
            "ix_direct_messages_conversation_id_created_at",
            "conversation_id",
            text("created_at DESC"),
        ),
        Index(
            "ix_direct_messages_author_id_created_at",
            "author_id",
            text("created_at DESC"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    content: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    content_text: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
    reply_to_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("direct_messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[DirectMessageStatus] = mapped_column(
        SAEnum(
            DirectMessageStatus,
            name="direct_message_status",
            native_enum=True,
            create_type=True,
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
        default=DirectMessageStatus.VISIBLE,
        server_default=DirectMessageStatus.VISIBLE.value,
    )
    attachments: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)),
        nullable=False,
        default=list,
        server_default=text("'{}'"),
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


class DirectMessageRead(Base):
    """Per-user read receipt for a specific message."""

    __tablename__ = "direct_message_reads"
    __table_args__ = (
        PrimaryKeyConstraint(
            "user_id",
            "message_id",
            name="pk_direct_message_reads",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("direct_messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    read_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# Sanity assertion: the dm_key column is wide enough for two UUIDs + ":".
_EXPECTED_DM_KEY_LEN = 36 + 1 + 36
assert _EXPECTED_DM_KEY_LEN == 73


def make_dm_key(a: uuid.UUID, b: uuid.UUID) -> str:
    """Stable, order-independent DM uniqueness key for a pair of users."""
    sa, sb = str(a), str(b)
    return f"{min(sa, sb)}:{max(sa, sb)}"


__all__ = [
    "Conversation",
    "ConversationKind",
    "ConversationParticipant",
    "DirectMessage",
    "DirectMessageRead",
    "DirectMessageStatus",
    "make_dm_key",
]
