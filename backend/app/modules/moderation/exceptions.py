"""Domain exceptions for the ``moderation`` module."""

from __future__ import annotations

# ruff: noqa: N818


class ModerationError(Exception):
    """Base class for moderation-domain errors."""


class ArticleNotFound(ModerationError):
    """No article matches the given id."""


class UserNotFound(ModerationError):
    """No user matches the given id."""


class InsufficientRole(ModerationError):
    """Actor's role is not allowed to perform the requested moderation action."""


__all__ = [
    "ArticleNotFound",
    "InsufficientRole",
    "ModerationError",
    "UserNotFound",
]
