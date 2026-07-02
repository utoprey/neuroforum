"""Route-level tests for the ``messages`` module."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token


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


async def _register(
    client: AsyncClient,
    username: str,
    db_session: AsyncSession | None = None,
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
    if role and db_session is not None:
        await db_session.execute(
            text("UPDATE users SET role = :r WHERE id = :id"),
            {"r": role, "id": user_id},
        )
        await db_session.commit()
    token = create_access_token(sub=user_id, extra={"role": role or "user"})
    return user_id, token


async def _published_article(
    client: AsyncClient,
    db_session: AsyncSession,
    *,
    section_slug: str,
) -> tuple[str, str, str]:
    """Returns ``(author_token, article_id, admin_token)``.

    Creates a section, a topic, an article, publishes it.
    """
    _, admin_token = await _register(
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
    topic_id = t.json()["id"]
    _, author_token = await _register(
        client, f"author_{section_slug}", db_session
    )
    create = await client.post(
        f"/api/v1/topics/{topic_id}/articles",
        json={"title": "Article", "content": _doc()},
        headers={"Authorization": f"Bearer {author_token}"},
    )
    article_id = create.json()["id"]
    pub = await client.post(
        f"/api/v1/articles/{article_id}/publish",
        headers={"Authorization": f"Bearer {author_token}"},
    )
    assert pub.status_code == 200, pub.text
    return author_token, article_id, admin_token


# ---------------------------------------------------------------------------
# Post / list
# ---------------------------------------------------------------------------


async def test_post_message_201(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    author_token, article_id, _ = await _published_article(
        client, db_session, section_slug="mr1"
    )
    resp = await client.post(
        f"/api/v1/articles/{article_id}/messages",
        json={"content": _doc("Hi")},
        headers={"Authorization": f"Bearer {author_token}"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["depth"] == 0
    assert body["parent_id"] is None
    assert body["status"] == "visible"


async def test_post_message_requires_auth(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, article_id, _ = await _published_article(
        client, db_session, section_slug="mr2"
    )
    resp = await client.post(
        f"/api/v1/articles/{article_id}/messages",
        json={"content": _doc()},
    )
    assert resp.status_code == 401


async def test_list_messages_returns_top_level_plus_children(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    author_token, article_id, _ = await _published_article(
        client, db_session, section_slug="mr3"
    )
    root = await client.post(
        f"/api/v1/articles/{article_id}/messages",
        json={"content": _doc("root")},
        headers={"Authorization": f"Bearer {author_token}"},
    )
    root_id = root.json()["id"]
    child = await client.post(
        f"/api/v1/articles/{article_id}/messages",
        json={"content": _doc("child"), "parent_id": root_id},
        headers={"Authorization": f"Bearer {author_token}"},
    )
    assert child.status_code == 201
    listing = await client.get(f"/api/v1/articles/{article_id}/messages")
    assert listing.status_code == 200
    ids = {m["id"] for m in listing.json()}
    assert root_id in ids
    assert child.json()["id"] in ids


async def test_get_thread_returns_subtree(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    author_token, article_id, _ = await _published_article(
        client, db_session, section_slug="mr4"
    )
    root = await client.post(
        f"/api/v1/articles/{article_id}/messages",
        json={"content": _doc("R")},
        headers={"Authorization": f"Bearer {author_token}"},
    )
    root_id = root.json()["id"]
    c1 = await client.post(
        f"/api/v1/articles/{article_id}/messages",
        json={"content": _doc("C1"), "parent_id": root_id},
        headers={"Authorization": f"Bearer {author_token}"},
    )
    c2 = await client.post(
        f"/api/v1/articles/{article_id}/messages",
        json={"content": _doc("C2"), "parent_id": c1.json()["id"]},
        headers={"Authorization": f"Bearer {author_token}"},
    )
    thread = await client.get(f"/api/v1/messages/{root_id}/thread")
    assert thread.status_code == 200
    ids = [m["id"] for m in thread.json()]
    assert ids == [root_id, c1.json()["id"], c2.json()["id"]]


# ---------------------------------------------------------------------------
# Mod edit requires reason
# ---------------------------------------------------------------------------


async def test_mod_edit_requires_reason(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    author_token, article_id, _ = await _published_article(
        client, db_session, section_slug="mr5"
    )
    _, mod_token = await _register(client, "mod_mr5", db_session, role="moderator")
    post = await client.post(
        f"/api/v1/articles/{article_id}/messages",
        json={"content": _doc("hi")},
        headers={"Authorization": f"Bearer {author_token}"},
    )
    msg_id = post.json()["id"]
    bad = await client.patch(
        f"/api/v1/messages/{msg_id}",
        json={"content": _doc("modified")},
        headers={"Authorization": f"Bearer {mod_token}"},
    )
    assert bad.status_code == 422
    ok = await client.patch(
        f"/api/v1/messages/{msg_id}",
        json={"content": _doc("modified"), "edit_reason": "moderation"},
        headers={"Authorization": f"Bearer {mod_token}"},
    )
    assert ok.status_code == 200
    assert ok.json()["status"] == "edited"


# ---------------------------------------------------------------------------
# Soft delete shows placeholder
# ---------------------------------------------------------------------------


async def test_soft_delete_returns_placeholder(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    author_token, article_id, _ = await _published_article(
        client, db_session, section_slug="mr6"
    )
    post = await client.post(
        f"/api/v1/articles/{article_id}/messages",
        json={"content": _doc("bye")},
        headers={"Authorization": f"Bearer {author_token}"},
    )
    msg_id = post.json()["id"]
    delete = await client.delete(
        f"/api/v1/messages/{msg_id}",
        headers={"Authorization": f"Bearer {author_token}"},
    )
    assert delete.status_code == 200
    body = delete.json()
    assert body["status"] == "deleted_by_author"
    assert body["content"] is None
    assert body["placeholder"] == "Сообщение удалено автором"
