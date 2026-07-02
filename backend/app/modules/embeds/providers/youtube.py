"""YouTube embed provider.

Recognises ``youtube.com/watch?v=X``, ``youtu.be/X``, ``youtube.com/embed/X``
and ``youtube.com/shorts/X``. Builds an embed URL + thumbnail link — we
don't talk to the YouTube API so no API key is needed and we never get
rate-limited.
"""

from __future__ import annotations

import re

from app.modules.embeds.exceptions import EmbedFetchFailed
from app.modules.embeds.providers.base import EmbedProvider
from app.modules.embeds.schemas import EmbedData

# Host check. ``www.`` and ``music.`` and the short ``youtu.be`` form are
# all accepted; we extract the video id with the patterns below.
_HOST_RE = re.compile(
    r"^https?://(?:www\.|m\.|music\.)?(?:youtube\.com|youtu\.be)(?:/|$)",
    re.IGNORECASE,
)

# A YouTube video id is exactly 11 chars of [A-Za-z0-9_-].
_VID_ID = r"[A-Za-z0-9_-]{11}"

# Patterns: ``watch?v=ID``, short ``youtu.be/ID``, ``embed/ID``, ``shorts/ID``.
_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(rf"[?&]v=({_VID_ID})"),
    re.compile(rf"youtu\.be/({_VID_ID})"),
    re.compile(rf"youtube\.com/embed/({_VID_ID})"),
    re.compile(rf"youtube\.com/shorts/({_VID_ID})"),
)


class YouTubeEmbed(EmbedProvider):
    name = "youtube"

    def matches(self, url: str) -> bool:
        return bool(_HOST_RE.search(url))

    async def fetch(self, url: str) -> EmbedData:
        video_id = self._extract_video_id(url)
        if video_id is None:
            raise EmbedFetchFailed(f"Could not extract YouTube video id from {url!r}")
        return EmbedData(
            iframe_src=f"https://www.youtube.com/embed/{video_id}",
            width=560,
            height=315,
            title=None,
            thumbnail=f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
            raw_meta={"video_id": video_id},
        )

    @staticmethod
    def _extract_video_id(url: str) -> str | None:
        for pat in _PATTERNS:
            m = pat.search(url)
            if m:
                return m.group(1)
        return None


__all__ = ["YouTubeEmbed"]
