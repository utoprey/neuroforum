"""Route-level tests for the ``reactions`` module."""

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
) -> tuple[str, str]:
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
    return author_token, article_id


# ---------------------------------------------------------------------------
# Article reactions
# ---------------------------------------------------------------------------


async def test_react_and_list_article(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    author_token, article_id = await _published_article(
        client, db_session, section_slug="rr1"
    )
    resp = await client.post(
        f"/api/v1/articles/{article_id}/reactions",
        json={"kind": "brain"},
        headers={"Authorization": f"Bearer {author_token}"},
    )
    assert resp.status_code == 204
    listing = await client.get(f"/api/v1/articles/{article_id}/reactions")
    assert listing.status_code == 200
    summary = listing.json()
    assert summary == [{"kind": "brain", "count": 1}]


async def test_react_idempotent_route(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    author_token, article_id = await _published_article(
        client, db_session, section_slug="rr2"
    )
    for _ in range(3):
        resp = await client.post(
            f"/api/v1/articles/{article_id}/reactions",
            json={"kind": "synapse"},
            headers={"Authorization": f"Bearer {author_token}"},
        )
        assert resp.status_code == 204
    summary = (await client.get(
        f"/api/v1/articles/{article_id}/reactions"
    )).json()
    syn = [s for s in summary if s["kind"] == "synapse"]
    assert syn == [{"kind": "synapse", "count": 1}]


async def test_unreact_no_existing_204(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    author_token, article_id = await _published_article(
        client, db_session, section_slug="rr3"
    )
    resp = await client.delete(
        f"/api/v1/articles/{article_id}/reactions/neuron",
        headers={"Authorization": f"Bearer {author_token}"},
    )
    assert resp.status_code == 204


# ---------------------------------------------------------------------------
# Message reactions
# ---------------------------------------------------------------------------


async def test_react_and_list_message(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    author_token, article_id = await _published_article(
        client, db_session, section_slug="rr4"
    )
    msg = await client.post(
        f"/api/v1/articles/{article_id}/messages",
        json={"content": _doc("hi")},
        headers={"Authorization": f"Bearer {author_token}"},
    )
    msg_id = msg.json()["id"]
    resp = await client.post(
        f"/api/v1/messages/{msg_id}/reactions",
        json={"kind": "dna"},
        headers={"Authorization": f"Bearer {author_token}"},
    )
    assert resp.status_code == 204
    listing = await client.get(f"/api/v1/messages/{msg_id}/reactions")
    assert listing.status_code == 200
    assert listing.json() == [{"kind": "dna", "count": 1}]


async def test_unreact_message(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    author_token, article_id = await _published_article(
        client, db_session, section_slug="rr5"
    )
    msg = await client.post(
        f"/api/v1/articles/{article_id}/messages",
        json={"content": _doc("hi")},
        headers={"Authorization": f"Bearer {author_token}"},
    )
    msg_id = msg.json()["id"]
    await client.post(
        f"/api/v1/messages/{msg_id}/reactions",
        json={"kind": "mindblown"},
        headers={"Authorization": f"Bearer {author_token}"},
    )
    resp = await client.delete(
        f"/api/v1/messages/{msg_id}/reactions/mindblown",
        headers={"Authorization": f"Bearer {author_token}"},
    )
    assert resp.status_code == 204
    listing = (await client.get(
        f"/api/v1/messages/{msg_id}/reactions"
    )).json()
    assert listing == []
