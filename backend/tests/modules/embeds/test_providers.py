"""Pure provider URL parsing tests — no DB, no async fixtures needed."""

from __future__ import annotations

import pytest

from app.modules.embeds.providers import find_provider
from app.modules.embeds.providers.github_gist import GistEmbed
from app.modules.embeds.providers.telegram import TelegramEmbed
from app.modules.embeds.providers.vk import VKEmbed
from app.modules.embeds.providers.youtube import YouTubeEmbed

# ---------------------------------------------------------------------------
# YouTube
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected_id"),
    [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        (
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s",
            "dQw4w9WgXcQ",
        ),
    ],
)
async def test_youtube_extracts_video_id(url: str, expected_id: str) -> None:
    prov = YouTubeEmbed()
    assert prov.matches(url) is True
    data = await prov.fetch(url)
    assert data.iframe_src == f"https://www.youtube.com/embed/{expected_id}"
    assert data.thumbnail == f"https://img.youtube.com/vi/{expected_id}/hqdefault.jpg"
    assert data.width == 560
    assert data.height == 315


def test_youtube_does_not_match_random() -> None:
    assert YouTubeEmbed().matches("https://example.com/youtube.html") is False


# ---------------------------------------------------------------------------
# Gist
# ---------------------------------------------------------------------------


async def test_gist_parsing() -> None:
    prov = GistEmbed()
    url = "https://gist.github.com/octocat/abc123def456"
    assert prov.matches(url) is True
    data = await prov.fetch(url)
    assert data.iframe_src == "https://gist.github.com/octocat/abc123def456.pibb"
    assert data.raw_meta == {"user": "octocat", "gist_id": "abc123def456"}


def test_gist_rejects_non_gist() -> None:
    assert GistEmbed().matches("https://github.com/octocat/repo") is False


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------


async def test_telegram_parsing() -> None:
    prov = TelegramEmbed()
    url = "https://t.me/durov/123"
    assert prov.matches(url) is True
    data = await prov.fetch(url)
    assert data.iframe_src == "https://t.me/durov/123?embed=1&dark=1"
    assert data.raw_meta == {"channel": "durov", "post_id": "123"}


def test_telegram_rejects_channel_root() -> None:
    # No post id → no embed.
    assert TelegramEmbed().matches("https://t.me/durov") is False


# ---------------------------------------------------------------------------
# VK
# ---------------------------------------------------------------------------


async def test_vk_video_parsing() -> None:
    prov = VKEmbed()
    url = "https://vk.com/video-12345_67890"
    assert prov.matches(url) is True
    data = await prov.fetch(url)
    assert data.iframe_src == (
        "https://vk.com/video_ext.php?oid=-12345&id=67890"
    )
    assert data.raw_meta["kind"] == "video"


async def test_vk_wall_no_iframe() -> None:
    prov = VKEmbed()
    url = "https://vk.com/wall-12345_678"
    assert prov.matches(url) is True
    data = await prov.fetch(url)
    assert data.iframe_src is None
    assert data.raw_meta["kind"] == "wall"


def test_vk_rejects_random_path() -> None:
    assert VKEmbed().matches("https://vk.com/durov") is False


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_find_provider_unknown_returns_none() -> None:
    assert find_provider("https://example.com/foo") is None


def test_find_provider_youtube() -> None:
    prov = find_provider("https://www.youtube.com/watch?v=abc12345678")
    assert prov is not None
    assert prov.name == "youtube"
