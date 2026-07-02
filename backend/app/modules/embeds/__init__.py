"""Embeds module: oEmbed-style URL → iframe cache for the 4-provider whitelist.

Providers: youtube, github_gist, telegram, vk. Each one is a tiny URL
parser that returns a fully-resolved ``EmbedData`` — we explicitly do
NOT call upstream oEmbed endpoints (don't trust their HTML).
"""
