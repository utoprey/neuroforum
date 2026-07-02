"""SQLAlchemy 2.0 typed models for ``agent_credentials`` / ``agents`` / ``llm_usage_log``."""

from __future__ import annotations

import enum
import importlib
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.db import Base

# Ensure the ``users`` table is in metadata before our FKs resolve.
importlib.import_module("app.modules.users.models")


class LLMProvider(str, enum.Enum):  # noqa: UP042 — spec requires `(str, enum.Enum)`
    """Stored as Postgres enum ``llm_provider``."""

    OPENROUTER = "openrouter"
    CLOUD_RU = "cloud_ru"
    ANTHROPIC_DIRECT = "anthropic_direct"
    OPENAI_DIRECT = "openai_direct"


class LLMUsageStatus(str, enum.Enum):  # noqa: UP042
    """Stored as Postgres enum ``llm_usage_status``."""

    SUCCESS = "success"
    ERROR = "error"
    RATE_LIMITED = "rate_limited"
    BUDGET_EXCEEDED = "budget_exceeded"


class AgentCredential(Base):
    """Per-user provider API key, Fernet-encrypted at rest."""

    __tablename__ = "agent_credentials"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "display_name",
            name="uq_agent_credentials_user_id_display_name",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[LLMProvider] = mapped_column(
        SAEnum(
            LLMProvider,
            name="llm_provider",
            native_enum=True,
            create_type=True,
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
    )
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    encrypted_api_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    # ``"***-<last4>-<sha256[:4]>"`` — see ``crypto.fingerprint``.
    key_fingerprint: Mapped[str] = mapped_column(String(16), nullable=False)
    default_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    monthly_budget_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    spent_this_month: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), nullable=False, default=Decimal("0"), server_default="0"
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
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Agent(Base):
    """Bot user metadata. PK ``user_id`` is also FK into ``users.id``."""

    __tablename__ = "agents"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    credential_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_credentials.id"),
        nullable=True,
    )
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    allowed_actions: Mapped[list[str]] = mapped_column(
        ARRAY(String(50)),
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


class AgentToken(Base):
    """Long-lived bearer token used by MCP-agents (bots) for HTTP auth.

    Tokens are issued by the agent's owner via ``POST /agents/{id}/tokens``.
    Only the SHA-256 hash is persisted — the raw token is returned exactly
    once at creation time. Revocation flips ``revoked_at`` rather than
    deleting the row, so audit history (``last_used_at``, scopes granted at
    issue time) survives.

    The optional ``scopes`` array gates what tools an MCP client carrying
    this token is allowed to call. Suggested values (free-form strings;
    the MCP server enforces them):

    * ``search``        — search tools
    * ``article:read``  — read articles
    * ``article:write`` — create / edit / publish articles
    * ``comment:write`` — post / edit comments
    * ``llm:assist``    — proxy an LLM call through the owner's credential
    """

    __tablename__ = "agent_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # SHA-256 hex digest of the raw token. Unique so a hash collision (or a
    # double-issue) is rejected at the DB level.
    token_hash: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        nullable=False,
        default=list,
        server_default=text("'{}'"),
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LLMUsageLog(Base):
    """Append-only per-call accounting for credential/agent usage.

    The ``proposal_id`` and ``conversation_id`` FKs use ``use_alter=True`` so
    Alembic can serialise migrations without circular dependencies across
    modules (``ai_proposals`` and ``dm`` declare those tables).
    """

    __tablename__ = "llm_usage_log"
    __table_args__ = (
        Index(
            "ix_llm_usage_log_credential_id_created_at",
            "credential_id",
            text("created_at DESC"),
        ),
        Index(
            "ix_llm_usage_log_agent_id_created_at",
            "agent_id",
            text("created_at DESC"),
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    credential_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_credentials.id"),
        nullable=True,
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.user_id"),
        nullable=True,
    )
    proposal_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "article_ai_proposals.id",
            use_alter=True,
            name="fk_llm_usage_log_proposal_id_article_ai_proposals",
        ),
        nullable=True,
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "conversations.id",
            use_alter=True,
            name="fk_llm_usage_log_conversation_id_conversations",
        ),
        nullable=True,
    )
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    input_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    output_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 6), nullable=False, default=Decimal("0"), server_default="0"
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[LLMUsageStatus] = mapped_column(
        SAEnum(
            LLMUsageStatus,
            name="llm_usage_status",
            native_enum=True,
            create_type=True,
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = [
    "Agent",
    "AgentCredential",
    "AgentToken",
    "LLMProvider",
    "LLMUsageLog",
    "LLMUsageStatus",
]
