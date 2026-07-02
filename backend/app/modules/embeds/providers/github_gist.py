"""GitHub Gist embed provider.

GitHub offers a ``.pibb`` URL suffix that returns an embeddable HTML
snippet — we just point an iframe at it.
"""

from __future__ import annotations

import re

from app.modules.embeds.exceptions import EmbedFetchFailed
from app.modules.embeds.providers.base import EmbedProvider
from app.modules.embeds.schemas import EmbedData

# gist.github.com/<user>/<gist_id> where gist_id is a hex string.
_RE = re.compile(
    r"^https?://gist\.github\.com/([^/\s]+)/([a-f0-9]+)",
    re.IGNORECASE,
)


class GistEmbed(EmbedProvider):
    name = "github_gist"

    def matches(self, url: str) -> bool:
        return bool(_RE.match(url))

    async def fetch(self, url: str) -> EmbedData:
        m = _RE.match(url)
        if m is None:
            raise EmbedFetchFailed(f"Could not parse GitHub gist URL {url!r}")
        user, gist_id = m.group(1), m.group(2)
        return EmbedData(
            iframe_src=f"https://gist.github.com/{user}/{gist_id}.pibb",
            # Gist embed scales to its container — we hint percentages
            # with a sentinel ``-1`` so the frontend renders ``width:100%``.
            width=-1,
            height=400,
            title=None,
            thumbnail=None,
            raw_meta={"user": user, "gist_id": gist_id},
        )


__all__ = ["GistEmbed"]
