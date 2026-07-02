"""Embed provider registry: resolves a URL to one of four whitelisted providers."""

from __future__ import annotations

from app.modules.embeds.providers.base import EmbedProvider
from app.modules.embeds.providers.github_gist import GistEmbed
from app.modules.embeds.providers.telegram import TelegramEmbed
from app.modules.embeds.providers.vk import VKEmbed
from app.modules.embeds.providers.youtube import YouTubeEmbed

# Order matters only for human readability — ``matches`` is unambiguous per host.
PROVIDERS: list[EmbedProvider] = [
    YouTubeEmbed(),
    GistEmbed(),
    TelegramEmbed(),
    VKEmbed(),
]


def find_provider(url: str) -> EmbedProvider | None:
    """Return the first provider whose ``matches`` predicate succeeds."""
    for provider in PROVIDERS:
        if provider.matches(url):
            return provider
    return None


__all__ = [
    "PROVIDERS",
    "EmbedProvider",
    "GistEmbed",
    "TelegramEmbed",
    "VKEmbed",
    "YouTubeEmbed",
    "find_provider",
]
