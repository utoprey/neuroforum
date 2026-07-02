"""SQLAlchemy 2.0 typed models for ``articles`` and ``article_revisions``.

Notes
-----
- ``content_tsv``: in production this column is ``GENERATED ALWAYS AS
  (to_tsvector('russian', coalesce(content_text,''))) STORED`` — added by
  Alembic via raw SQL because SQLAlchemy can't emit ``GENERATED ALWAYS AS``
  for a TSVECTOR column directly. The ORM-side mapping below is just a
  deferred read-only column with ``server_default=text("''")`` so that
  ``Base.metadata.create_all`` in tests succeeds against a plain Postgres
  cluster. The Alembic migration drops & re-creates the column as
  ``GENERATED`` plus a GIN index.
- The ``Article.topic_id`` FK relies on ``forum.models.Topic`` being loaded
  first. Module autodiscovery imports alphabetically (``articles`` < ``forum``);
  we therefore eagerly import ``forum.models`` here so the placeholder pop
  + real definition has happened by the time we declare our own FKs.
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

# Make sure the real ``topics`` table is in the metadata before our FK
# resolves against it. Module-discovery loads packages alphabetically, so
# ``articles`` is imported before ``forum`` — without this explicit nudge,
# Article.topic_id would end up pointing at rbac's placeholder table.
importlib.import_module("app.modules.forum.models")


class ArticleStatus(str, enum.Enum):  # noqa: UP042 — spec requires `(str, enum.Enum)`
    """Lifecycle state of an article. Stored as Postgres enum ``article_status``."""

    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"
    HIDDEN = "hidden"


class Article(Base):
    """A long-form post: ProseMirror JSON in ``content`` + denormalised counters."""

    __tablename__ = "articles"
    __table_args__ = (
        UniqueConstraint("topic_id", "slug", name="uq_articles_topic_id_slug"),
        Index(
            "ix_articles_topic_id_status_published_at",
            "topic_id",
            "status",
            "published_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    topic_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("topics.id", ondelete="RESTRICT"),
        nullable=False,
    )
    slug: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ProseMirror document. Pydantic ``DocSchema`` is the source of truth;
    # ORM only sees a dict-shaped JSONB blob.
    content: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    # Plain-text projection used both for snippets and as the source for
    # ``content_tsv``.
    content_text: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
    # See module docstring: GENERATED column in production, plain TSVECTOR
    # with empty default in tests. ``deferred=True`` keeps it out of the
    # default selectable so we don't accidentally write to it.
    content_tsv: Mapped[str | None] = mapped_column(
        TSVECTOR,
        nullable=True,
        deferred=True,
        server_default=text("''"),
    )

    author_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    status: Mapped[ArticleStatus] = mapped_column(
        SAEnum(
            ArticleStatus,
            name="article_status",
            native_enum=True,
            create_type=True,
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
        default=ArticleStatus.DRAFT,
        server_default=ArticleStatus.DRAFT.value,
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    view_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    comment_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
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

    revisions: Mapped[list[ArticleRevision]] = relationship(
        "ArticleRevision",
        back_populates="article",
        cascade="all, delete-orphan",
        lazy="noload",
    )


class ArticleRevision(Base):
    """Immutable snapshot of an article taken before each mod/admin edit."""

    __tablename__ = "article_revisions"
    __table_args__ = (
        UniqueConstraint(
            "article_id",
            "revision",
            name="uq_article_revisions_article_id_revision",
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
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    editor_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    editor_role_at_edit: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    content: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    edit_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    article: Mapped[Article] = relationship("Article", back_populates="revisions")


__all__ = ["Article", "ArticleRevision", "ArticleStatus"]
