"""Domain exceptions for the ``articles`` module."""

from __future__ import annotations

# Names intentionally don't carry the ``Error`` suffix — public contract.
# ruff: noqa: N818


class ArticlesError(Exception):
    """Base class for article-domain errors."""


class ArticleNotFound(ArticlesError):
    """No article matches the given id."""


class ArticleNotEditable(ArticlesError):
    """Actor is not allowed to edit this article (not author, not mod/admin)."""


class MissingEditReason(ArticlesError):
    """Mod/admin edit requires a non-empty ``edit_reason``."""


class ContentInvalid(ArticlesError):
    """Raised when content fails ProseMirror validation."""


class SlugConflict(ArticlesError):
    """Could not allocate a free slug for an article in this topic."""


__all__ = [
    "ArticleNotEditable",
    "ArticleNotFound",
    "ArticlesError",
    "ContentInvalid",
    "MissingEditReason",
    "SlugConflict",
]
