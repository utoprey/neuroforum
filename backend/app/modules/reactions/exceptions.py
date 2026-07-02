"""Domain exceptions for the ``reactions`` module."""

from __future__ import annotations

# Names intentionally don't carry the ``Error`` suffix.
# ruff: noqa: N818


class ReactionsError(Exception):
    """Base class for reaction-domain errors."""


class ArticleNotFound(ReactionsError):
    """No article matches the given id."""


class MessageNotFound(ReactionsError):
    """No message matches the given id."""


__all__ = ["ArticleNotFound", "MessageNotFound", "ReactionsError"]
