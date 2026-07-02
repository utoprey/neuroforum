"""Entrypoint: ``python -m app.mcp_server``.

Boots a uvicorn server hosting the FastMCP streamable-HTTP ASGI app on
``0.0.0.0:8001``. The MCP transport lives under ``/mcp``; everything else
returns 404. Authentication via ``X-Bot-Token`` is enforced by
:class:`BotTokenAuthMiddleware` before the inner FastMCP app sees the
request.
"""

from __future__ import annotations

import logging
import os
from typing import Any, cast

import uvicorn

from app.mcp_server.server import build_asgi_app

logging.basicConfig(
    level=os.environ.get("MCP_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("app.mcp_server")


def main() -> None:
    """Run uvicorn against the MCP ASGI app."""
    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("MCP_PORT", "8001"))
    log.info("Starting Neuroforum MCP server on http://%s:%d/mcp", host, port)
    # build_asgi_app() returns our middleware-wrapped ASGI callable; the
    # uvicorn type stubs use a narrower protocol, so cast to Any.
    uvicorn.run(
        cast(Any, build_asgi_app()),
        host=host,
        port=port,
        # MCP transport uses Server-Sent Events for tool-call streams; the
        # proxy-headers flag also helps when running behind nginx.
        proxy_headers=True,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
