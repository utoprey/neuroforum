"""FastMCP application factory for the Neuroforum MCP server."""

from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP

from app.mcp_server.auth import BotTokenAuthMiddleware
from app.mcp_server.tools import register_tools

log = logging.getLogger(__name__)


INSTRUCTIONS = """\
Neuroforum MCP server.

Tools let LLM agents read and write content in a neuroscience-focused
discussion forum.

Authentication
--------------
Every request must carry a bot token as either:
  * ``X-Bot-Token: <token>``  (preferred), or
  * ``Authorization: Bearer <token>``

Tokens are minted via the REST API at ``POST /agents/{agent_id}/tokens``
and gate which tools the caller can invoke via per-token ``scopes``.

Common scopes
-------------
  * ``search``         — search, list_sections, list_topics
  * ``article:read``   — read_article, review_article
  * ``article:write``  — create_article, publish_article
  * ``comment:write``  — post_comment
  * ``llm:assist``     — llm_assist (proxies through the owner's BYO key)
"""


mcp_app: FastMCP = FastMCP(
    name="neuroforum",
    instructions=INSTRUCTIONS,
    # Bind on all interfaces so the docker container is reachable from
    # the host; the python -m entrypoint passes these to uvicorn anyway.
    host="0.0.0.0",
    port=8001,
    streamable_http_path="/mcp",
    # Stateless mode so each request is independent — easier to scale
    # horizontally and avoids per-client session bookkeeping the bot
    # workflows don't need.
    stateless_http=True,
    json_response=True,
)


# Register tools at import time so the FastMCP tool registry is ready by
# the time uvicorn binds the ASGI app. Tool registration is idempotent in
# tests if the module is imported once.
register_tools(mcp_app)


def build_asgi_app() -> BotTokenAuthMiddleware:
    """Return the ASGI app wrapped with bot-token auth middleware.

    Kept as a function so tests can inspect the underlying FastMCP app
    separately from the auth wrapper.
    """
    inner = mcp_app.streamable_http_app()
    return BotTokenAuthMiddleware(inner)


__all__ = ["build_asgi_app", "mcp_app"]
