"""Domain exceptions for the ``messages`` module."""

from __future__ import annotations

# Names intentionally don't carry the ``Error`` suffix — public contract
# mirroring ``articles`` / ``forum``.
# ruff: noqa: N818


class MessagesError(Exception):
    """Base class for message-domain errors."""


class MessageNotFound(MessagesError):
    """No message matches the given id."""


class ArticleNotPostable(MessagesError):
    """Parent article does not exist or is not in ``published`` state."""


class ParentNotInSameArticle(MessagesError):
    """``parent_id`` refers to a message that lives in a different article."""


class MaxDepthExceeded(MessagesError):
    """The resulting message would exceed the ``depth <= 8`` thread limit."""


class ReplyTargetNotFound(MessagesError):
    """``reply_to_selection.target`` points at a non-existent row."""


class MissingEditReason(MessagesError):
    """Mod/admin edit requires a non-empty ``edit_reason``."""


class NotEditable(MessagesError):
    """Message is in a state (deleted/hidden) that cannot be edited."""


__all__ = [
    "ArticleNotPostable",
    "MaxDepthExceeded",
    "MessageNotFound",
    "MessagesError",
    "MissingEditReason",
    "NotEditable",
    "ParentNotInSameArticle",
    "ReplyTargetNotFound",
]
