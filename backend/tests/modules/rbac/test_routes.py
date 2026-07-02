"""Route-level tests for ``rbac`` / moderation."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token


async def _register_and_login(
    client: AsyncClient,
    username: str,
    db_session: AsyncSession | None = None,
    role: str | None = None,
) -> tuple[str, str]:
    """Returns (user_id, access_token)."""
    reg = await client.post(
        "/api/v1/users/",
        json={
            "username": username,
            "email": f"{username}@x.io",
            "password": "hunter22!",
        },
    )
    assert reg.status_code == 201, reg.text
    user_id = reg.json()["id"]
    if role and db_session is not None:
        await db_session.execute(
            text("UPDATE users SET role = :r WHERE id = :id"),
            {"r": role, "id": user_id},
        )
        await db_session.commit()
    token = create_access_token(sub=user_id, extra={"role": role or "user"})
    return user_id, token


async def test_moderator_creates_ban_201(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, mod_token = await _register_and_login(client, "rmod1", db_session, role="moderator")
    victim_id, _ = await _register_and_login(client, "rvic1")
    resp = await client.post(
        "/api/v1/moderation/bans/",
        json={
            "user_id": victim_id,
            "reason": "spam",
            "scope": "global",
        },
        headers={"Authorization": f"Bearer {mod_token}"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["user_id"] == victim_id
    assert body["scope"] == "global"


async def test_regular_user_cannot_create_ban_403(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, user_token = await _register_and_login(client, "ruser1")
    victim_id, _ = await _register_and_login(client, "rvic2")
    resp = await client.post(
        "/api/v1/moderation/bans/",
        json={
            "user_id": victim_id,
            "reason": "spam",
            "scope": "global",
        },
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 403


async def test_create_ban_requires_auth(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/moderation/bans/",
        json={
            "user_id": "11111111-1111-1111-1111-111111111111",
            "reason": "spam",
            "scope": "global",
        },
    )
    assert resp.status_code == 401


async def test_my_bans_lists_active(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, mod_token = await _register_and_login(client, "rmod2", db_session, role="moderator")
    victim_id, victim_token = await _register_and_login(client, "rvic3")
    # Pre-condition: empty list.
    pre = await client.get(
        "/api/v1/moderation/bans/me",
        headers={"Authorization": f"Bearer {victim_token}"},
    )
    assert pre.status_code == 200
    assert pre.json() == []
    # Issue the ban.
    ban_resp = await client.post(
        "/api/v1/moderation/bans/",
        json={"user_id": victim_id, "reason": "x", "scope": "global"},
        headers={"Authorization": f"Bearer {mod_token}"},
    )
    assert ban_resp.status_code == 201
    # Victim sees their ban.
    post = await client.get(
        "/api/v1/moderation/bans/me",
        headers={"Authorization": f"Bearer {victim_token}"},
    )
    assert post.status_code == 200
    bans = post.json()
    assert len(bans) == 1
    assert bans[0]["user_id"] == victim_id


async def test_lift_ban_via_patch(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, mod_token = await _register_and_login(client, "rmod3", db_session, role="moderator")
    victim_id, _ = await _register_and_login(client, "rvic4")
    ban_resp = await client.post(
        "/api/v1/moderation/bans/",
        json={"user_id": victim_id, "reason": "x", "scope": "global"},
        headers={"Authorization": f"Bearer {mod_token}"},
    )
    ban_id = ban_resp.json()["id"]
    lift = await client.patch(
        f"/api/v1/moderation/bans/{ban_id}/lift",
        json={"reason": "appeal approved"},
        headers={"Authorization": f"Bearer {mod_token}"},
    )
    assert lift.status_code == 200, lift.text
    assert lift.json()["lifted_at"] is not None
    assert lift.json()["lift_reason"] == "appeal approved"
