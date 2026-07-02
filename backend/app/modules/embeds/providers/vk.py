"""VK (vk.com) embed provider.

Three URL shapes we support:

- ``vk.com/video<oid>_<vid>`` → embedded video player iframe.
- ``vk.com/wall<oid>_<post_id>`` → no iframe; we return a link-only meta.
- ``vk.com/photo<oid>_<photo_id>`` → no iframe; link-only.

VK doesn't have a public oEmbed endpoint we'd trust, so wall/photo
become "preview links" — frontend renders them as a clickable card.
"""

from __future__ import annotations

import re

from app.modules.embeds.exceptions import EmbedFetchFailed
from app.modules.embeds.providers.base import EmbedProvider
from app.modules.embeds.schemas import EmbedData

# vk.com/<kind><owner_id>_<id> — owner_id may be negative for groups.
_HOST_RE = re.compile(r"^https?://(?:www\.|m\.)?vk\.com/", re.IGNORECASE)
_VIDEO_RE = re.compile(r"vk\.com/video(-?\d+)_(\d+)", re.IGNORECASE)
_WALL_RE = re.compile(r"vk\.com/wall(-?\d+)_(\d+)", re.IGNORECASE)
_PHOTO_RE = re.compile(r"vk\.com/photo(-?\d+)_(\d+)", re.IGNORECASE)


class VKEmbed(EmbedProvider):
    name = "vk"

    def matches(self, url: str) -> bool:
        if not _HOST_RE.search(url):
            return False
        return bool(
            _VIDEO_RE.search(url) or _WALL_RE.search(url) or _PHOTO_RE.search(url)
        )

    async def fetch(self, url: str) -> EmbedData:
        if (m := _VIDEO_RE.search(url)) is not None:
            oid, vid = m.group(1), m.group(2)
            return EmbedData(
                iframe_src=f"https://vk.com/video_ext.php?oid={oid}&id={vid}",
                width=560,
                height=315,
                title=None,
                thumbnail=None,
                raw_meta={"kind": "video", "oid": oid, "id": vid},
            )
        if (m := _WALL_RE.search(url)) is not None:
            oid, post_id = m.group(1), m.group(2)
            return EmbedData(
                iframe_src=None,
                width=0,
                height=0,
                title=None,
                thumbnail=None,
                raw_meta={"kind": "wall", "oid": oid, "post_id": post_id, "url": url},
            )
        if (m := _PHOTO_RE.search(url)) is not None:
            oid, photo_id = m.group(1), m.group(2)
            return EmbedData(
                iframe_src=None,
                width=0,
                height=0,
                title=None,
                thumbnail=None,
                raw_meta={"kind": "photo", "oid": oid, "photo_id": photo_id, "url": url},
            )
        raise EmbedFetchFailed(f"Could not parse VK URL {url!r}")


__all__ = ["VKEmbed"]
