"""Pydantic v2 schemas for the ``agents`` module."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.modules.agents.models import LLMProvider, LLMUsageStatus
from app.modules.users.schemas import UserPublic

# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


class AgentCredentialCreate(BaseModel):
    """Body of ``POST /agents/credentials``."""

    model_config = ConfigDict(extra="forbid")

    provider: LLMProvider
    display_name: str = Field(min_length=1, max_length=100)
    api_key: SecretStr = Field(min_length=1)
    default_model: str | None = Field(default=None, max_length=100)
    monthly_budget_usd: Decimal | None = Field(default=None, ge=0)


class AgentCredentialUpdate(BaseModel):
    """Body of ``PATCH /agents/credentials/{id}``. Any field optional.

    Providing ``api_key`` rotates the stored ciphertext + fingerprint.
    """

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    api_key: SecretStr | None = None
    default_model: str | None = Field(default=None, max_length=100)
    monthly_budget_usd: Decimal | None = Field(default=None, ge=0)
    is_active: bool | None = None


class AgentCredentialRead(BaseModel):
    """Wire shape — NEVER includes ``encrypted_api_key`` or plaintext."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    provider: LLMProvider
    display_name: str
    key_fingerprint: str
    default_model: str | None = None
    is_active: bool
    monthly_budget_usd: Decimal | None = None
    spent_this_month: Decimal
    created_at: datetime
    last_used_at: datetime | None = None


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------


class AgentCreate(BaseModel):
    """Body of ``POST /agents``. Creates a bot user + agent record."""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=3, max_length=50)
    display_name: str | None = Field(default=None, max_length=100)
    credential_id: UUID
    system_prompt: str | None = None
    allowed_actions: list[str] = Field(default_factory=list)


class AgentRead(BaseModel):
    """Wire shape for an agent (bot user + agent metadata)."""

    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    username: str
    display_name: str | None = None
    owner: UserPublic
    credential: AgentCredentialRead | None = None
    system_prompt: str | None = None
    allowed_actions: list[str] = Field(default_factory=list)
    created_at: datetime


# ---------------------------------------------------------------------------
# Agent tokens (bot bearer tokens)
# ---------------------------------------------------------------------------


class AgentTokenCreate(BaseModel):
    """Body of ``POST /agents/{agent_id}/tokens``."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    # Free-form strings — the MCP server interprets them. Typical values:
    # ``search``, ``article:read``, ``article:write``, ``comment:write``,
    # ``llm:assist``.
    scopes: list[str] = Field(default_factory=list)


class AgentTokenRead(BaseModel):
    """Wire shape — NEVER includes the raw token."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent_id: UUID
    name: str
    scopes: list[str] = Field(default_factory=list)
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime


class AgentTokenCreated(AgentTokenRead):
    """Response returned only by the create endpoint.

    Includes ``raw_token`` — shown to the user exactly ONCE. After this
    response is dropped, only the hash exists on disk and the secret is
    unrecoverable.
    """

    raw_token: str


# ---------------------------------------------------------------------------
# Usage log
# ---------------------------------------------------------------------------


class LLMUsageLogRead(BaseModel):
    """Read shape of a single accounting row."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    credential_id: UUID | None = None
    agent_id: UUID | None = None
    proposal_id: UUID | None = None
    conversation_id: UUID | None = None
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    duration_ms: int | None = None
    status: LLMUsageStatus
    error_message: str | None = None
    created_at: datetime


__all__ = [
    "AgentCreate",
    "AgentCredentialCreate",
    "AgentCredentialRead",
    "AgentCredentialUpdate",
    "AgentRead",
    "AgentTokenCreate",
    "AgentTokenCreated",
    "AgentTokenRead",
    "LLMUsageLogRead",
]
