"""Telegram channel post embed provider.

Pattern: ``https://t.me/<channel>/<post_id>``. Telegram supports an
``?embed=1`` flag that renders a self-contained iframe.
"""

from __future__ import annotations

import re

from app.modules.embeds.exceptions import EmbedFetchFailed
from app.modules.embeds.providers.base import EmbedProvider
from app.modules.embeds.schemas import EmbedData

_RE = re.compile(
    r"^https?://t\.me/([A-Za-z0-9_]+)/(\d+)",
    re.IGNORECASE,
)


class TelegramEmbed(EmbedProvider):
    name = "telegram"

    def matches(self, url: str) -> bool:
        return bool(_RE.match(url))

    async def fetch(self, url: str) -> EmbedData:
        m = _RE.match(url)
        if m is None:
            raise EmbedFetchFailed(f"Could not parse Telegram URL {url!r}")
        channel, post_id = m.group(1), m.group(2)
        return EmbedData(
            iframe_src=f"https://t.me/{channel}/{post_id}?embed=1&dark=1",
            width=500,
            # Posts are variable height; 600 is a sensible default that
            # the frontend can override via ``ResizeObserver``.
            height=600,
            title=None,
            thumbnail=None,
            raw_meta={"channel": channel, "post_id": post_id},
        )


__all__ = ["TelegramEmbed"]
