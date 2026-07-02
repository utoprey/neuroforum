"""Touch ``users.last_seen_at`` on each authenticated request.

The middleware peeks at the ``Authorization`` header, decodes the JWT and,
if valid, bumps the user's ``last_seen_at`` timestamp in a dedicated
short-lived session — so the bump never participates in the request's own
transaction (it must succeed or fail independently).

All errors are swallowed: presence tracking is best-effort and must never
break a request.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import UUID

from fastapi import Request, Response
from sqlalchemy import update
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.db import AsyncSessionLocal
from app.core.security import InvalidTokenError, decode_token
from app.modules.users.models import User

log = logging.getLogger(__name__)


class PresenceMiddleware(BaseHTTPMiddleware):
    """Bump ``users.last_seen_at`` whenever a Bearer JWT is presented."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
            if token:
                try:
                    payload = decode_token(token)
                    sub = payload.get("sub")
                    token_type = payload.get("type")
                    if sub and token_type == "access":
                        try:
                            user_id = UUID(str(sub))
                        except (ValueError, TypeError):
                            user_id = None
                        if user_id is not None:
                            try:
                                async with AsyncSessionLocal() as session:
                                    await session.execute(
                                        update(User)
                                        .where(User.id == user_id)
                                        .values(last_seen_at=datetime.now(UTC))
                                    )
                                    await session.commit()
                            except Exception:
                                log.exception(
                                    "Failed to bump last_seen_at for %s", user_id
                                )
                except InvalidTokenError:
                    # Malformed / expired token — leave handler to reject.
                    pass
                except Exception:
                    log.exception("Unexpected error while bumping last_seen_at")
        return await call_next(request)


__all__ = ["PresenceMiddleware"]
