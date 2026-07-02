"""Top-level /api/v1 router with automatic module discovery.

Each subpackage under ``app.modules`` is scanned. If it exposes a
``routes`` submodule with a module-level ``router: APIRouter``, that router
is mounted under ``/api/v1``. This is the *only* coordination point: new
modules don't need to touch any shared file to be wired up.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil

from fastapi import APIRouter

import app.modules as modules_pkg

logger = logging.getLogger(__name__)


def build_api_router() -> APIRouter:
    """Discover module routers under ``app.modules.*.routes`` and aggregate them."""
    api_v1 = APIRouter(prefix="/api/v1")

    for module_info in pkgutil.iter_modules(modules_pkg.__path__):
        if not module_info.ispkg:
            # Modules must be packages (``app/modules/<name>/...``).
            continue

        module_name = module_info.name
        routes_path = f"{modules_pkg.__name__}.{module_name}.routes"

        try:
            routes_module = importlib.import_module(routes_path)
        except ModuleNotFoundError:
            logger.debug("Module '%s' has no `routes` submodule; skipping.", module_name)
            continue
        except Exception:
            logger.exception("Failed to import routes for module '%s'.", module_name)
            raise

        router = getattr(routes_module, "router", None)
        if not isinstance(router, APIRouter):
            logger.warning(
                "Module '%s' exposes a `routes` submodule but no `router: APIRouter` "
                "attribute; skipping.",
                module_name,
            )
            continue

        api_v1.include_router(router)
        logger.info("Mounted router from module '%s'.", module_name)

    return api_v1
