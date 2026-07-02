"""SQLAlchemy 2.0 typed model for ``saved_articles``."""

from __future__ import annotations

import importlib
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.db import Base

# Ensure FK targets are registered before our PK/FKs resolve.
importlib.import_module("app.modules.users.models")
importlib.import_module("app.modules.articles.models")


class SavedArticle(Base):
    """One row per ``(user, article)`` bookmark."""

    __tablename__ = "saved_articles"
    __table_args__ = (
        PrimaryKeyConstraint(
            "user_id", "article_id", name="pk_saved_articles"
        ),
        Index(
            "ix_saved_articles_user_saved_at",
            "user_id",
            text("saved_at DESC"),
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
    saved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = ["SavedArticle"]
