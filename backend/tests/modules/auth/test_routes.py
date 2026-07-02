"""Route-level tests for the ``auth`` module."""

from __future__ import annotations

from httpx import AsyncClient


async def _register(client: AsyncClient, username: str = "router") -> None:
    resp = await client.post(
        "/api/v1/users/",
        json={
            "username": username,
            "email": f"{username}@x.io",
            "password": "hunter22!",
        },
    )
    assert resp.status_code == 201


async def test_login_returns_token_pair(client: AsyncClient) -> None:
    await _register(client, "logger")
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "logger", "password": "hunter22!"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0


async def test_login_wrong_password_401(client: AsyncClient) -> None:
    await _register(client, "wronger")
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "wronger", "password": "BAD"},
    )
    assert resp.status_code == 401


async def test_refresh_rotates(client: AsyncClient) -> None:
    await _register(client, "rotr")
    login = await client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "rotr", "password": "hunter22!"},
    )
    first = login.json()["refresh_token"]

    rot = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": first},
    )
    assert rot.status_code == 200, rot.text
    second = rot.json()["refresh_token"]
    assert second != first

    # The old refresh is now revoked.
    again = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": first},
    )
    assert again.status_code == 401


async def test_logout_requires_auth(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/logout", json={"refresh_token": "x"}
    )
    assert resp.status_code == 401


async def test_logout_revokes_token(client: AsyncClient) -> None:
    await _register(client, "logout1")
    login = await client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "logout1", "password": "hunter22!"},
    )
    access = login.json()["access_token"]
    refresh = login.json()["refresh_token"]
    resp = await client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": refresh},
        headers={"Authorization": f"Bearer {access}"},
    )
    assert resp.status_code == 204
    # Refresh is now revoked.
    again = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh},
    )
    assert again.status_code == 401
