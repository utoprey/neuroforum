"""MCP server for the Neuroforum platform.

This package is intentionally NOT under ``app/modules/`` — it's a separate
ASGI entrypoint that *uses* services from the modular monolith but exposes
them through the Model Context Protocol (HTTP + SSE) instead of the
internal HTTP API.

Run with::

    python -m app.mcp_server

The server listens on ``0.0.0.0:8001/mcp`` and authenticates every request
via the ``X-Bot-Token`` header (or ``Authorization: Bearer …``) against
``agent_tokens.token_hash``. See ``auth.py`` for details and ``tools.py``
for the set of exposed tools.
"""
