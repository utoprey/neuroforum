"""Provider protocol — what every embed parser must implement."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.modules.embeds.schemas import EmbedData


class EmbedProvider(ABC):
    """Abstract base. Each provider is stateless — single instance is fine."""

    name: str

    @abstractmethod
    def matches(self, url: str) -> bool:
        """Return True if this provider can resolve ``url``."""

    @abstractmethod
    async def fetch(self, url: str) -> EmbedData:
        """Resolve ``url`` to an ``EmbedData`` (no upstream HTML trusted)."""


__all__ = ["EmbedProvider"]
