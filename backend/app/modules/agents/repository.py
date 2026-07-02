"""Data access for the ``agents`` module."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.agents.models import (
    Agent,
    AgentCredential,
    AgentToken,
    LLMUsageLog,
)
from app.modules.users.models import User


class AgentRepository:
    """Reads + writes for credentials, agents, usage logs."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ----- Credentials ----------------------------------------------------

    async def get_credential(
        self, credential_id: UUID
    ) -> AgentCredential | None:
        stmt = select(AgentCredential).where(AgentCredential.id == credential_id)
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def get_credential_by_name(
        self, user_id: UUID, display_name: str
    ) -> AgentCredential | None:
        stmt = select(AgentCredential).where(
            AgentCredential.user_id == user_id,
            AgentCredential.display_name == display_name,
        )
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def add_credential(
        self, credential: AgentCredential
    ) -> AgentCredential:
        self._db.add(credential)
        await self._db.flush()
        return credential

    async def list_credentials_for_user(
        self, user_id: UUID
    ) -> list[AgentCredential]:
        stmt = (
            select(AgentCredential)
            .where(AgentCredential.user_id == user_id)
            .order_by(desc(AgentCredential.created_at))
        )
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def delete_credential(self, credential: AgentCredential) -> None:
        await self._db.delete(credential)
        await self._db.flush()

    # ----- Agents ---------------------------------------------------------

    async def get_agent(self, user_id: UUID) -> Agent | None:
        stmt = select(Agent).where(Agent.user_id == user_id)
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def get_agent_with_owner(
        self, user_id: UUID
    ) -> tuple[Agent, User] | None:
        stmt = (
            select(Agent, User)
            .join(User, User.id == Agent.owner_user_id)
            .where(Agent.user_id == user_id)
            .options(selectinload(User.profile))
        )
        row = (await self._db.execute(stmt)).first()
        if row is None:
            return None
        return (row[0], row[1])

    async def add_agent(self, agent: Agent) -> Agent:
        self._db.add(agent)
        await self._db.flush()
        return agent

    async def list_agents_for_owner(
        self, owner_user_id: UUID
    ) -> list[Agent]:
        stmt = (
            select(Agent)
            .where(Agent.owner_user_id == owner_user_id)
            .order_by(desc(Agent.created_at))
        )
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    # ----- Agent tokens ---------------------------------------------------

    async def add_token(self, token: AgentToken) -> AgentToken:
        self._db.add(token)
        await self._db.flush()
        return token

    async def get_token(self, token_id: UUID) -> AgentToken | None:
        stmt = select(AgentToken).where(AgentToken.id == token_id)
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def get_token_by_hash(self, token_hash: str) -> AgentToken | None:
        stmt = select(AgentToken).where(AgentToken.token_hash == token_hash)
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def list_tokens_for_agent(
        self, agent_id: UUID
    ) -> list[AgentToken]:
        stmt = (
            select(AgentToken)
            .where(AgentToken.agent_id == agent_id)
            .order_by(desc(AgentToken.created_at))
        )
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    # ----- Usage log ------------------------------------------------------

    async def add_usage(self, entry: LLMUsageLog) -> LLMUsageLog:
        self._db.add(entry)
        await self._db.flush()
        return entry

    async def sum_credential_usage_since(
        self, credential_id: UUID, since: datetime
    ) -> Decimal:
        """Aggregate ``cost_usd`` for one credential since ``since``."""
        stmt = select(
            func.coalesce(func.sum(LLMUsageLog.cost_usd), 0)
        ).where(
            LLMUsageLog.credential_id == credential_id,
            LLMUsageLog.created_at >= since,
        )
        result = await self._db.execute(stmt)
        return Decimal(result.scalar_one() or 0)


__all__ = ["AgentRepository"]
