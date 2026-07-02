"""SQLAlchemy 2.0 typed models for ``attachments`` and ``attachment_usages``."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.db import Base


class AttachmentKind(str, enum.Enum):  # noqa: UP042 — spec requires `(str, enum.Enum)`
    """Kind of uploaded blob. Stored as Postgres enum ``attachment_kind``."""

    IMAGE = "image"
    GIF = "gif"
    VIDEO = "video"
    FILE = "file"


class ProcessingStatus(str, enum.Enum):  # noqa: UP042 — spec requires `(str, enum.Enum)`
    """Lifecycle of an uploaded blob. Non-video files go straight to READY."""

    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


class Attachment(Base):
    """One MinIO object + its metadata."""

    __tablename__ = "attachments"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    uploader_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    kind: Mapped[AttachmentKind] = mapped_column(
        SAEnum(
            AttachmentKind,
            name="attachment_kind",
            native_enum=True,
            create_type=True,
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
    )
    bucket: Mapped[str] = mapped_column(
        String(50), nullable=False, default="forum-media", server_default="forum-media"
    )
    object_key: Mapped[str] = mapped_column(
        String(500), nullable=False, unique=True
    )
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    poster_object_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    processing_status: Mapped[ProcessingStatus] = mapped_column(
        SAEnum(
            ProcessingStatus,
            name="attachment_processing_status",
            native_enum=True,
            create_type=True,
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
        default=ProcessingStatus.READY,
        server_default=ProcessingStatus.READY.value,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    usages: Mapped[list[AttachmentUsage]] = relationship(
        "AttachmentUsage",
        back_populates="attachment",
        cascade="all, delete-orphan",
        lazy="noload",
    )


class AttachmentUsage(Base):
    """Many-to-many between attachments and any entity that references them.

    ``entity_type`` is a free-form string (``'article'``, ``'message'``,
    ``'article_revision'``, …) so we don't need a polymorphic FK. The
    garbage-collector finds rows with zero usages.
    """

    __tablename__ = "attachment_usages"
    __table_args__ = (
        UniqueConstraint(
            "attachment_id",
            "entity_type",
            "entity_id",
            name="uq_attachment_usages_attachment_id_entity_type_entity_id",
        ),
        Index(
            "ix_attachment_usages_entity_type_entity_id",
            "entity_type",
            "entity_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    attachment_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("attachments.id", ondelete="CASCADE"),
        nullable=False,
    )
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    attachment: Mapped[Attachment] = relationship(
        "Attachment", back_populates="usages"
    )


__all__ = [
    "Attachment",
    "AttachmentKind",
    "AttachmentUsage",
    "ProcessingStatus",
]
