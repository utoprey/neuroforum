"""Domain exceptions for ``rbac``."""

from __future__ import annotations

# Names intentionally don't carry the ``Error`` suffix — the task spec
# fixes them as part of the public service-layer contract.
# ruff: noqa: N818


class RbacError(Exception):
    """Base class for rbac-domain errors."""


class InsufficientRole(RbacError):
    """Actor's role is not allowed to perform the requested action."""


class AlreadyBanned(RbacError):
    """An active ban already exists for the same user + scope + target."""


class BanNotFound(RbacError):
    """Ban ID does not match any existing row."""


class CannotBanAdmin(RbacError):
    """Moderators may not ban admins or other moderators; admins may not ban other admins."""
