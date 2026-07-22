"""Shared pytest fixtures: ephemeral Postgres via testcontainers + FastAPI app/client.

We deliberately bypass Alembic in tests by default and call
``Base.metadata.create_all`` for speed. Set ``TESTS_USE_ALEMBIC=1`` to run
the production migrations instead — used by tests that need GENERATED
columns / GIN-trgm indexes / etc. See CLAUDE.md > Conventions.
"""

# ruff: noqa: E402  -- env setup must happen before app.* imports

from __future__ import annotations

import importlib
import logging
import os
import pkgutil
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

_COLIMA_SOCK = Path.home() / ".colima/default/docker.sock"
if _COLIMA_SOCK.exists():
    os.environ.setdefault("DOCKER_HOST", f"unix://{_COLIMA_SOCK}")
    os.environ.setdefault("TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE", "/var/run/docker.sock")

# Disable the slowapi rate limiter globally for the test run — the whole
# suite shares one client host and would otherwise trip the 3/min register
# limit within the first handful of tests. This must happen BEFORE the
# ``app.core.ratelimit`` module is first imported (it evaluates the env
# at module init).
os.environ.setdefault("RATELIMIT_ENABLED", "0")

# Belt-and-suspenders: some other module may have already imported
# ``app.core.ratelimit`` before this env var got set (pytest collection can
# import our test modules in either order). Force the flag off directly.
try:
    from app.core.ratelimit import limiter as _limiter
    _limiter.enabled = False
except ImportError:  # pragma: no cover — during initial bootstrap
    pass

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.postgres import PostgresContainer

import app.modules as _modules_pkg
from app.core.db import Base, get_session
from app.main import create_app

_logger = logging.getLogger(__name__)


def _discover_module_models() -> None:
    """Import ``app.modules.<name>.models`` so ORM classes register on Base.metadata.

    Mirrors the same autodiscovery logic used in ``backend/alembic/env.py``.
    Without this, ``Base.metadata.create_all`` in the ``engine`` fixture would
    produce an empty schema (since model modules would never be imported).
    """
    for module_info in pkgutil.iter_modules(_modules_pkg.__path__):
        if not module_info.ispkg:
            continue
        models_path = f"{_modules_pkg.__name__}.{module_info.name}.models"
        try:
            importlib.import_module(models_path)
        except ModuleNotFoundError:
            _logger.debug("Module '%s' has no `models` package; skipping.", module_info.name)
        except Exception:
            _logger.exception("Failed to import models for module '%s'.", module_info.name)
            raise


def _to_asyncpg_url(url: str) -> str:
    """Rewrite the sync URL produced by testcontainers to the asyncpg driver."""
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql+psycopg2://"):
        return "postgresql+asyncpg://" + url[len("postgresql+psycopg2://") :]
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://") :]
    raise ValueError(f"Unexpected Postgres URL scheme: {url!r}")


# --- Container --------------------------------------------------------------


@pytest.fixture(scope="session")
def postgres_container() -> Iterator[PostgresContainer]:
    """Spin up a single Postgres container for the whole test session."""
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


# --- Engine + schema --------------------------------------------------------


def _use_alembic() -> bool:
    """Whether to run real Alembic migrations to build the test schema.

    Off by default (set ``TESTS_USE_ALEMBIC=1`` to flip on) because alembic
    is several seconds slower than ``create_all`` and exercises code paths
    irrelevant to most service-layer tests.
    """
    return os.environ.get("TESTS_USE_ALEMBIC", "").lower() in {"1", "true", "yes"}


def _run_alembic_upgrade(url: str) -> None:
    """Run ``alembic upgrade head`` against ``url`` in a clean subprocess.

    Alembic's ``env.py`` calls ``asyncio.run()`` to bootstrap an async
    engine for the migration. Doing this from inside our pytest-asyncio
    event loop blows up with ``RuntimeError: asyncio.run() cannot be
    called from a running event loop`` — so we delegate to a child
    process where alembic owns the loop.
    """
    import subprocess
    import sys

    repo_root = Path(__file__).resolve().parents[2]
    ini_path = repo_root / "backend" / "alembic.ini"

    env = os.environ.copy()
    env["DATABASE_URL"] = url

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            str(ini_path),
            "upgrade",
            "head",
        ],
        env=env,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"alembic upgrade head failed:\nstdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )


@pytest_asyncio.fixture(scope="session")
async def engine(postgres_container: PostgresContainer) -> AsyncIterator[AsyncEngine]:
    """Async engine bound to the test container, with schema created up-front."""
    url = _to_asyncpg_url(postgres_container.get_connection_url())

    # Must happen BEFORE schema creation — otherwise model modules are never
    # imported and Base.metadata is empty (matters for create_all only).
    _discover_module_models()

    if _use_alembic():
        _logger.info("Building test schema via Alembic (TESTS_USE_ALEMBIC=1).")
        _run_alembic_upgrade(url)
        engine = create_async_engine(url, echo=False, pool_pre_ping=True, future=True)
    else:
        engine = create_async_engine(url, echo=False, pool_pre_ping=True, future=True)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    try:
        yield engine
    finally:
        if _use_alembic():
            # downgrade base is unreliable when other test sessions or
            # leftover objects exist; testcontainers will reap the container
            # on session exit anyway, so just dispose the engine.
            pass
        else:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()


# --- Per-test session in a SAVEPOINT ---------------------------------------


@pytest_asyncio.fixture
async def db_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Yield an AsyncSession bound to a connection inside an outer transaction.

    Uses the classic "join an external transaction" pattern so the entire
    test (including any inner ``session.commit()`` calls) rolls back at the
    end, leaving the DB pristine for the next test.
    """
    connection: AsyncConnection = await engine.connect()
    trans = await connection.begin()

    session_factory = async_sessionmaker(
        bind=connection,
        expire_on_commit=False,
        class_=AsyncSession,
        join_transaction_mode="create_savepoint",
    )
    session = session_factory()

    try:
        yield session
    finally:
        await session.close()
        if trans.is_active:
            await trans.rollback()
        await connection.close()


# --- App + HTTP client ------------------------------------------------------


@pytest_asyncio.fixture
async def app(db_session: AsyncSession) -> AsyncIterator[FastAPI]:
    """FastAPI app with ``get_session`` overridden to return the test session."""
    application = create_app()

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    application.dependency_overrides[get_session] = _override_get_session

    async with LifespanManager(application):
        yield application

    application.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Async HTTP client wired to the in-process ASGI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
