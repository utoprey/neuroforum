"""Domain exceptions for the ``saved`` module."""

from __future__ import annotations

# ruff: noqa: N818


class SavedError(Exception):
    """Base class for saved-domain errors."""


class ArticleNotFound(SavedError):
    """No article matches the given id."""


__all__ = ["ArticleNotFound", "SavedError"]
