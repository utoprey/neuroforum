"""Domain exceptions for the ``dm`` module."""

from __future__ import annotations

# Public contract — no ``Error`` suffix on these names.
# ruff: noqa: N818


class DMError(Exception):
    """Base class for direct-messaging errors."""


class ConversationNotFound(DMError):
    """No conversation matches the given id."""


class NotParticipant(DMError):
    """Actor is not a participant of the conversation."""


class CannotDmYourself(DMError):
    """Attempt to open a DM with one's own user id."""


class DirectMessageNotFound(DMError):
    """No direct message matches the given id."""


class NotEditable(DMError):
    """Message is in a state (deleted) that cannot be edited."""


__all__ = [
    "CannotDmYourself",
    "ConversationNotFound",
    "DMError",
    "DirectMessageNotFound",
    "NotEditable",
    "NotParticipant",
]
