"""Slug helpers shared by ``forum`` and ``articles``.

Why a hand-rolled translit map instead of ``python-slugify``:

- ``python-slugify`` pulls ``Unidecode`` which is a 1.5 MB tarball with a
  permissive but non-MIT license. We only need Cyrillic → Latin, so the
  hand-rolled map below is tiny, deterministic, and reviewable.
- The data-model.md "URL and identifiers" section ratifies Khabr-style
  ``/articles/<uuid>/<slug>`` URLs where the slug is *cosmetic* — strict
  fidelity to ICU rules is not required.
"""

# ``RUF001`` flags every Cyrillic glyph as "ambiguous" — which is
# precisely the point of this module's translit table. File-level disable.
# ruff: noqa: RUF001

from __future__ import annotations

import re
import uuid

# Single-character Cyrillic → Latin map. Mixed-case handled by lowercasing
# the input first, so we only need lowercase entries.
_CYR_MAP: dict[str, str] = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e",
    "ё": "yo", "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k",
    "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "",
    "э": "e", "ю": "yu", "я": "ya",
}

# Collapse any run of characters outside [a-z0-9] into a single dash.
_NON_SLUG_RE = re.compile(r"[^a-z0-9]+")
# Strip leading/trailing dashes after collapse.
_EDGE_DASH_RE = re.compile(r"^-+|-+$")


def transliterate(value: str) -> str:
    """Cyrillic → Latin character-by-character, leaving other chars intact."""
    return "".join(_CYR_MAP.get(ch, ch) for ch in value)


def make_slug(title: str, *, max_length: int = 100) -> str:
    """Generate a URL-safe slug from a free-form title.

    - Lowercases first so the Cyrillic map only needs the lowercase set.
    - Transliterates Cyrillic letters.
    - Replaces every non ``[a-z0-9]`` run with a single dash.
    - Strips edge dashes and truncates to ``max_length``.
    - Falls back to a short UUID prefix if the result is empty (e.g. the
      title contained only emoji or punctuation).
    """
    lowered = title.lower().strip()
    transliterated = transliterate(lowered)
    collapsed = _NON_SLUG_RE.sub("-", transliterated)
    stripped = _EDGE_DASH_RE.sub("", collapsed)
    if not stripped:
        return uuid.uuid4().hex[:8]
    return stripped[:max_length].rstrip("-") or uuid.uuid4().hex[:8]


__all__ = ["make_slug", "transliterate"]
