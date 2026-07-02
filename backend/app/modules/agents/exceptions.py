"""Domain exceptions for the ``agents`` module."""

from __future__ import annotations

# Public contract — no ``Error`` suffix.
# ruff: noqa: N818


class AgentsError(Exception):
    """Base class for agent-domain errors."""


class CredentialNotFound(AgentsError):
    """No credential matches the given id."""


class CredentialNameTaken(AgentsError):
    """Same ``(user_id, display_name)`` pair already exists."""


class AgentNotFound(AgentsError):
    """No agent matches the given user id."""


class NotCredentialOwner(AgentsError):
    """Actor does not own the credential (and is not admin)."""


class NotAgentOwner(AgentsError):
    """Actor is not the owner of the agent (and not admin)."""


class BudgetExceeded(AgentsError):
    """Credential has hit its ``monthly_budget_usd`` cap for the current month."""


class AgentTokenNotFound(AgentsError):
    """No agent-token matches the given id."""


class NotAgentTokenOwner(AgentsError):
    """Actor does not own the token's owning agent (and is not admin)."""


__all__ = [
    "AgentNotFound",
    "AgentTokenNotFound",
    "AgentsError",
    "BudgetExceeded",
    "CredentialNameTaken",
    "CredentialNotFound",
    "NotAgentOwner",
    "NotAgentTokenOwner",
    "NotCredentialOwner",
]
