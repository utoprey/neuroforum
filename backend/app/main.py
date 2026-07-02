"""FastAPI application factory."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.v1.router import build_api_router
from app.core.config import settings
from app.core.presence import PresenceMiddleware
from app.core.ratelimit import limiter

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Build and configure the FastAPI application.

    Kept as a factory so tests can spin up isolated instances with overridden
    dependencies (e.g. test DB session).
    """
    app = FastAPI(
        title="Forum API",
        version="0.1.0",
        default_response_class=ORJSONResponse,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # CORS — frontend dev server on localhost:3000 by default; extra
    # origins (e.g., the public VPS URL) from CORS_ORIGINS env (csv).
    import os
    _extra = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", *_extra],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Wire slowapi. Exception handler returns a proper JSON 429 instead of
    # slowapi's default plaintext. Middleware must be added before routers.
    app.state.limiter = limiter
    app.add_exception_handler(
        RateLimitExceeded, _rate_limit_exceeded_handler  # type: ignore[arg-type]
    )

    # Presence — bump ``users.last_seen_at`` on each authed request.
    app.add_middleware(PresenceMiddleware)

    # Liveness probe. Keep cheap; do not touch DB here.
    @app.get("/healthz", tags=["meta"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "environment": settings.ENVIRONMENT}

    # Auto-discover module routers under /api/v1.
    app.include_router(build_api_router())

    return app


app = create_app()
