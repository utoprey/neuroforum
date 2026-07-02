"""SQLAlchemy 2.0 typed model for ``audit_log``.

Append-only, BIGSERIAL PK because UUID indexes bloat for time-ordered inserts.
"""

from __future__ import annotations

import importlib
from datetime import datetime
from uuid import UUID as _UUID

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.db import Base

# Ensure the ``users`` table is registered before our FK resolves.
importlib.import_module("app.modules.users.models")


class AuditLog(Base):
    """One row per moderation / admin action. Insert-only; never updated or deleted."""

    __tablename__ = "audit_log"
    __table_args__ = (
        Index(
            "ix_audit_log_actor_created",
            "actor_id",
            text("created_at DESC"),
        ),
        Index("ix_audit_log_target", "target_type", "target_id"),
        Index(
            "ix_audit_log_action_created",
            "action",
            text("created_at DESC"),
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    actor_id: Mapped[_UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # Logical FK — varies by target_type, no DB FK.
    target_id: Mapped[_UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False
    )
    payload: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = ["AuditLog"]
