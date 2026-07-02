"""Bot-token authentication for the MCP server.

FastMCP doesn't expose a per-request hook directly, so we authenticate at
the ASGI layer: an ASGI middleware extracts the bearer token from each
HTTP request, looks up the matching :class:`Agent`, and stashes both the
agent and the granted scopes into module-level ``ContextVar`` instances
that the tool implementations read.

This keeps the MCP-side tool signatures clean (no extra "ctx" parameter)
and avoids leaking session/HTTP plumbing into business logic.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar

from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.db import AsyncSessionLocal
from app.modules.agents.models import Agent
from app.modules.agents.repository import AgentRepository
from app.modules.agents.service import AgentService
from app.modules.users.repository import UserRepository

log = logging.getLogger(__name__)


# Populated by :class:`BotTokenAuthMiddleware` on every authenticated request.
# Tools read these via :func:`get_current_agent` / :func:`get_current_scopes`.
current_agent: ContextVar[Agent | None] = ContextVar(
    "current_agent", default=None
)
current_scopes: ContextVar[tuple[str, ...]] = ContextVar(
    "current_scopes", default=()
)
current_raw_token: ContextVar[str | None] = ContextVar(
    "current_raw_token", default=None
)


def _extract_token(headers: list[tuple[bytes, bytes]]) -> str | None:
    """Pull the bot token from ``X-Bot-Token`` or ``Authorization: Bearer …``."""
    for name, value in headers:
        if name.lower() == b"x-bot-token":
            return value.decode("ascii", errors="ignore").strip()
    for name, value in headers:
        if name.lower() == b"authorization":
            raw = value.decode("ascii", errors="ignore").strip()
            if raw.lower().startswith("bearer "):
                return raw[7:].strip()
    return None


async def _send_401(send: Send, message: str) -> None:
    body = f'{{"error":"unauthorized","detail":"{message}"}}'.encode()
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"www-authenticate", b'Bearer realm="neuroforum-mcp"'),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body, "more_body": False})


class BotTokenAuthMiddleware:
    """ASGI middleware that enforces ``X-Bot-Token`` on every HTTP request.

    A request without a valid, non-revoked token is rejected with HTTP 401
    before it reaches the FastMCP app. On success, the agent + scopes are
    pushed onto :data:`current_agent` / :data:`current_scopes` so the tool
    layer can read them without re-authenticating.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if scope["type"] != "http":
            # WebSocket / lifespan: pass through unchanged. The MCP HTTP
            # transport doesn't use WebSockets, but lifespan must work.
            await self._app(scope, receive, send)
            return

        raw_token = _extract_token(scope.get("headers", []))
        if not raw_token:
            await _send_401(send, "Missing X-Bot-Token header")
            return

        async with AsyncSessionLocal() as session:
            svc = AgentService(
                AgentRepository(session),
                UserRepository(session),
                session,
            )
            agent = await svc.authenticate_bot(raw_token)
            scopes = (
                await svc.get_token_scopes(raw_token) if agent is not None else None
            )
            # ``authenticate_bot`` updates ``last_used_at`` — persist it.
            await session.commit()

        if agent is None or scopes is None:
            await _send_401(send, "Invalid or revoked bot token")
            return

        # ``ContextVar.set`` returns a token used to reset on exit; we keep
        # the binding for the duration of this request scope so concurrent
        # requests don't see each other's identity.
        agent_tok = current_agent.set(agent)
        scope_tok = current_scopes.set(tuple(scopes))
        raw_tok = current_raw_token.set(raw_token)
        try:
            await self._app(scope, receive, send)
        finally:
            current_agent.reset(agent_tok)
            current_scopes.reset(scope_tok)
            current_raw_token.reset(raw_tok)


def get_current_agent() -> Agent:
    """Return the agent associated with the current MCP request.

    Raises ``PermissionError`` if called outside an authenticated context.
    Tool implementations call this rather than reading the ContextVar
    directly so we always raise a consistent message.
    """
    agent = current_agent.get()
    if agent is None:  # pragma: no cover — defended in middleware
        raise PermissionError("MCP tool called without authentication")
    return agent


def get_current_scopes() -> list[str]:
    return list(current_scopes.get())


def require_scope(scope: str) -> None:
    """Raise :class:`PermissionError` if the current token lacks ``scope``."""
    scopes = current_scopes.get()
    if scope not in scopes:
        raise PermissionError(
            f"Bot token is missing required scope: {scope!r}. "
            f"Granted scopes: {sorted(scopes)}"
        )


__all__ = [
    "BotTokenAuthMiddleware",
    "current_agent",
    "current_raw_token",
    "current_scopes",
    "get_current_agent",
    "get_current_scopes",
    "require_scope",
]
