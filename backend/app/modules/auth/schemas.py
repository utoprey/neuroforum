"""Pydantic v2 schemas for ``auth`` endpoints."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, SecretStr


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username_or_email: str
    password: SecretStr


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str


class TokenPair(BaseModel):
    model_config = ConfigDict(extra="forbid")

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


__all__ = ["LoginRequest", "RefreshRequest", "TokenPair"]
