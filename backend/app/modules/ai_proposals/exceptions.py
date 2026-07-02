"""Domain exceptions for the ``ai_proposals`` module."""

from __future__ import annotations

# Public contract — no ``Error`` suffix.
# ruff: noqa: N818


class AIProposalsError(Exception):
    """Base class for AI proposal errors."""


class ProposalNotFound(AIProposalsError):
    """No proposal matches the given id."""


class ProposalAlreadyDecided(AIProposalsError):
    """Proposal is no longer in ``pending`` and cannot be accepted/rejected."""


class ProposalExpired(AIProposalsError):
    """Proposal's ``expires_at`` is in the past."""


class NotAllowedToPropose(AIProposalsError):
    """Actor lacks permission to create / decide a proposal on this article."""


__all__ = [
    "AIProposalsError",
    "NotAllowedToPropose",
    "ProposalAlreadyDecided",
    "ProposalExpired",
    "ProposalNotFound",
]
