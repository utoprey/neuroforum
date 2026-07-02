"""Alembic environment — async, with autodiscovery of module model packages."""

from __future__ import annotations

import asyncio
import importlib
import logging
import pkgutil
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

import app.modules as modules_pkg
from alembic import context
from app.core.config import settings
from app.core.db import Base

# Alembic Config object provides access to .ini values.
config = context.config

# Inject the runtime DB URL from settings so we never hardcode credentials.
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

logger = logging.getLogger("alembic.env")


def _discover_module_models() -> None:
    """Import ``app.modules.<name>.models`` for every module package.

    Each module is responsible for ensuring that importing its ``models``
    package registers all of its ORM classes on :data:`Base.metadata`
    (typically by re-exporting them from ``models/__init__.py``).
    """
    for module_info in pkgutil.iter_modules(modules_pkg.__path__):
        if not module_info.ispkg:
            continue
        models_path = f"{modules_pkg.__name__}.{module_info.name}.models"
        try:
            importlib.import_module(models_path)
            logger.info("Loaded models from %s", models_path)
        except ModuleNotFoundError:
            logger.debug("Module '%s' has no `models` package; skipping.", module_info.name)
        except Exception:
            logger.exception("Failed to import models for module '%s'.", module_info.name)
            raise


_discover_module_models()

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live DB connection."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations against a live async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
