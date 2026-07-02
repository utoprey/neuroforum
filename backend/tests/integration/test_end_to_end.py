"""End-to-end cross-module integration tests.

These exercise the public HTTP surface (no direct service-layer calls) so we
catch wiring regressions: a route here pokes another module's service, which
hits the DB, which triggers a cross-module hook (mention -> notification),
and the next route observes the side effect.

Every test uses a unique username/section prefix so the same Postgres
container can host them in parallel without slug collisions even though
each individual test rolls back at the SAVEPOINT level via ``db_session``.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _unique(prefix: str) -> str:
    """Stable-but-unique slug/username fragment."""
    return f"{prefix}{uuid.uuid4().hex[:8]}"


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


def _doc_with_mention(text_value: str, user_id: str) -> dict[str, object]:
    return {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": text_value},
                    {"type": "mention", "attrs": {"user_id": user_id}},
                ],
            }
        ],
    }


async def _register(
    client: AsyncClient,
    username: str,
    *,
    db_session: AsyncSession | None = None,
    role: str | None = None,
) -> tuple[str, str]:
    """Register a user and return ``(user_id, access_token)``.

    If ``role`` is given, also bumps the row in the DB (raw UPDATE).
    The token bakes the elevated role in its claims so route-level
    permission checks pass without round-tripping through /auth/login.
    """
    resp = await client.post(
        "/api/v1/users/",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": "hunter22!",
        },
    )
    assert resp.status_code == 201, resp.text
    user_id = resp.json()["id"]
    if role and db_session is not None:
        await db_session.execute(
            text("UPDATE users SET role = :r WHERE id = :id"),
            {"r": role, "id": user_id},
        )
        await db_session.commit()
    token = create_access_token(sub=user_id, extra={"role": role or "user"})
    return user_id, token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Scenario 1 — full happy path: section → topic → article → reactions/comments/save
# ---------------------------------------------------------------------------


async def test_full_happy_path(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    alice_name = _unique("alice")
    bob_name = _unique("bob")

    alice_id, alice_token = await _register(
        client, alice_name, db_session=db_session, role="admin"
    )
    bob_id, bob_token = await _register(client, bob_name, db_session=db_session)

    # --- Login as Alice via /auth/login to exercise the auth route too ----
    login = await client.post(
        "/api/v1/auth/login",
        json={"username_or_email": alice_name, "password": "hunter22!"},
    )
    assert login.status_code == 200, login.text
    assert login.json()["access_token"]

    # --- Alice creates a section ------------------------------------------
    section_slug = _unique("compneuro")
    sec = await client.post(
        "/api/v1/sections",
        json={"title": "Computational Neuroscience", "slug": section_slug},
        headers=_auth(alice_token),
    )
    assert sec.status_code == 201, sec.text

    # --- Alice creates a topic --------------------------------------------
    topic_slug = _unique("predcoding")
    topic = await client.post(
        f"/api/v1/sections/{section_slug}/topics",
        json={"title": "Predictive Coding", "slug": topic_slug},
        headers=_auth(alice_token),
    )
    assert topic.status_code == 201, topic.text
    topic_id = topic.json()["id"]

    # --- Bob writes a draft article ---------------------------------------
    art = await client.post(
        f"/api/v1/topics/{topic_id}/articles",
        json={"title": "Bayesian brain", "content": _doc("Predictive coding ftw")},
        headers=_auth(bob_token),
    )
    assert art.status_code == 201, art.text
    article_id = art.json()["id"]
    assert art.json()["status"] == "draft"

    # --- Bob publishes ----------------------------------------------------
    pub = await client.post(
        f"/api/v1/articles/{article_id}/publish",
        headers=_auth(bob_token),
    )
    assert pub.status_code == 200, pub.text
    assert pub.json()["status"] == "published"

    # --- Bob fetches his now-published article ----------------------------
    got = await client.get(
        f"/api/v1/articles/{article_id}", headers=_auth(bob_token)
    )
    assert got.status_code == 200
    assert got.json()["status"] == "published"

    # --- Alice reacts with brain ------------------------------------------
    react = await client.post(
        f"/api/v1/articles/{article_id}/reactions",
        json={"kind": "brain"},
        headers=_auth(alice_token),
    )
    assert react.status_code == 204, react.text

    # --- Alice comments on the article ------------------------------------
    cmt = await client.post(
        f"/api/v1/articles/{article_id}/messages",
        json={"content": _doc("Nice writeup!")},
        headers=_auth(alice_token),
    )
    assert cmt.status_code == 201, cmt.text
    alice_msg_id = cmt.json()["id"]

    # --- Bob replies to Alice's comment -----------------------------------
    reply = await client.post(
        f"/api/v1/articles/{article_id}/messages",
        json={"content": _doc("Thanks!"), "parent_id": alice_msg_id},
        headers=_auth(bob_token),
    )
    assert reply.status_code == 201, reply.text
    assert reply.json()["parent_id"] == alice_msg_id
    assert reply.json()["depth"] == 1

    # --- Alice saves the article ------------------------------------------
    save = await client.post(
        f"/api/v1/me/saved/{article_id}", headers=_auth(alice_token)
    )
    assert save.status_code == 204, save.text

    # --- Bob's saved list is empty; Alice's has 1 -------------------------
    bob_saved = await client.get("/api/v1/me/saved", headers=_auth(bob_token))
    assert bob_saved.status_code == 200
    assert bob_saved.json() == []

    alice_saved = await client.get(
        "/api/v1/me/saved", headers=_auth(alice_token)
    )
    assert alice_saved.status_code == 200
    saved_payload = alice_saved.json()
    assert len(saved_payload) == 1
    assert saved_payload[0]["article_id"] == article_id

    # --- Bob has no notifications (no mentions, no replies-to-him hook) ---
    bob_notifs = await client.get(
        "/api/v1/me/notifications", headers=_auth(bob_token)
    )
    assert bob_notifs.status_code == 200
    # The reply scenarios don't fire a "you got a reply" notification in
    # the current service layer (only mentions do), so the inbox is empty.
    assert bob_notifs.json() == []

    # Sanity: reaction count visible to anonymous reader.
    anon = await client.get(f"/api/v1/articles/{article_id}/reactions")
    assert anon.status_code == 200
    kinds = {r["kind"]: r["count"] for r in anon.json()}
    assert kinds.get("brain") == 1

    # Use ids in assertions so the linter doesn't flag them as unused.
    assert alice_id != bob_id


# ---------------------------------------------------------------------------
# Scenario 2 — mentions inside content trigger /me/mentions + /me/notifications
# ---------------------------------------------------------------------------


async def test_mentions_trigger_notifications(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    alice_name = _unique("alice")
    bob_name = _unique("bob")

    _alice_id, alice_token = await _register(
        client, alice_name, db_session=db_session, role="admin"
    )
    bob_id, bob_token = await _register(client, bob_name, db_session=db_session)

    section_slug = _unique("mentions")
    await client.post(
        "/api/v1/sections",
        json={"title": "Mentions", "slug": section_slug},
        headers=_auth(alice_token),
    )
    topic = await client.post(
        f"/api/v1/sections/{section_slug}/topics",
        json={"title": "Pinging"},
        headers=_auth(alice_token),
    )
    assert topic.status_code == 201
    topic_id = topic.json()["id"]

    art = await client.post(
        f"/api/v1/topics/{topic_id}/articles",
        json={
            "title": "Hi Bob",
            "content": _doc_with_mention("Hey ", bob_id),
        },
        headers=_auth(alice_token),
    )
    assert art.status_code == 201, art.text

    # Bob sees 1 mention.
    me_mentions = await client.get(
        "/api/v1/me/mentions", headers=_auth(bob_token)
    )
    assert me_mentions.status_code == 200, me_mentions.text
    body = me_mentions.json()
    assert len(body) == 1
    assert body[0]["source_type"] == "article"

    # Bob sees 1 notification of type='mention'.
    notifs = await client.get(
        "/api/v1/me/notifications", headers=_auth(bob_token)
    )
    assert notifs.status_code == 200
    notif_body = notifs.json()
    assert len(notif_body) == 1
    assert notif_body[0]["type"] == "mention"


# ---------------------------------------------------------------------------
# Scenario 3 — /users/search (trigram + prefix)
# ---------------------------------------------------------------------------


async def test_user_search_prefix_and_fuzzy(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    suffix = uuid.uuid4().hex[:6]
    johndoe = f"johndoe{suffix}"
    johndee = f"johndee{suffix}"
    jane = f"jane{suffix}"
    for name in (johndoe, johndee, jane):
        await _register(client, name, db_session=db_session)

    # @prefix search returns both johndoe* and johndee* (start with "john")
    prefix = await client.get(
        "/api/v1/users/search", params={"q": f"@john{suffix[:0]}"}
    )
    # Use a short prefix that still anchors on "john".
    prefix = await client.get("/api/v1/users/search", params={"q": "@john"})
    assert prefix.status_code == 200
    found = {u["username"] for u in prefix.json()}
    assert johndoe in found
    assert johndee in found
    assert jane not in found

    # Fuzzy search for jane.
    fuzzy = await client.get("/api/v1/users/search", params={"q": jane})
    assert fuzzy.status_code == 200
    names = {u["username"] for u in fuzzy.json()}
    assert jane in names


# ---------------------------------------------------------------------------
# Scenario 4 — RBAC enforcement on sections/topics/articles + role escalation
# ---------------------------------------------------------------------------


async def test_rbac_enforcement_and_role_change(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    alice_name = _unique("alice")
    bob_name = _unique("bob")

    _alice_id, alice_token = await _register(
        client, alice_name, db_session=db_session, role="admin"
    )
    bob_id, bob_token = await _register(client, bob_name, db_session=db_session)

    # Bob (plain user) can't create sections → 403.
    bad_section = await client.post(
        "/api/v1/sections",
        json={"title": "Nope", "slug": _unique("nope")},
        headers=_auth(bob_token),
    )
    assert bad_section.status_code == 403

    # Alice (admin) creates section + topic.
    section_slug = _unique("rbac")
    sec = await client.post(
        "/api/v1/sections",
        json={"title": "RBAC", "slug": section_slug},
        headers=_auth(alice_token),
    )
    assert sec.status_code == 201
    topic = await client.post(
        f"/api/v1/sections/{section_slug}/topics",
        json={"title": "T"},
        headers=_auth(alice_token),
    )
    assert topic.status_code == 201
    topic_id = topic.json()["id"]

    # Bob (plain user) can create discussion topics, but NOT news → 403.
    bad_topic = await client.post(
        f"/api/v1/sections/{section_slug}/topics",
        json={"title": "Nope", "kind": "news"},
        headers=_auth(bob_token),
    )
    assert bad_topic.status_code == 403
    ok_topic = await client.post(
        f"/api/v1/sections/{section_slug}/topics",
        json={"title": "Bob's discussion", "kind": "discussion"},
        headers=_auth(bob_token),
    )
    assert ok_topic.status_code == 201, ok_topic.text

    # Bob CAN create an article (any authed user) → 201.
    art = await client.post(
        f"/api/v1/topics/{topic_id}/articles",
        json={"title": "Bob's draft", "content": _doc()},
        headers=_auth(bob_token),
    )
    assert art.status_code == 201, art.text

    # Alice promotes Bob to moderator.
    promote = await client.post(
        f"/api/v1/moderation/users/{bob_id}/role",
        json={"role": "moderator"},
        headers=_auth(alice_token),
    )
    assert promote.status_code == 200, promote.text
    assert promote.json()["role"] == "moderator"

    # Reissue Bob's token with the new role baked in (claim-driven).
    new_bob_token = create_access_token(sub=bob_id, extra={"role": "moderator"})
    # Bob (now moderator) can create topics.
    ok_topic = await client.post(
        f"/api/v1/sections/{section_slug}/topics",
        json={"title": "Bob's topic", "slug": _unique("bobtopic")},
        headers=_auth(new_bob_token),
    )
    assert ok_topic.status_code == 201, ok_topic.text


# ---------------------------------------------------------------------------
# Scenario 5 — soft-delete by author yields placeholder + status flip
# ---------------------------------------------------------------------------


async def test_message_soft_delete_by_author_renders_placeholder(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    alice_name = _unique("alice")
    bob_name = _unique("bob")

    _alice_id, alice_token = await _register(
        client, alice_name, db_session=db_session, role="admin"
    )
    _bob_id, bob_token = await _register(
        client, bob_name, db_session=db_session
    )

    # Bootstrap section + topic + published article so Bob can post a message.
    section_slug = _unique("delsec")
    await client.post(
        "/api/v1/sections",
        json={"title": "Del", "slug": section_slug},
        headers=_auth(alice_token),
    )
    topic = await client.post(
        f"/api/v1/sections/{section_slug}/topics",
        json={"title": "T"},
        headers=_auth(alice_token),
    )
    topic_id = topic.json()["id"]
    art = await client.post(
        f"/api/v1/topics/{topic_id}/articles",
        json={"title": "A", "content": _doc()},
        headers=_auth(bob_token),
    )
    art_id = art.json()["id"]
    await client.post(
        f"/api/v1/articles/{art_id}/publish", headers=_auth(bob_token)
    )

    # Bob posts a comment.
    cmt = await client.post(
        f"/api/v1/articles/{art_id}/messages",
        json={"content": _doc("delete me please")},
        headers=_auth(bob_token),
    )
    assert cmt.status_code == 201, cmt.text
    msg_id = cmt.json()["id"]

    # Bob deletes his own comment.
    delr = await client.delete(
        f"/api/v1/messages/{msg_id}", headers=_auth(bob_token)
    )
    assert delr.status_code == 200, delr.text
    assert delr.json()["status"] == "deleted_by_author"
    assert delr.json()["content"] is None
    assert delr.json()["placeholder"]

    # Listing reflects the redacted state.
    listing = await client.get(f"/api/v1/articles/{art_id}/messages")
    assert listing.status_code == 200
    rows = listing.json()
    # The message we soft-deleted should still appear with a placeholder.
    target = next((r for r in rows if r["id"] == msg_id), None)
    assert target is not None
    assert target["status"] == "deleted_by_author"
    assert target["content"] is None
    assert target["placeholder"]
