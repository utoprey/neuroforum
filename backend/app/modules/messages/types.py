"""SQLAlchemy ``UserDefinedType`` for Postgres ``LTREE``.

Postgres ships ``LTREE`` via the ``ltree`` extension (created up-front by
``users.models`` via ``before_create`` DDL hooks and in production by the
first Alembic migration). SQLAlchemy has no built-in mapping, so we expose
a thin :class:`Ltree` type that round-trips the path as a plain ``str`` —
which is what asyncpg already returns for ``ltree`` columns.

Subtree queries (``path <@ ltree`` etc.) are still done via
``sqlalchemy.text()`` with bind parameters, because the operators
themselves are Postgres-specific.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.types import UserDefinedType


class Ltree(UserDefinedType[str]):
    """Round-trip a Postgres ``LTREE`` as a plain ``str`` path."""

    cache_ok = True

    def get_col_spec(self, **kw: Any) -> str:
        _ = kw
        return "LTREE"

    def bind_processor(self, dialect: Any) -> Any:
        _ = dialect

        def process(value: str | None) -> str | None:
            return value

        return process

    def result_processor(self, dialect: Any, coltype: Any) -> Any:
        _ = (dialect, coltype)

        def process(value: str | None) -> str | None:
            return value

        return process


__all__ = ["Ltree"]
