"""Domain exceptions for the ``content`` module."""

from __future__ import annotations


class ContentValidationError(ValueError):
    """Raised when a raw content document fails Pydantic validation.

    Wraps the underlying ``pydantic.ValidationError`` so that the service
    layer can translate it into a single, predictable HTTP 422 without
    leaking Pydantic internals.
    """
