"""Domain exceptions for the ``imports`` module."""

from __future__ import annotations

# Public domain contract: names intentionally omit the ``Error`` suffix.
# ruff: noqa: N818
from uuid import UUID


class ImportsError(Exception):
    """Base class for import-domain errors."""


class InvalidArxivId(ImportsError):
    """The supplied string didn't parse as an arXiv id or URL."""


class ArxivNotFound(ImportsError):
    """The arXiv API returned an empty result for the given id."""


class ArxivFetchFailed(ImportsError):
    """Network / parse error talking to the arXiv export endpoint."""


class DuplicateImport(ImportsError):
    """The (source, external_id) pair is already imported."""

    def __init__(self, message: str, *, article_id: UUID | None = None) -> None:
        super().__init__(message)
        self.article_id = article_id


__all__ = [
    "ArxivFetchFailed",
    "ArxivNotFound",
    "DuplicateImport",
    "ImportsError",
    "InvalidArxivId",
]
