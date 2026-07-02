"""SQLAlchemy 2.0 typed models for ``article_ai_proposals``."""

from __future__ import annotations

import enum
import importlib
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Text,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.db import Base

# Ensure dependent tables exist in metadata before our FKs resolve.
importlib.import_module("app.modules.users.models")
importlib.import_module("app.modules.articles.models")
# Imported so the ``agent_id`` FK target (``agents.user_id``) is resolvable
# when this module is loaded standalone (the test conftest also discovers
# every module's models, but explicit is friendlier).
importlib.import_module("app.modules.agents.models")


class AIProposalAction(str, enum.Enum):  # noqa: UP042 — spec requires `(str, enum.Enum)`
    """Stored as Postgres enum ``ai_proposal_action``."""

    DRAFT = "draft"
    EXPAND = "expand"
    REPHRASE = "rephrase"
    SUMMARIZE = "summarize"
    CITE_CHECK = "cite_check"
    TRANSLATE = "translate"
    OUTLINE = "outline"


class AIProposalStatus(str, enum.Enum):  # noqa: UP042
    """Stored as Postgres enum ``ai_proposal_status``."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ArticleAIProposal(Base):
    """An AI-assist suggestion attached to an article."""

    __tablename__ = "article_ai_proposals"
    __table_args__ = (
        Index(
            "ix_article_ai_proposals_article_id_status_created_at",
            "article_id",
            "status",
            text("created_at DESC"),
        ),
        # Cheap range scan for the cleanup cron actor.
        Index("ix_article_ai_proposals_expires_at", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    article_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("articles.id", ondelete="CASCADE"),
        nullable=False,
    )
    requested_by: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    # ``agents.user_id`` is the agent's user PK. ``use_alter`` keeps Alembic
    # happy regardless of module ordering.
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "agents.user_id",
            use_alter=True,
            name="fk_article_ai_proposals_agent_id_agents",
        ),
        nullable=True,
    )
    action: Mapped[AIProposalAction] = mapped_column(
        SAEnum(
            AIProposalAction,
            name="ai_proposal_action",
            native_enum=True,
            create_type=True,
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
    )
    selection: Mapped[dict[str, object] | None] = mapped_column(
        JSONB, nullable=True
    )
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    context: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    proposed_content: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False
    )
    proposed_diff: Mapped[dict[str, object] | None] = mapped_column(
        JSONB, nullable=True
    )
    status: Mapped[AIProposalStatus] = mapped_column(
        SAEnum(
            AIProposalStatus,
            name="ai_proposal_status",
            native_enum=True,
            create_type=True,
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
        default=AIProposalStatus.PENDING,
        server_default=AIProposalStatus.PENDING.value,
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


__all__ = [
    "AIProposalAction",
    "AIProposalStatus",
    "ArticleAIProposal",
]
