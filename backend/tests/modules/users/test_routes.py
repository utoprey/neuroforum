"""Route-level tests for the ``users`` module."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token


async def test_register_user_201(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/users/",
        json={
            "username": "newbie",
            "email": "newbie@x.io",
            "password": "hunter22!",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["username"] == "newbie"
    assert body["email"] == "newbie@x.io"
    assert body["role"] == "user"
    assert body["is_active"] is True
    assert body["profile"] is not None


async def test_register_user_duplicate_username_409(client: AsyncClient) -> None:
    payload = {
        "username": "dup",
        "email": "dup@x.io",
        "password": "hunter22!",
    }
    r1 = await client.post("/api/v1/users/", json=payload)
    assert r1.status_code == 201
    payload2 = {**payload, "email": "other@x.io"}
    r2 = await client.post("/api/v1/users/", json=payload2)
    assert r2.status_code == 409


async def test_register_user_bad_username_422(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/users/",
        json={
            "username": "bad name!",
            "email": "x@y.io",
            "password": "hunter22!",
        },
    )
    assert resp.status_code == 422


async def test_get_me_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/users/me")
    assert resp.status_code == 401


async def test_get_me_with_valid_token(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    reg = await client.post(
        "/api/v1/users/",
        json={
            "username": "tokuser",
            "email": "tok@x.io",
            "password": "hunter22!",
        },
    )
    assert reg.status_code == 201
    user_id = reg.json()["id"]
    token = create_access_token(sub=user_id)
    resp = await client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == user_id


async def test_get_me_with_inactive_user_403(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    reg = await client.post(
        "/api/v1/users/",
        json={
            "username": "dead",
            "email": "dead@x.io",
            "password": "hunter22!",
        },
    )
    user_id = reg.json()["id"]
    await db_session.execute(
        text("UPDATE users SET is_active = false WHERE id = :id"),
        {"id": user_id},
    )
    await db_session.commit()
    token = create_access_token(sub=user_id)
    resp = await client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403


async def test_search_users_prefix_route(client: AsyncClient) -> None:
    for name in ("xander", "xanadu", "yvette"):
        await client.post(
            "/api/v1/users/",
            json={
                "username": name,
                "email": f"{name}@x.io",
                "password": "hunter22!",
            },
        )
    resp = await client.get("/api/v1/users/search", params={"q": "@xan"})
    assert resp.status_code == 200
    names = {u["username"] for u in resp.json()}
    assert names == {"xander", "xanadu"}


async def test_get_user_by_username_404(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/users/no-such-user")
    assert resp.status_code == 404


async def test_recent_topics_empty_for_user_with_no_messages(client: AsyncClient) -> None:
    reg = await client.post(
        "/api/v1/users/",
        json={
            "username": "topicz",
            "email": "topicz@x.io",
            "password": "hunter22!",
        },
    )
    assert reg.status_code == 201
    resp = await client.get("/api/v1/users/topicz/recent-topics")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_recent_messages_empty_for_user_with_no_messages(
    client: AsyncClient,
) -> None:
    reg = await client.post(
        "/api/v1/users/",
        json={
            "username": "msgz",
            "email": "msgz@x.io",
            "password": "hunter22!",
        },
    )
    assert reg.status_code == 201
    resp = await client.get("/api/v1/users/msgz/recent-messages")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_recent_messages_user_not_found(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/users/no-such-user/recent-messages")
    assert resp.status_code == 404


@pytest.mark.parametrize("missing", ["username", "email", "password"])
async def test_register_user_missing_field_422(
    client: AsyncClient, missing: str
) -> None:
    payload = {
        "username": "okname",
        "email": "ok@x.io",
        "password": "hunter22!",
    }
    payload.pop(missing)
    resp = await client.post("/api/v1/users/", json=payload)
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Activity feed endpoints: /articles, /messages, /reactions
# ---------------------------------------------------------------------------


def _doc(text_value: str = "Hello") -> dict[str, object]:
    return {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text_value}],
            }
        ],
    }


async def _register_with_role(
    client: AsyncClient,
    username: str,
    db_session: AsyncSession,
    role: str | None = None,
) -> tuple[str, str]:
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
    if role:
        await db_session.execute(
            text("UPDATE users SET role = :r WHERE id = :id"),
            {"r": role, "id": user_id},
        )
        await db_session.commit()
    token = create_access_token(sub=user_id, extra={"role": role or "user"})
    return user_id, token


async def _bootstrap_topic(
    client: AsyncClient, db_session: AsyncSession, *, section_slug: str
) -> tuple[str, str]:
    _, admin_token = await _register_with_role(
        client, f"adm_{section_slug}", db_session, role="admin"
    )
    await client.post(
        "/api/v1/sections",
        json={"title": section_slug.upper(), "slug": section_slug},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    t = await client.post(
        f"/api/v1/sections/{section_slug}/topics",
        json={"title": "Topic"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    return admin_token, t.json()["id"]


async def test_user_articles_list(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, topic_id = await _bootstrap_topic(client, db_session, section_slug="ua1")
    _, token = await _register_with_role(client, "alice_arts", db_session)
    # Draft + published — only the published one should show up.
    await client.post(
        f"/api/v1/topics/{topic_id}/articles",
        json={"title": "Draft", "content": _doc("d")},
        headers={"Authorization": f"Bearer {token}"},
    )
    pub_resp = await client.post(
        f"/api/v1/topics/{topic_id}/articles",
        json={"title": "Pub", "content": _doc("p")},
        headers={"Authorization": f"Bearer {token}"},
    )
    pub_id = pub_resp.json()["id"]
    await client.post(
        f"/api/v1/articles/{pub_id}/publish",
        headers={"Authorization": f"Bearer {token}"},
    )

    resp = await client.get("/api/v1/users/alice_arts/articles")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    titles = {a["title"] for a in body}
    assert titles == {"Pub"}
    # Author shape sanity-check.
    assert body[0]["author"]["username"] == "alice_arts"
    assert body[0]["status"] == "published"


async def test_user_articles_unknown_user_404(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/users/ghost/articles")
    assert resp.status_code == 404


async def test_user_messages_list(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, topic_id = await _bootstrap_topic(client, db_session, section_slug="um1")
    _, author_token = await _register_with_role(client, "bob_msg", db_session)
    create = await client.post(
        f"/api/v1/topics/{topic_id}/articles",
        json={"title": "Host", "content": _doc("h")},
        headers={"Authorization": f"Bearer {author_token}"},
    )
    article_id = create.json()["id"]
    await client.post(
        f"/api/v1/articles/{article_id}/publish",
        headers={"Authorization": f"Bearer {author_token}"},
    )
    # Author leaves two comments under their own article.
    for text_value in ("first", "second"):
        msg = await client.post(
            f"/api/v1/articles/{article_id}/messages",
            json={"content": _doc(text_value)},
            headers={"Authorization": f"Bearer {author_token}"},
        )
        assert msg.status_code == 201, msg.text

    resp = await client.get("/api/v1/users/bob_msg/messages")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 2
    # Both messages came back with the expected snippets (order may tie when
    # ``created_at`` resolution can't distinguish two back-to-back inserts).
    snippets = {m["snippet"] for m in body}
    assert snippets == {"first", "second"}
    # Context is populated.
    assert body[0]["article_slug"]
    assert body[0]["topic_slug"]

    # Pagination — offset=1 must return exactly one of the two.
    paged = await client.get(
        "/api/v1/users/bob_msg/messages", params={"limit": 1, "offset": 1}
    )
    assert paged.status_code == 200
    paged_body = paged.json()
    assert len(paged_body) == 1
    assert paged_body[0]["snippet"] in {"first", "second"}


async def test_user_reactions_list(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, topic_id = await _bootstrap_topic(client, db_session, section_slug="ur1")
    _, author_token = await _register_with_role(client, "carol_react", db_session)
    create = await client.post(
        f"/api/v1/topics/{topic_id}/articles",
        json={"title": "Article-X", "content": _doc("article body")},
        headers={"Authorization": f"Bearer {author_token}"},
    )
    article_id = create.json()["id"]
    await client.post(
        f"/api/v1/articles/{article_id}/publish",
        headers={"Authorization": f"Bearer {author_token}"},
    )
    msg = await client.post(
        f"/api/v1/articles/{article_id}/messages",
        json={"content": _doc("comment body")},
        headers={"Authorization": f"Bearer {author_token}"},
    )
    msg_id = msg.json()["id"]

    # React on the article and on the message.
    r1 = await client.post(
        f"/api/v1/articles/{article_id}/reactions",
        json={"kind": "brain"},
        headers={"Authorization": f"Bearer {author_token}"},
    )
    assert r1.status_code == 204
    r2 = await client.post(
        f"/api/v1/messages/{msg_id}/reactions",
        json={"kind": "dna"},
        headers={"Authorization": f"Bearer {author_token}"},
    )
    assert r2.status_code == 204

    resp = await client.get("/api/v1/users/carol_react/reactions")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 2

    by_target = {item["target_type"]: item for item in body}
    assert set(by_target) == {"article", "message"}

    art_row = by_target["article"]
    assert art_row["target_id"] == article_id
    assert art_row["article_id"] == article_id
    assert art_row["article_slug"]
    assert art_row["article_title"] == "Article-X"
    assert art_row["kind"] == "brain"
    assert art_row["snippet"] == "article body"

    msg_row = by_target["message"]
    assert msg_row["target_id"] == msg_id
    # For message reactions we still surface the owning article.
    assert msg_row["article_id"] == article_id
    assert msg_row["article_title"] == "Article-X"
    assert msg_row["kind"] == "dna"
    assert msg_row["snippet"] == "comment body"

    # Sort: newest first across both tables. ``reacted_at`` is populated by
    # ``now()`` on insert and the two inserts can land in the same
    # microsecond — assert non-strict ordering (reacted_at descending).
    timestamps = [item["reacted_at"] for item in body]
    assert timestamps == sorted(timestamps, reverse=True)


async def test_user_reactions_unknown_user_404(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/users/ghost/reactions")
    assert resp.status_code == 404


async def test_user_messages_unknown_user_404(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/users/ghost/messages")
    assert resp.status_code == 404
