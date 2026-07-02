"""SQLAlchemy 2.0 typed models for ``sections`` and ``topics``.

Placeholder handling
--------------------
The ``rbac`` module registers minimal ``sections`` / ``topics`` placeholder
``Table`` objects on ``Base.metadata`` so that ``user_bans.section_id`` and
``user_bans.topic_id`` cross-module FKs (``use_alter=True``) resolve at
metadata-build time *and* at ``Base.metadata.create_all`` time, even when
the forum module hasn't been loaded yet.

When this module IS loaded we want the real, fully-fledged models — not
the placeholders. SQLAlchemy refuses to silently swap a table definition
(it requires ``extend_existing=True``, which merges columns instead of
replacing them). We therefore pop the placeholders from the metadata
*before* declaring the real classes.

Order of imports matters: ``app.modules.rbac.models`` must already have
been imported by the time we reach the ``pop()`` calls — which is
guaranteed by ``pkgutil.iter_modules`` autodiscovery (alphabetical:
``forum`` comes after ``rbac``). We still call ``importlib.import_module``
defensively so the file works correctly even when imported directly in a
REPL.
"""

from __future__ import annotations

import enum
import importlib
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
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

# Ensure ``rbac`` is loaded first so the placeholder tables exist and we
# pop the placeholder version (not someone else's stale stub).
importlib.import_module("app.modules.rbac.models")

# Replace placeholder tables registered by ``app.modules.rbac.models``
# with our real definitions below. ``extend_existing=True`` would merge
# columns, which is the wrong semantics — we want fresh, complete tables.
# ``MetaData.tables`` is a :class:`FacadeDict` (immutable), so we use the
# private :meth:`_remove_table` helper which mutates the underlying dict
# *and* clears related sorted-tables caches. ``Base.metadata.tables.pop``
# would raise ``TypeError: FacadeDict object is immutable``.
for _placeholder_name in ("sections", "topics"):
    if _placeholder_name in Base.metadata.tables:
        Base.metadata._remove_table(_placeholder_name, None)


class TopicKind(str, enum.Enum):  # noqa: UP042 — spec requires `(str, enum.Enum)`
    """Topic kind. Stored as Postgres native enum ``topic_kind``.

    News topics are reserved for moderators/admins (these are long-form
    article containers). Discussion/help/flood are open to any authed user.
    """

    NEWS = "news"
    DISCUSSION = "discussion"
    HELP = "help"
    FLOOD = "flood"


class Section(Base):
    """Top-level discussion area (e.g. ``fmri``, ``connectomics``)."""

    __tablename__ = "sections"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    icon: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    topics: Mapped[list[Topic]] = relationship(
        "Topic",
        back_populates="section",
        cascade="all, delete-orphan",
        lazy="noload",
    )


class Topic(Base):
    """A discussion thread anchor inside a :class:`Section`."""

    __tablename__ = "topics"
    __table_args__ = (
        UniqueConstraint("section_id", "slug", name="uq_topics_section_id_slug"),
        Index(
            "ix_topics_section_id_is_pinned_created_at",
            "section_id",
            "is_pinned",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    section_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("sections.id", ondelete="RESTRICT"),
        nullable=False,
    )
    slug: Mapped[str] = mapped_column(String(150), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_locked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    is_pinned: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    kind: Mapped[TopicKind] = mapped_column(
        SAEnum(
            TopicKind,
            name="topic_kind",
            native_enum=True,
            create_type=True,
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
        default=TopicKind.DISCUSSION,
        server_default=TopicKind.DISCUSSION.value,
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
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

    section: Mapped[Section] = relationship("Section", back_populates="topics")


__all__ = ["Section", "Topic", "TopicKind"]
