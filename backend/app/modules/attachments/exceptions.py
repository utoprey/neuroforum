"""Domain exceptions for the ``attachments`` module."""

from __future__ import annotations

# Public domain contract: names intentionally omit the ``Error`` suffix.
# ruff: noqa: N818


class AttachmentsError(Exception):
    """Base class for attachment-domain errors."""


class AttachmentNotFound(AttachmentsError):
    """No attachment matches the given id."""


class SizeLimitExceeded(AttachmentsError):
    """Request body exceeds the per-kind size limit."""


class MimeTypeNotAllowed(AttachmentsError):
    """The declared MIME type is not in the per-kind whitelist."""


class NotUploaded(AttachmentsError):
    """Tried to finalize an attachment whose blob is missing from MinIO."""


__all__ = [
    "AttachmentNotFound",
    "AttachmentsError",
    "MimeTypeNotAllowed",
    "NotUploaded",
    "SizeLimitExceeded",
]
