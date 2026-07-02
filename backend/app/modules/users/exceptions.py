"""Domain exceptions for the ``users`` module."""

from __future__ import annotations

# Names intentionally don't carry the ``Error`` suffix — the task spec
# fixes them as part of the public service-layer contract (see CLAUDE.md
# > "module: users"). Module agents downstream import these by exact name.
# ruff: noqa: N818


class UsersError(Exception):
    """Base class for user-domain errors."""


class UserNotFound(UsersError):
    """Lookup by id/username/email returned nothing."""


class UsernameTaken(UsersError):
    """Tried to create a user whose ``username`` is already used."""


class EmailTaken(UsersError):
    """Tried to create a user whose ``email`` is already used."""


class InvalidORCID(UsersError):
    """ORCID string did not match the canonical pattern."""
