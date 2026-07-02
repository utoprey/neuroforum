"""Domain exceptions for the ``forum`` module."""

from __future__ import annotations

# Names intentionally don't carry the ``Error`` suffix — they form the
# public service-layer contract that downstream modules and route
# handlers import by name.
# ruff: noqa: N818


class ForumError(Exception):
    """Base class for forum-domain errors."""


class SectionNotFound(ForumError):
    """No section matches the given slug / id."""


class TopicNotFound(ForumError):
    """No topic matches the given slug / id."""


class SlugConflict(ForumError):
    """A slug collides with an existing one in the same parent scope."""


class TopicLocked(ForumError):
    """Tried to act on a topic whose ``is_locked=True``."""


class InsufficientRole(ForumError):
    """Actor's role is not authorised for the requested forum action."""


__all__ = [
    "ForumError",
    "InsufficientRole",
    "SectionNotFound",
    "SlugConflict",
    "TopicLocked",
    "TopicNotFound",
]
