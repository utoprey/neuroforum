"""Service layer for the ``agents`` module."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.modules.agents import crypto
from app.modules.agents.exceptions import (
    AgentNotFound,
    AgentTokenNotFound,
    CredentialNameTaken,
    CredentialNotFound,
    NotAgentOwner,
    NotAgentTokenOwner,
    NotCredentialOwner,
)
from app.modules.agents.models import (
    Agent,
    AgentCredential,
    AgentToken,
    LLMUsageLog,
    LLMUsageStatus,
)
from app.modules.agents.repository import AgentRepository
from app.modules.agents.schemas import (
    AgentCreate,
    AgentCredentialCreate,
    AgentCredentialUpdate,
)
from app.modules.users.exceptions import UsernameTaken
from app.modules.users.models import Role, User, UserProfile, UserStats
from app.modules.users.repository import UserRepository


def _hash_token(raw_token: str) -> str:
    """SHA-256 hex digest used as the stored ``token_hash``."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


class AgentService:
    """BYO-key LLM credential + bot-user lifecycle orchestration."""

    def __init__(
        self,
        repo: AgentRepository,
        user_repo: UserRepository,
        db: AsyncSession,
    ) -> None:
        self._repo = repo
        self._users = user_repo
        self._db = db

    # ------------------------------------------------------------------
    # Credentials
    # ------------------------------------------------------------------

    async def create_credential(
        self, actor: User, payload: AgentCredentialCreate
    ) -> AgentCredential:
        api_key = payload.api_key.get_secret_value()
        existing = await self._repo.get_credential_by_name(
            actor.id, payload.display_name
        )
        if existing is not None:
            raise CredentialNameTaken(payload.display_name)

        credential = AgentCredential(
            user_id=actor.id,
            provider=payload.provider,
            display_name=payload.display_name,
            encrypted_api_key=crypto.encrypt(api_key),
            key_fingerprint=crypto.fingerprint(api_key),
            default_model=payload.default_model,
            monthly_budget_usd=payload.monthly_budget_usd,
            is_active=True,
            spent_this_month=Decimal("0"),
        )
        await self._repo.add_credential(credential)
        await self._db.refresh(
            credential, attribute_names=("created_at", "updated_at")
        )
        return credential

    async def list_my_credentials(self, actor: User) -> list[AgentCredential]:
        return await self._repo.list_credentials_for_user(actor.id)

    async def get_credential(
        self, actor: User, credential_id: UUID
    ) -> AgentCredential:
        credential = await self._repo.get_credential(credential_id)
        if credential is None:
            raise CredentialNotFound(str(credential_id))
        if credential.user_id != actor.id and actor.role != Role.ADMIN:
            raise NotCredentialOwner(str(credential_id))
        return credential

    async def update_credential(
        self,
        actor: User,
        credential_id: UUID,
        payload: AgentCredentialUpdate,
    ) -> AgentCredential:
        credential = await self.get_credential(actor, credential_id)

        if payload.display_name is not None and payload.display_name != credential.display_name:
            clash = await self._repo.get_credential_by_name(
                credential.user_id, payload.display_name
            )
            if clash is not None and clash.id != credential.id:
                raise CredentialNameTaken(payload.display_name)
            credential.display_name = payload.display_name
        if payload.api_key is not None:
            new_key = payload.api_key.get_secret_value()
            credential.encrypted_api_key = crypto.encrypt(new_key)
            credential.key_fingerprint = crypto.fingerprint(new_key)
        if payload.default_model is not None:
            credential.default_model = payload.default_model
        if payload.monthly_budget_usd is not None:
            credential.monthly_budget_usd = payload.monthly_budget_usd
        if payload.is_active is not None:
            credential.is_active = payload.is_active

        await self._db.flush()
        await self._db.refresh(credential, attribute_names=("updated_at",))
        return credential

    async def delete_credential(
        self, actor: User, credential_id: UUID
    ) -> None:
        credential = await self.get_credential(actor, credential_id)
        await self._repo.delete_credential(credential)

    def decrypt_api_key(self, credential: AgentCredential) -> str:
        """Internal: return the plaintext API key for worker use only."""
        return crypto.decrypt(credential.encrypted_api_key)

    # ------------------------------------------------------------------
    # Agents (bot users)
    # ------------------------------------------------------------------

    async def create_agent(
        self, actor: User, payload: AgentCreate
    ) -> tuple[Agent, User, User]:
        """Create a bot user (role='agent') + ``Agent`` record.

        Returns ``(agent, bot_user, owner)`` so the route layer can render
        an :class:`AgentRead` without re-querying.
        """
        credential = await self.get_credential(actor, payload.credential_id)
        if credential.user_id != actor.id:
            # Admin can read other people's credentials, but they can't
            # attach them to their own agent.
            raise NotCredentialOwner(str(credential.id))

        # Username uniqueness — re-uses the User table's UNIQUE constraint.
        existing = await self._users.get_by_username(payload.username)
        if existing is not None:
            raise UsernameTaken(payload.username)

        bot_user = User(
            id=uuid4(),
            username=payload.username,
            email=None,
            password_hash=None,
            role=Role.AGENT,
            is_active=True,
        )
        profile = UserProfile(display_name=payload.display_name)
        stats = UserStats()
        await self._users.create(bot_user, profile, stats)

        agent = Agent(
            user_id=bot_user.id,
            owner_user_id=actor.id,
            credential_id=credential.id,
            system_prompt=payload.system_prompt,
            allowed_actions=list(payload.allowed_actions or []),
        )
        await self._repo.add_agent(agent)
        await self._db.refresh(
            agent, attribute_names=("created_at", "updated_at")
        )
        # Re-fetch via repo so the ``profile`` / ``stats`` relationships are
        # eager-loaded — otherwise the route's ``UserPublic`` serialization
        # triggers a lazy load in async context → MissingGreenlet.
        loaded_bot = await self._users.get(bot_user.id)
        assert loaded_bot is not None  # we literally just inserted it
        # ``bot_user`` is the new agent's identity; ``actor`` is the owner.
        return (agent, loaded_bot, actor)

    async def list_my_agents(
        self, actor: User
    ) -> list[tuple[Agent, User, User, AgentCredential | None]]:
        """Return ``(agent, bot_user, owner, credential)`` for each of my agents."""
        agents = await self._repo.list_agents_for_owner(actor.id)
        out: list[tuple[Agent, User, User, AgentCredential | None]] = []
        for agent in agents:
            bot_user = await self._users.get(agent.user_id)
            assert bot_user is not None  # FK guarantees this
            credential = (
                await self._repo.get_credential(agent.credential_id)
                if agent.credential_id is not None
                else None
            )
            out.append((agent, bot_user, actor, credential))
        return out

    async def get_agent(
        self, actor: User, agent_user_id: UUID
    ) -> tuple[Agent, User, User, AgentCredential | None]:
        agent_row = await self._repo.get_agent_with_owner(agent_user_id)
        if agent_row is None:
            raise AgentNotFound(str(agent_user_id))
        agent, owner = agent_row
        if owner.id != actor.id and actor.role != Role.ADMIN:
            raise NotAgentOwner(str(agent_user_id))
        bot_user = await self._users.get(agent.user_id)
        assert bot_user is not None
        credential = (
            await self._repo.get_credential(agent.credential_id)
            if agent.credential_id is not None
            else None
        )
        return (agent, bot_user, owner, credential)

    async def delete_agent(self, actor: User, agent_user_id: UUID) -> None:
        agent_row = await self._repo.get_agent_with_owner(agent_user_id)
        if agent_row is None:
            raise AgentNotFound(str(agent_user_id))
        agent, owner = agent_row
        if owner.id != actor.id and actor.role != Role.ADMIN:
            raise NotAgentOwner(str(agent_user_id))
        # Soft delete the bot user — keep the Agent row for audit.
        bot_user = await self._users.get(agent.user_id)
        if bot_user is not None:
            bot_user.is_active = False
            await self._db.flush()

    # ------------------------------------------------------------------
    # Agent tokens (bot bearer tokens)
    # ------------------------------------------------------------------

    async def create_agent_token(
        self,
        actor: User,
        agent_id: UUID,
        name: str,
        scopes: list[str],
    ) -> tuple[AgentToken, str]:
        """Mint a new bearer token for ``agent_id``.

        Returns ``(model, raw_token)``. The raw token is shown to the
        caller exactly once; only the SHA-256 hash hits the database.

        Permission: actor must be the agent's owner or an admin.
        """
        agent_row = await self._repo.get_agent_with_owner(agent_id)
        if agent_row is None:
            raise AgentNotFound(str(agent_id))
        _agent, owner = agent_row
        if owner.id != actor.id and actor.role != Role.ADMIN:
            raise NotAgentOwner(str(agent_id))

        # 40 url-safe base64 chars ≈ 240 bits of entropy. ``secrets`` is
        # safe for credentials.
        raw_token = secrets.token_urlsafe(40)
        token_hash = _hash_token(raw_token)

        token = AgentToken(
            agent_id=agent_id,
            token_hash=token_hash,
            name=name,
            scopes=list(scopes or []),
        )
        await self._repo.add_token(token)
        await self._db.refresh(token, attribute_names=("created_at",))
        return (token, raw_token)

    async def list_agent_tokens(
        self, actor: User, agent_id: UUID
    ) -> list[AgentToken]:
        """List tokens for ``agent_id`` (owner or admin only)."""
        agent_row = await self._repo.get_agent_with_owner(agent_id)
        if agent_row is None:
            raise AgentNotFound(str(agent_id))
        _agent, owner = agent_row
        if owner.id != actor.id and actor.role != Role.ADMIN:
            raise NotAgentOwner(str(agent_id))
        return await self._repo.list_tokens_for_agent(agent_id)

    async def revoke_agent_token(self, actor: User, token_id: UUID) -> None:
        """Mark a token as revoked (set ``revoked_at``).

        Permission: owner of the token's agent or admin. Revoking an
        already-revoked token is an idempotent no-op.
        """
        token = await self._repo.get_token(token_id)
        if token is None:
            raise AgentTokenNotFound(str(token_id))
        agent_row = await self._repo.get_agent_with_owner(token.agent_id)
        if agent_row is None:
            # FK should prevent this, but be defensive.
            raise AgentNotFound(str(token.agent_id))
        _agent, owner = agent_row
        if owner.id != actor.id and actor.role != Role.ADMIN:
            raise NotAgentTokenOwner(str(token_id))
        if token.revoked_at is not None:
            return
        token.revoked_at = datetime.now(UTC)
        await self._db.flush()

    async def authenticate_bot(self, raw_token: str) -> Agent | None:
        """Look up an agent by a raw bearer token.

        Returns the matching :class:`Agent` row (with ``last_used_at``
        bumped on the token), or ``None`` if no live token matches.

        Token must NOT be revoked.
        """
        if not raw_token:
            return None
        token_hash = _hash_token(raw_token)
        token = await self._repo.get_token_by_hash(token_hash)
        if token is None or token.revoked_at is not None:
            return None
        agent = await self._repo.get_agent(token.agent_id)
        if agent is None:
            return None
        # Update the timestamp using the server clock so the bump is
        # observable inside the same outer transaction in tests.
        token.last_used_at = (
            await self._db.execute(select(func.clock_timestamp()))
        ).scalar_one()
        await self._db.flush()
        return agent

    async def get_token_scopes(self, raw_token: str) -> list[str] | None:
        """Return the scopes granted to ``raw_token``, or ``None`` if invalid.

        Convenience wrapper for the MCP server's scope-check middleware.
        Does not bump ``last_used_at`` (callers should already have called
        :meth:`authenticate_bot` for that).
        """
        token_hash = _hash_token(raw_token)
        token = await self._repo.get_token_by_hash(token_hash)
        if token is None or token.revoked_at is not None:
            return None
        return list(token.scopes or [])

    # ------------------------------------------------------------------
    # Usage accounting
    # ------------------------------------------------------------------

    async def log_usage(
        self,
        *,
        credential_id: UUID | None,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost: Decimal,
        status: LLMUsageStatus,
        agent_id: UUID | None = None,
        proposal_id: UUID | None = None,
        conversation_id: UUID | None = None,
        duration_ms: int | None = None,
        error: str | None = None,
    ) -> LLMUsageLog:
        entry = LLMUsageLog(
            credential_id=credential_id,
            agent_id=agent_id,
            proposal_id=proposal_id,
            conversation_id=conversation_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            duration_ms=duration_ms,
            status=status,
            error_message=error,
        )
        await self._repo.add_usage(entry)

        if credential_id is not None and cost > 0:
            credential = await self._repo.get_credential(credential_id)
            if credential is not None:
                credential.spent_this_month = (
                    Decimal(credential.spent_this_month or 0) + cost
                )
                # Use server clock so the test observes a fresh stamp even
                # when the call sits inside the same transaction.
                credential.last_used_at = (
                    await self._db.execute(select(func.clock_timestamp()))
                ).scalar_one()
                await self._db.flush()
        return entry

    async def get_monthly_usage(
        self, credential_id: UUID
    ) -> dict[str, Decimal]:
        """Sum cost for the current calendar month for one credential."""
        now = datetime.now(UTC)
        month_start = now.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        total = await self._repo.sum_credential_usage_since(
            credential_id, month_start
        )
        return {"month_start": month_start, "cost_usd": total}  # type: ignore[dict-item]


__all__ = ["AgentService"]
