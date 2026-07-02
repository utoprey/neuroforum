"""Domain exceptions for the ``embeds`` module."""

from __future__ import annotations

# Public domain contract: names intentionally omit the ``Error`` suffix.
# ruff: noqa: N818


class EmbedsError(Exception):
    """Base class for embed-domain errors."""


class UnsupportedProvider(EmbedsError):
    """URL doesn't match any provider in the whitelist."""


class EmbedFetchFailed(EmbedsError):
    """Provider matched but resolving the URL failed (network, parse, …)."""


__all__ = ["EmbedFetchFailed", "EmbedsError", "UnsupportedProvider"]
