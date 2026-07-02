"""Application settings loaded from environment / .env via pydantic-settings."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "staging", "production"]


class Settings(BaseSettings):
    """Global runtime configuration.

    Fields mirror `.env.example`. Anything not in this class will be ignored
    (see ``extra="ignore"``), so unrelated env vars from the host don't break
    boot.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # --- Infra connection strings ---
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://forum:forum@localhost:5432/forum",
        description="SQLAlchemy async URL (must use the asyncpg driver).",
    )
    REDIS_URL: str = Field(default="redis://localhost:6379/0")
    RABBITMQ_URL: str = Field(default="amqp://guest:guest@localhost:5672/")

    # --- Auth / JWT ---
    SECRET_KEY: str = Field(
        default="change-me-in-prod-min-32-chars-long",
        min_length=32,
        description="HS256 signing key for JWT. Override in production.",
    )
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=15, ge=1)
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=7, ge=1)

    # --- Object storage (MinIO / S3-compatible) ---
    MINIO_ENDPOINT: str = Field(default="localhost:9000")
    MINIO_ACCESS_KEY: str = Field(default="minioadmin")
    MINIO_SECRET_KEY: str = Field(default="minioadmin")
    MINIO_BUCKET: str = Field(default="forum-media")
    MINIO_SECURE: bool = Field(default=False)
    MINIO_PUBLIC_BASE_URL: str = Field(
        default="http://localhost:9000",
        description="Public-facing base URL used to render attachment read URLs.",
    )

    # --- Search ---
    # See ``docs/adr/0003-postgres-tsvector-with-opensearch-stub.md``: the
    # two backends behind ``app.modules.search.protocol.SearchEngine``.
    SEARCH_BACKEND: Literal["postgres", "opensearch"] = Field(default="postgres")

    # --- Encryption (agent BYO API keys, etc.) ---
    # Used by ``app.modules.agents.crypto`` to derive a Fernet key for
    # symmetric encryption of per-user provider API keys at rest. Any
    # 32-character-plus secret works — the sha256 derivation lifts it to
    # a 32-byte URL-safe base64 key.
    ENCRYPTION_KEY: str = Field(
        default="change-me-32-bytes-min-encryption-key-for-fernet",
        min_length=32,
        description="Secret used to derive the Fernet key for at-rest encryption.",
    )

    # --- Misc ---
    ENVIRONMENT: Environment = Field(default="development")


@lru_cache(maxsize=1)
def _build_settings() -> Settings:
    return Settings()


settings: Settings = _build_settings()
