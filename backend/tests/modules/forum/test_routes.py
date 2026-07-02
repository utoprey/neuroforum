"""Route-level tests for the ``forum`` module."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token


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


async def test_admin_creates_section_201(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, token = await _register(client, "adm1", db_session, role="admin")
    resp = await client.post(
        "/api/v1/sections",
        json={"title": "fMRI", "slug": "fmri"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["slug"] == "fmri"
    assert body["title"] == "fMRI"


async def test_user_create_section_403(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, token = await _register(client, "user1", db_session)
    resp = await client.post(
        "/api/v1/sections",
        json={"title": "X", "slug": "x"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_anonymous_create_section_401(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/sections", json={"title": "X"})
    assert resp.status_code == 401


async def test_list_sections_anonymous(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, token = await _register(client, "adm2", db_session, role="admin")
    await client.post(
        "/api/v1/sections",
        json={"title": "A", "slug": "a", "position": 2},
        headers={"Authorization": f"Bearer {token}"},
    )
    await client.post(
        "/api/v1/sections",
        json={"title": "B", "slug": "b", "position": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    resp = await client.get("/api/v1/sections")
    assert resp.status_code == 200
    slugs = [s["slug"] for s in resp.json()]
    assert slugs == ["b", "a"]


async def test_create_topic_and_list(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, admin_token = await _register(client, "adm3", db_session, role="admin")
    _, mod_token = await _register(client, "mod1", db_session, role="moderator")
    _, user_token = await _register(client, "user2", db_session)

    # Admin creates section.
    await client.post(
        "/api/v1/sections",
        json={"title": "DTI", "slug": "dti"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    # Regular user CAN create discussion/help/flood topics …
    ok = await client.post(
        "/api/v1/sections/dti/topics",
        json={"title": "User topic", "kind": "discussion"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["kind"] == "discussion"

    # … but NOT news topics.
    forbidden = await client.post(
        "/api/v1/sections/dti/topics",
        json={"title": "News topic", "kind": "news"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert forbidden.status_code == 403

    # Moderator creates two news topics with the same title — slug auto-collision.
    t1 = await client.post(
        "/api/v1/sections/dti/topics",
        json={"title": "Tractography", "kind": "news"},
        headers={"Authorization": f"Bearer {mod_token}"},
    )
    assert t1.status_code == 201, t1.text
    t2 = await client.post(
        "/api/v1/sections/dti/topics",
        json={"title": "Tractography", "kind": "news"},
        headers={"Authorization": f"Bearer {mod_token}"},
    )
    assert t2.status_code == 201
    assert t1.json()["slug"] == "tractography"
    assert t2.json()["slug"] == "tractography-2"
    assert t1.json()["kind"] == "news"

    # Listing visible to anonymous — user-created discussion + two mod-news.
    listing = await client.get("/api/v1/sections/dti/topics")
    assert listing.status_code == 200
    assert len(listing.json()) == 3

    # Filter by kind.
    only_news = await client.get(
        "/api/v1/sections/dti/topics", params={"kind": "news"}
    )
    assert only_news.status_code == 200
    assert {t["slug"] for t in only_news.json()} == {
        "tractography",
        "tractography-2",
    }
    only_discussion = await client.get(
        "/api/v1/sections/dti/topics", params={"kind": "discussion"}
    )
    assert only_discussion.status_code == 200
    assert [t["title"] for t in only_discussion.json()] == ["User topic"]


async def test_lock_topic(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, admin_token = await _register(client, "adm4", db_session, role="admin")
    await client.post(
        "/api/v1/sections",
        json={"title": "MEG", "slug": "meg"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    create = await client.post(
        "/api/v1/sections/meg/topics",
        json={"title": "Alpha rhythms"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    topic_id = create.json()["id"]

    lock = await client.post(
        f"/api/v1/topics/{topic_id}/lock",
        json={"locked": True},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert lock.status_code == 200
    assert lock.json()["is_locked"] is True


# ---------------------------------------------------------------------------
# Slug-based topic resolution
# ---------------------------------------------------------------------------


async def test_get_topic_by_section_and_topic_slug(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, admin_token = await _register(client, "adm_slug1", db_session, role="admin")
    await client.post(
        "/api/v1/sections",
        json={"title": "Connectomics", "slug": "connectomics"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    create = await client.post(
        "/api/v1/sections/connectomics/topics",
        json={
            "title": "Graph theory in fMRI",
            "slug": "graph-theory-fmri",
            "kind": "news",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert create.status_code == 201, create.text
    topic_id = create.json()["id"]

    resp = await client.get(
        "/api/v1/sections/connectomics/topics/graph-theory-fmri"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == topic_id
    assert body["slug"] == "graph-theory-fmri"
    assert body["section_slug"] == "connectomics"
    assert body["title"] == "Graph theory in fMRI"


async def test_get_topic_by_slug_unknown_section_404(
    client: AsyncClient,
) -> None:
    resp = await client.get(
        "/api/v1/sections/no-such-section/topics/some-topic"
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Section not found"


async def test_get_topic_by_slug_unknown_topic_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, admin_token = await _register(client, "adm_slug2", db_session, role="admin")
    await client.post(
        "/api/v1/sections",
        json={"title": "Sec", "slug": "sec-x"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    resp = await client.get("/api/v1/sections/sec-x/topics/missing-topic")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Topic not found"


async def test_topic_read_includes_section_slug_in_listings(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Every TopicRead returned by the API must carry ``section_slug`` so
    the frontend can build slug-based URLs from a single payload."""
    _, admin_token = await _register(client, "adm_slug3", db_session, role="admin")
    await client.post(
        "/api/v1/sections",
        json={"title": "EEG", "slug": "eeg"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    await client.post(
        "/api/v1/sections/eeg/topics",
        json={"title": "Alpha", "slug": "alpha-band", "kind": "news"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    listing = await client.get("/api/v1/sections/eeg/topics")
    assert listing.status_code == 200
    rows = listing.json()
    assert all(t["section_slug"] == "eeg" for t in rows)


async def test_list_topic_articles_by_slug(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, admin_token = await _register(client, "adm_slug4", db_session, role="admin")
    await client.post(
        "/api/v1/sections",
        json={"title": "Predictive Coding", "slug": "predictive-coding"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    create_topic = await client.post(
        "/api/v1/sections/predictive-coding/topics",
        json={
            "title": "Free energy",
            "slug": "free-energy",
            "kind": "news",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert create_topic.status_code == 201
    topic_id = create_topic.json()["id"]

    # Author posts a draft via the existing UUID-based route, then publishes.
    _, user_token = await _register(client, "author_slug", db_session)
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "Body"}],
            }
        ],
    }
    art = await client.post(
        f"/api/v1/topics/{topic_id}/articles",
        json={"title": "Hello PC", "content": doc},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert art.status_code == 201, art.text
    article_id = art.json()["id"]
    pub = await client.post(
        f"/api/v1/articles/{article_id}/publish",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert pub.status_code == 200, pub.text

    # New slug-based listing returns it.
    listing = await client.get(
        "/api/v1/sections/predictive-coding/topics/free-energy/articles"
    )
    assert listing.status_code == 200, listing.text
    ids = [a["id"] for a in listing.json()]
    assert article_id in ids


async def test_list_topic_articles_by_slug_unknown_section_404(
    client: AsyncClient,
) -> None:
    resp = await client.get(
        "/api/v1/sections/no-section/topics/no-topic/articles"
    )
    assert resp.status_code == 404
