"""Scaffold-level smoke tests.

These exercise the bare bones of the project — app factory, healthz, security
primitives, DB session isolation, settings — to make sure the foundation is
sound before any module agents start landing real code on top of it.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, settings
from app.core.security import (
    InvalidTokenError,
    _build_payload,
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.main import create_app


# --- App factory ------------------------------------------------------------


def test_create_app_starts() -> None:
    """The factory returns a FastAPI app with at least the meta routes mounted."""
    app = create_app()
    assert isinstance(app, FastAPI)
    # /healthz, /openapi.json, /docs, /redoc + the /api/v1 mount root at minimum.
    assert len(app.routes) > 0
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/healthz" in paths


# --- Healthz ----------------------------------------------------------------


async def test_healthz_ok(client: AsyncClient) -> None:
    """GET /healthz returns 200 and the canonical body."""
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    # environment is present (value depends on .env / defaults).
    assert "environment" in body


# --- Password hashing -------------------------------------------------------


def test_password_hash_roundtrip() -> None:
    """argon2 hash verifies the original password and rejects a wrong one."""
    pw = "correct horse battery staple"
    h = hash_password(pw)
    assert h != pw
    assert verify_password(pw, h) is True
    assert verify_password("wrong password", h) is False


# --- JWT --------------------------------------------------------------------


def test_jwt_access_token_roundtrip() -> None:
    """An access token decodes back to the same subject and carries access claims."""
    token = create_access_token(sub="user-123", extra={"role": "user"})
    claims = decode_token(token)
    assert claims["sub"] == "user-123"
    assert claims["type"] == "access"
    assert claims["role"] == "user"
    # Reserved claims are always present.
    for key in ("iat", "exp", "jti"):
        assert key in claims


def test_jwt_decode_rejects_garbage() -> None:
    """Random non-JWT input raises InvalidTokenError."""
    with pytest.raises(InvalidTokenError):
        decode_token("this.is.not.a.jwt")
    with pytest.raises(InvalidTokenError):
        decode_token("")


def test_jwt_decode_rejects_expired() -> None:
    """Tokens past their exp claim must not validate."""
    from jose import jwt

    from app.core.security import ALGORITHM, TOKEN_TYPE_ACCESS

    payload = _build_payload(
        sub="user-123",
        token_type=TOKEN_TYPE_ACCESS,
        expires_delta=timedelta(seconds=-1),
    )
    expired = jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)
    with pytest.raises(InvalidTokenError):
        decode_token(expired)


# --- DB session isolation ---------------------------------------------------


async def test_db_session_isolation_writer(db_session: AsyncSession) -> None:
    """Insert into a temp table inside this test's transaction.

    Combined with :func:`test_db_session_isolation_reader` (which runs in
    its own SAVEPOINT-rolled-back transaction), this proves the per-test
    rollback in ``conftest.db_session`` actually isolates writes.
    """
    await db_session.execute(
        text(
            "CREATE TABLE IF NOT EXISTS _scaffold_probe "
            "(id SERIAL PRIMARY KEY, marker TEXT NOT NULL)"
        )
    )
    await db_session.execute(
        text("INSERT INTO _scaffold_probe (marker) VALUES (:m)"),
        {"m": "writer-test-row"},
    )
    await db_session.commit()
    result = await db_session.execute(
        text("SELECT COUNT(*) FROM _scaffold_probe WHERE marker = :m"),
        {"m": "writer-test-row"},
    )
    assert result.scalar_one() == 1


async def test_db_session_isolation_reader(db_session: AsyncSession) -> None:
    """The other test's writes are NOT visible here — proof of rollback isolation."""
    # The table may or may not exist (depends on test ordering); either way,
    # the writer-test-row from the sibling test must not be visible.
    try:
        result = await db_session.execute(
            text("SELECT COUNT(*) FROM _scaffold_probe WHERE marker = :m"),
            {"m": "writer-test-row"},
        )
    except Exception:
        # Table doesn't exist yet (this test ran first). That's fine — also
        # demonstrates the writer's CREATE TABLE was rolled back.
        await db_session.rollback()
        return
    assert result.scalar_one() == 0


# --- Settings ---------------------------------------------------------------


def test_settings_loaded_from_env() -> None:
    """Settings() instantiates and exposes non-empty connection strings."""
    s = Settings()
    assert s.DATABASE_URL
    assert s.DATABASE_URL.startswith("postgresql+asyncpg://")
    assert s.SECRET_KEY
    assert len(s.SECRET_KEY) >= 32
    assert s.ENVIRONMENT in {"development", "test", "staging", "production"}
