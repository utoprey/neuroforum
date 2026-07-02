"""SQLAlchemy 2.0 typed model for ``external_sources``.

One row per (external system, external id) referenced by the forum.
``article_id`` is populated once an import creates a draft article and
stays NULL for purely-metadata-only previews if we ever store them.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.db import Base


class ExternalSource(str, enum.Enum):  # noqa: UP042 — spec requires `(str, enum.Enum)`
    """Which upstream system this row was harvested from."""

    ARXIV = "arxiv"
    BIORXIV = "biorxiv"
    DOI = "doi"
    PUBMED = "pubmed"
    CUSTOM = "custom"


class ExternalSourceRecord(Base):
    """One imported external reference (arxiv paper, DOI, …)."""

    __tablename__ = "external_sources"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "external_id",
            name="uq_external_sources_source_external_id",
        ),
        Index("ix_external_sources_article_id", "article_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    article_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("articles.id", ondelete="SET NULL"),
        nullable=True,
    )
    source: Mapped[ExternalSource] = mapped_column(
        SAEnum(
            ExternalSource,
            name="external_source_type",
            native_enum=True,
            create_type=True,
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
    )
    external_id: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_url: Mapped[str] = mapped_column(String(500), nullable=False)
    pdf_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # ``metadata`` is reserved on ``DeclarativeBase``; use the trailing
    # underscore on the Python side and pin the SQL column name.
    metadata_: Mapped[dict[str, object]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


__all__ = ["ExternalSource", "ExternalSourceRecord"]
