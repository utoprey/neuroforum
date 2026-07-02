"""Route-level tests for the ``articles`` module."""

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


async def _bootstrap_section_topic(
    client: AsyncClient,
    db_session: AsyncSession,
    *,
    section_slug: str = "fmri",
) -> tuple[str, str]:
    """Returns (admin_token, topic_id). Creates a section + topic."""
    _, admin_token = await _register(client, f"adm_{section_slug}", db_session, role="admin")
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


async def test_create_article_201(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, topic_id = await _bootstrap_section_topic(client, db_session, section_slug="r1")
    _, user_token = await _register(client, "author1", db_session)
    resp = await client.post(
        f"/api/v1/topics/{topic_id}/articles",
        json={"title": "My Article", "content": _doc("Hi")},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "draft"
    assert body["title"] == "My Article"


async def test_create_article_requires_auth(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, topic_id = await _bootstrap_section_topic(client, db_session, section_slug="r2")
    resp = await client.post(
        f"/api/v1/topics/{topic_id}/articles",
        json={"title": "X", "content": _doc()},
    )
    assert resp.status_code == 401


async def test_draft_invisible_to_anon(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, topic_id = await _bootstrap_section_topic(client, db_session, section_slug="r3")
    _, user_token = await _register(client, "author2", db_session)
    create = await client.post(
        f"/api/v1/topics/{topic_id}/articles",
        json={"title": "Draft", "content": _doc()},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    article_id = create.json()["id"]
    anon = await client.get(f"/api/v1/articles/{article_id}")
    assert anon.status_code == 404


async def test_publish_and_get_anonymous(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, topic_id = await _bootstrap_section_topic(client, db_session, section_slug="r4")
    _, user_token = await _register(client, "author3", db_session)
    create = await client.post(
        f"/api/v1/topics/{topic_id}/articles",
        json={"title": "Pub", "content": _doc()},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    article_id = create.json()["id"]
    pub = await client.post(
        f"/api/v1/articles/{article_id}/publish",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert pub.status_code == 200, pub.text
    assert pub.json()["status"] == "published"
    # Anonymous can now see it.
    get = await client.get(f"/api/v1/articles/{article_id}")
    assert get.status_code == 200


async def test_mod_edit_requires_reason(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, topic_id = await _bootstrap_section_topic(client, db_session, section_slug="r5")
    _, user_token = await _register(client, "author4", db_session)
    _, mod_token = await _register(client, "modr5", db_session, role="moderator")
    create = await client.post(
        f"/api/v1/topics/{topic_id}/articles",
        json={"title": "T", "content": _doc()},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    article_id = create.json()["id"]

    # No reason => 422
    bad = await client.patch(
        f"/api/v1/articles/{article_id}",
        json={"title": "Edited by mod"},
        headers={"Authorization": f"Bearer {mod_token}"},
    )
    assert bad.status_code == 422

    # With reason => 200
    ok = await client.patch(
        f"/api/v1/articles/{article_id}",
        json={"title": "Edited by mod", "edit_reason": "typo"},
        headers={"Authorization": f"Bearer {mod_token}"},
    )
    assert ok.status_code == 200
    assert ok.json()["title"] == "Edited by mod"


async def test_list_revisions_author_only(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, topic_id = await _bootstrap_section_topic(client, db_session, section_slug="r6")
    _, author_token = await _register(client, "author6", db_session)
    _, stranger_token = await _register(client, "stranger6", db_session)
    create = await client.post(
        f"/api/v1/topics/{topic_id}/articles",
        json={"title": "T", "content": _doc("v1")},
        headers={"Authorization": f"Bearer {author_token}"},
    )
    article_id = create.json()["id"]
    await client.patch(
        f"/api/v1/articles/{article_id}",
        json={"title": "T2"},
        headers={"Authorization": f"Bearer {author_token}"},
    )
    # Author can list.
    own = await client.get(
        f"/api/v1/articles/{article_id}/revisions",
        headers={"Authorization": f"Bearer {author_token}"},
    )
    assert own.status_code == 200
    assert len(own.json()) == 1
    # Stranger cannot.
    forbidden = await client.get(
        f"/api/v1/articles/{article_id}/revisions",
        headers={"Authorization": f"Bearer {stranger_token}"},
    )
    assert forbidden.status_code == 403


async def test_me_drafts(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, topic_id = await _bootstrap_section_topic(client, db_session, section_slug="r7")
    _, user_token = await _register(client, "author7", db_session)
    await client.post(
        f"/api/v1/topics/{topic_id}/articles",
        json={"title": "Draft A", "content": _doc()},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    pub = await client.post(
        f"/api/v1/topics/{topic_id}/articles",
        json={"title": "Pub B", "content": _doc()},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    pub_id = pub.json()["id"]
    await client.post(
        f"/api/v1/articles/{pub_id}/publish",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    drafts = await client.get(
        "/api/v1/me/drafts",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert drafts.status_code == 200
    titles = {d["title"] for d in drafts.json()}
    assert titles == {"Draft A"}


async def test_delete_article_as_author_204(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, topic_id = await _bootstrap_section_topic(client, db_session, section_slug="rd1")
    _, author_token = await _register(client, "author_del1", db_session)
    create = await client.post(
        f"/api/v1/topics/{topic_id}/articles",
        json={"title": "T", "content": _doc()},
        headers={"Authorization": f"Bearer {author_token}"},
    )
    article_id = create.json()["id"]
    # Publish so we can validate the GET-after-delete returns archived.
    await client.post(
        f"/api/v1/articles/{article_id}/publish",
        headers={"Authorization": f"Bearer {author_token}"},
    )
    deleted = await client.delete(
        f"/api/v1/articles/{article_id}",
        headers={"Authorization": f"Bearer {author_token}"},
    )
    assert deleted.status_code == 204, deleted.text
    # Soft-deleted: row still exists, status flipped to ``archived``.
    got = await client.get(
        f"/api/v1/articles/{article_id}",
        headers={"Authorization": f"Bearer {author_token}"},
    )
    assert got.status_code == 200
    assert got.json()["status"] == "archived"


async def test_delete_article_as_stranger_403(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, topic_id = await _bootstrap_section_topic(client, db_session, section_slug="rd2")
    _, author_token = await _register(client, "author_del2", db_session)
    _, stranger_token = await _register(client, "stranger_del2", db_session)
    create = await client.post(
        f"/api/v1/topics/{topic_id}/articles",
        json={"title": "T", "content": _doc()},
        headers={"Authorization": f"Bearer {author_token}"},
    )
    article_id = create.json()["id"]
    bad = await client.delete(
        f"/api/v1/articles/{article_id}",
        headers={"Authorization": f"Bearer {stranger_token}"},
    )
    assert bad.status_code == 403


async def test_hard_delete_as_user_403(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, topic_id = await _bootstrap_section_topic(client, db_session, section_slug="rd3")
    _, author_token = await _register(client, "author_del3", db_session)
    create = await client.post(
        f"/api/v1/topics/{topic_id}/articles",
        json={"title": "T", "content": _doc()},
        headers={"Authorization": f"Bearer {author_token}"},
    )
    article_id = create.json()["id"]
    # Even the author cannot hard-delete — that's admin-only.
    bad = await client.delete(
        f"/api/v1/articles/{article_id}?hard=true",
        headers={"Authorization": f"Bearer {author_token}"},
    )
    assert bad.status_code == 403


async def test_hard_delete_as_admin_204_and_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, topic_id = await _bootstrap_section_topic(client, db_session, section_slug="rd4")
    _, author_token = await _register(client, "author_del4", db_session)
    _, admin_token = await _register(client, "admin_del4", db_session, role="admin")
    create = await client.post(
        f"/api/v1/topics/{topic_id}/articles",
        json={"title": "T", "content": _doc()},
        headers={"Authorization": f"Bearer {author_token}"},
    )
    article_id = create.json()["id"]
    gone = await client.delete(
        f"/api/v1/articles/{article_id}?hard=true",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert gone.status_code == 204, gone.text
    # Row is physically gone — GET returns 404.
    missing = await client.get(f"/api/v1/articles/{article_id}")
    assert missing.status_code == 404


async def test_list_for_topic_status_filter(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, topic_id = await _bootstrap_section_topic(client, db_session, section_slug="r8")
    _, user_token = await _register(client, "author8", db_session)
    # One draft, one published.
    await client.post(
        f"/api/v1/topics/{topic_id}/articles",
        json={"title": "Draft", "content": _doc()},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    pub_resp = await client.post(
        f"/api/v1/topics/{topic_id}/articles",
        json={"title": "Pub", "content": _doc()},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    pub_id = pub_resp.json()["id"]
    await client.post(
        f"/api/v1/articles/{pub_id}/publish",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    # Default ``status=published``.
    listing = await client.get(f"/api/v1/topics/{topic_id}/articles")
    assert listing.status_code == 200
    titles = {a["title"] for a in listing.json()}
    assert titles == {"Pub"}
