"""Service-layer tests for the ``ai_proposals`` module."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agents.repository import AgentRepository
from app.modules.agents.schemas import AgentCredentialCreate
from app.modules.agents.service import AgentService
from app.modules.ai_proposals.exceptions import (
    NotAllowedToPropose,
    ProposalExpired,
    ProposalNotFound,
)
from app.modules.ai_proposals.models import (
    AIProposalAction,
    AIProposalStatus,
)
from app.modules.ai_proposals.repository import AIProposalRepository
from app.modules.ai_proposals.schemas import AIProposalCreate
from app.modules.ai_proposals.service import AIProposalService
from app.modules.articles.exceptions import ContentInvalid
from app.modules.articles.models import Article
from app.modules.articles.repository import ArticleRepository
from app.modules.articles.schemas import ArticleCreate
from app.modules.articles.service import ArticleService
from app.modules.content.schemas import DocSchema
from app.modules.forum.repository import ForumRepository
from app.modules.forum.schemas import SectionCreate, TopicCreate
from app.modules.forum.service import ForumService
from app.modules.users.models import Role, User
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import UserCreate
from app.modules.users.service import UserService

# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def users_svc(db_session: AsyncSession) -> UserService:
    return UserService(UserRepository(db_session), db_session)


@pytest.fixture
def forum_svc(db_session: AsyncSession) -> ForumService:
    return ForumService(ForumRepository(db_session), db_session)


@pytest.fixture
def articles_svc(db_session: AsyncSession) -> ArticleService:
    return ArticleService(
        ArticleRepository(db_session), ForumRepository(db_session), db_session
    )


@pytest.fixture
def proposals_svc(
    db_session: AsyncSession, articles_svc: ArticleService
) -> AIProposalService:
    return AIProposalService(
        AIProposalRepository(db_session), articles_svc, db_session
    )


async def _make_user(
    users_svc: UserService,
    db_session: AsyncSession,
    *,
    username: str,
    role: Role = Role.USER,
) -> User:
    user = await users_svc.create_user(
        UserCreate(
            username=username,
            email=f"{username}@aip.io",
            password=SecretStr("hunter22!"),
        )
    )
    if role is not Role.USER:
        await db_session.execute(
            text("UPDATE users SET role = :r WHERE id = :id"),
            {"r": role.value, "id": user.id},
        )
        await db_session.flush()
        await db_session.refresh(user)
    return user


def _doc(text_value: str = "Initial body") -> dict[str, object]:
    return {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text_value}],
            }
        ],
    }


async def _seed_article(
    *,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
    section_slug: str,
) -> tuple[User, Article]:
    admin = await _make_user(
        users_svc, db_session, username=f"admin_{section_slug}", role=Role.ADMIN
    )
    author = await _make_user(
        users_svc, db_session, username=f"author_{section_slug}"
    )
    await forum_svc.create_section(
        admin, SectionCreate(title=section_slug.upper(), slug=section_slug)
    )
    topic, _ = await forum_svc.create_topic(
        admin, section_slug, TopicCreate(title="T")
    )
    article, _ = await articles_svc.create_article(
        author,
        topic.id,
        ArticleCreate(
            title="Initial",
            content=DocSchema.model_validate(_doc("Initial body")),
        ),
    )
    published, _ = await articles_svc.publish_article(author, article.id)
    return author, published


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


async def test_create_proposal_happy_path_uses_stub_llm(
    proposals_svc: AIProposalService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    author, article = await _seed_article(
        articles_svc=articles_svc,
        forum_svc=forum_svc,
        users_svc=users_svc,
        db_session=db_session,
        section_slug="aip1",
    )
    proposal, requester = await proposals_svc.create_proposal(
        author,
        article.id,
        AIProposalCreate(action=AIProposalAction.SUMMARIZE, prompt="tl;dr"),
    )
    assert proposal.status == AIProposalStatus.PENDING
    assert proposal.action == AIProposalAction.SUMMARIZE
    assert proposal.expires_at > proposal.created_at
    # TTL is 3 days — give a 1-minute margin for clock noise.
    assert (proposal.expires_at - proposal.created_at) >= timedelta(days=3) - timedelta(minutes=1)
    assert requester.id == author.id


async def test_non_author_non_mod_cannot_propose(
    proposals_svc: AIProposalService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    _author, article = await _seed_article(
        articles_svc=articles_svc,
        forum_svc=forum_svc,
        users_svc=users_svc,
        db_session=db_session,
        section_slug="aip2",
    )
    randos = await _make_user(users_svc, db_session, username="random_aip2")
    with pytest.raises(NotAllowedToPropose):
        await proposals_svc.create_proposal(
            randos,
            article.id,
            AIProposalCreate(action=AIProposalAction.DRAFT),
        )


# ---------------------------------------------------------------------------
# Accept
# ---------------------------------------------------------------------------


async def test_accept_proposal_marks_status_and_does_not_modify_article(
    proposals_svc: AIProposalService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    """Accepting a proposal is a "useful" annotation — not a content overwrite.

    Original article.content stays intact, no new ArticleRevision is created,
    and the proposal row flips to ACCEPTED with decided_by / decided_at set.
    """
    author, article = await _seed_article(
        articles_svc=articles_svc,
        forum_svc=forum_svc,
        users_svc=users_svc,
        db_session=db_session,
        section_slug="aip3",
    )
    original_content = dict(article.content)
    original_content_text = article.content_text
    original_revisions = await articles_svc._repo.list_revisions(article.id)
    original_revisions_count = len(original_revisions)

    proposal, _ = await proposals_svc.create_proposal(
        author,
        article.id,
        AIProposalCreate(action=AIProposalAction.EXPAND, prompt="add detail"),
    )
    result = await proposals_svc.accept_proposal(author, proposal.id)

    # Status flipped + decided_by/at populated; result is the proposal itself.
    assert result.id == proposal.id
    assert result.status == AIProposalStatus.ACCEPTED
    assert result.decided_by == author.id
    assert result.decided_at is not None

    # Article body is UNCHANGED — no revision snapshot was taken.
    refetched = await articles_svc._repo.get_with_author(article.id)
    assert refetched is not None
    refetched_article, _ = refetched
    assert refetched_article.content == original_content
    assert refetched_article.content_text == original_content_text

    revisions = await articles_svc._repo.list_revisions(article.id)
    assert len(revisions) == original_revisions_count


async def test_reject_proposal_marks_rejected_and_stashes_reason(
    proposals_svc: AIProposalService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    author, article = await _seed_article(
        articles_svc=articles_svc,
        forum_svc=forum_svc,
        users_svc=users_svc,
        db_session=db_session,
        section_slug="aip4",
    )
    proposal, _ = await proposals_svc.create_proposal(
        author,
        article.id,
        AIProposalCreate(action=AIProposalAction.DRAFT),
    )
    rejected = await proposals_svc.reject_proposal(
        author, proposal.id, reason="prefer human draft"
    )
    assert rejected.status == AIProposalStatus.REJECTED
    assert rejected.decided_by == author.id
    assert (rejected.context or {}).get("reject_reason") == "prefer human draft"


async def test_accept_expired_proposal_rejected(
    proposals_svc: AIProposalService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    author, article = await _seed_article(
        articles_svc=articles_svc,
        forum_svc=forum_svc,
        users_svc=users_svc,
        db_session=db_session,
        section_slug="aip5",
    )
    proposal, _ = await proposals_svc.create_proposal(
        author,
        article.id,
        AIProposalCreate(action=AIProposalAction.DRAFT),
    )
    # Force expiration.
    proposal.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.flush()

    with pytest.raises(ProposalExpired):
        await proposals_svc.accept_proposal(author, proposal.id)


async def test_accept_by_non_author_non_mod_forbidden(
    proposals_svc: AIProposalService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    author, article = await _seed_article(
        articles_svc=articles_svc,
        forum_svc=forum_svc,
        users_svc=users_svc,
        db_session=db_session,
        section_slug="aip6",
    )
    proposal, _ = await proposals_svc.create_proposal(
        author,
        article.id,
        AIProposalCreate(action=AIProposalAction.DRAFT),
    )
    intruder = await _make_user(users_svc, db_session, username="intruder_aip6")
    with pytest.raises(NotAllowedToPropose):
        await proposals_svc.accept_proposal(intruder, proposal.id)


# ---------------------------------------------------------------------------
# Listing + cron
# ---------------------------------------------------------------------------


async def test_list_for_article_filters_by_status(
    proposals_svc: AIProposalService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    author, article = await _seed_article(
        articles_svc=articles_svc,
        forum_svc=forum_svc,
        users_svc=users_svc,
        db_session=db_session,
        section_slug="aip7",
    )
    p1, _ = await proposals_svc.create_proposal(
        author, article.id, AIProposalCreate(action=AIProposalAction.DRAFT)
    )
    p2, _ = await proposals_svc.create_proposal(
        author, article.id, AIProposalCreate(action=AIProposalAction.OUTLINE)
    )
    await proposals_svc.reject_proposal(author, p1.id)
    pending = await proposals_svc.list_for_article(
        author, article.id, status_filter=AIProposalStatus.PENDING
    )
    assert len(pending) == 1
    assert pending[0][0].id == p2.id


async def test_expire_pending_flips_overdue_rows(
    proposals_svc: AIProposalService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    author, article = await _seed_article(
        articles_svc=articles_svc,
        forum_svc=forum_svc,
        users_svc=users_svc,
        db_session=db_session,
        section_slug="aip8",
    )
    p1, _ = await proposals_svc.create_proposal(
        author, article.id, AIProposalCreate(action=AIProposalAction.DRAFT)
    )
    # Make p1 overdue, leave a fresh p2.
    p1.expires_at = datetime.now(UTC) - timedelta(hours=1)
    await db_session.flush()
    _p2, _ = await proposals_svc.create_proposal(
        author, article.id, AIProposalCreate(action=AIProposalAction.OUTLINE)
    )
    expired = await proposals_svc.expire_pending()
    assert expired == 1


async def test_accept_nonexistent_proposal_raises(
    proposals_svc: AIProposalService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    import uuid

    author = await _make_user(users_svc, db_session, username="lonely_aip9")
    with pytest.raises(ProposalNotFound):
        await proposals_svc.accept_proposal(author, uuid.uuid4())


# ---------------------------------------------------------------------------
# Real-LLM wiring (mocked caller)
# ---------------------------------------------------------------------------


async def test_create_proposal_calls_llm_when_credential_present(
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    """If the actor has an active credential, the LLM caller is invoked and
    its text lands inside ``proposed_content``.

    We bypass the real OpenRouter HTTP call by injecting a fake ``llm_caller``
    that records the args and returns canned text + usage meta.
    """
    author, article = await _seed_article(
        articles_svc=articles_svc,
        forum_svc=forum_svc,
        users_svc=users_svc,
        db_session=db_session,
        section_slug="aipllm",
    )

    # Wire an agent service so the proposal service can look up credentials.
    agent_repo = AgentRepository(db_session)
    user_repo = UserRepository(db_session)
    agent_svc = AgentService(agent_repo, user_repo, db_session)

    from app.modules.agents.models import LLMProvider

    await agent_svc.create_credential(
        author,
        AgentCredentialCreate(
            provider=LLMProvider.OPENROUTER,
            display_name="test-or",
            api_key=SecretStr("sk-test-fake-key"),
            default_model="anthropic/claude-haiku-4.5",
        ),
    )

    captured: dict[str, Any] = {}

    async def fake_caller(
        provider: str, api_key: str, model: str, prompt: str
    ) -> tuple[str, dict[str, Any]]:
        captured["provider"] = provider
        captured["api_key"] = api_key
        captured["model"] = model
        captured["prompt"] = prompt
        return (
            "TEST LLM RESPONSE — this is the model output.",
            {
                "input_tokens": 42,
                "output_tokens": 13,
                "cost_usd": Decimal("0.0001"),
                "duration_ms": 250,
            },
        )

    svc = AIProposalService(
        AIProposalRepository(db_session),
        articles_svc,
        db_session,
        agent_service=agent_svc,
        llm_caller=fake_caller,
    )

    proposal, _ = await svc.create_proposal(
        author,
        article.id,
        AIProposalCreate(
            action=AIProposalAction.SUMMARIZE, prompt="be brief"
        ),
    )

    assert captured["provider"] == "openrouter"
    assert captured["api_key"] == "sk-test-fake-key"
    assert captured["model"] == "anthropic/claude-haiku-4.5"
    # Prompt should include the action instruction + the article title.
    assert "резюме" in captured["prompt"]
    assert article.title in captured["prompt"]
    assert "be brief" in captured["prompt"]

    # The model's text made it into the proposed_content doc.
    body = proposal.proposed_content
    assert body["type"] == "doc"
    joined = " ".join(
        node.get("content", [{}])[0].get("text", "")
        for node in body["content"]
    )
    assert "TEST LLM RESPONSE" in joined

    # llm_meta was stashed in context for the route layer to expose.
    assert proposal.context is not None
    assert proposal.context.get("llm_meta", {}).get("model") == (
        "anthropic/claude-haiku-4.5"
    )


# ---------------------------------------------------------------------------
# Edit content (PATCH /ai-proposals/{id})
# ---------------------------------------------------------------------------


async def test_update_content_as_requester(
    proposals_svc: AIProposalService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    """The requester (= author of the article in our seed) can edit text."""
    author, article = await _seed_article(
        articles_svc=articles_svc,
        forum_svc=forum_svc,
        users_svc=users_svc,
        db_session=db_session,
        section_slug="aipupd1",
    )
    proposal, _ = await proposals_svc.create_proposal(
        author, article.id, AIProposalCreate(action=AIProposalAction.SUMMARIZE)
    )
    new_doc = _doc("Edited body — human-corrected resume.")
    updated = await proposals_svc.update_proposal_content(
        author, proposal.id, new_doc
    )
    assert updated.id == proposal.id
    assert updated.proposed_content == new_doc
    # Status / decided_* must NOT shift just because we edited text.
    assert updated.status == AIProposalStatus.PENDING
    assert updated.decided_by is None
    assert updated.decided_at is None


async def test_update_content_as_mod(
    proposals_svc: AIProposalService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    """A moderator can edit a proposal they did not request."""
    author, article = await _seed_article(
        articles_svc=articles_svc,
        forum_svc=forum_svc,
        users_svc=users_svc,
        db_session=db_session,
        section_slug="aipupd2",
    )
    proposal, _ = await proposals_svc.create_proposal(
        author, article.id, AIProposalCreate(action=AIProposalAction.DRAFT)
    )
    mod = await _make_user(
        users_svc, db_session, username="mod_aipupd2", role=Role.MODERATOR
    )
    new_doc = _doc("Moderator-corrected text.")
    updated = await proposals_svc.update_proposal_content(
        mod, proposal.id, new_doc
    )
    assert updated.proposed_content == new_doc


async def test_update_content_as_stranger_forbidden(
    proposals_svc: AIProposalService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    """A random unrelated user cannot edit the proposal."""
    author, article = await _seed_article(
        articles_svc=articles_svc,
        forum_svc=forum_svc,
        users_svc=users_svc,
        db_session=db_session,
        section_slug="aipupd3",
    )
    proposal, _ = await proposals_svc.create_proposal(
        author, article.id, AIProposalCreate(action=AIProposalAction.DRAFT)
    )
    stranger = await _make_user(users_svc, db_session, username="strange_aipupd3")
    with pytest.raises(NotAllowedToPropose):
        await proposals_svc.update_proposal_content(
            stranger, proposal.id, _doc("hostile edit")
        )


async def test_update_content_of_expired_rejected(
    proposals_svc: AIProposalService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    """Expired proposals refuse edits; rejected ones still accept them.

    Rejected text might still be worth fixing for transparency / reference,
    but an expired one has been retired by the cron worker and is read-only.
    """
    author, article = await _seed_article(
        articles_svc=articles_svc,
        forum_svc=forum_svc,
        users_svc=users_svc,
        db_session=db_session,
        section_slug="aipupd4",
    )
    # Build one we'll reject, one we'll expire.
    rej_proposal, _ = await proposals_svc.create_proposal(
        author, article.id, AIProposalCreate(action=AIProposalAction.DRAFT)
    )
    await proposals_svc.reject_proposal(author, rej_proposal.id, reason="meh")

    edited = await proposals_svc.update_proposal_content(
        author, rej_proposal.id, _doc("Reject-then-edit body.")
    )
    assert edited.proposed_content == _doc("Reject-then-edit body.")
    # Status stays rejected — editing is not "un-rejecting".
    assert edited.status == AIProposalStatus.REJECTED

    exp_proposal, _ = await proposals_svc.create_proposal(
        author, article.id, AIProposalCreate(action=AIProposalAction.OUTLINE)
    )
    # Force the expired status directly on the row so we test the service
    # behaviour, not the cron worker.
    exp_proposal.status = AIProposalStatus.EXPIRED
    await db_session.flush()
    with pytest.raises(ProposalExpired):
        await proposals_svc.update_proposal_content(
            author, exp_proposal.id, _doc("Too late to edit.")
        )


async def test_update_content_validates_doc(
    proposals_svc: AIProposalService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    """A malformed ProseMirror doc is rejected via ContentInvalid."""
    author, article = await _seed_article(
        articles_svc=articles_svc,
        forum_svc=forum_svc,
        users_svc=users_svc,
        db_session=db_session,
        section_slug="aipupd5",
    )
    proposal, _ = await proposals_svc.create_proposal(
        author, article.id, AIProposalCreate(action=AIProposalAction.SUMMARIZE)
    )
    bogus = {"type": "doc", "content": [{"type": "totally-not-a-block"}]}
    with pytest.raises(ContentInvalid):
        await proposals_svc.update_proposal_content(
            author, proposal.id, bogus
        )


async def test_update_content_missing_proposal_raises(
    proposals_svc: AIProposalService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    import uuid

    actor = await _make_user(users_svc, db_session, username="ghost_aipupd6")
    with pytest.raises(ProposalNotFound):
        await proposals_svc.update_proposal_content(
            actor, uuid.uuid4(), _doc("hi")
        )


async def test_create_proposal_falls_back_to_stub_without_credential(
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    """When the actor has no credential the service silently uses the stub."""
    author, article = await _seed_article(
        articles_svc=articles_svc,
        forum_svc=forum_svc,
        users_svc=users_svc,
        db_session=db_session,
        section_slug="aipstub",
    )

    agent_svc = AgentService(
        AgentRepository(db_session),
        UserRepository(db_session),
        db_session,
    )

    async def fake_caller(*args: Any, **kwargs: Any) -> tuple[str, dict[str, Any]]:
        raise AssertionError("LLM should not be called when no credential is set")

    svc = AIProposalService(
        AIProposalRepository(db_session),
        articles_svc,
        db_session,
        agent_service=agent_svc,
        llm_caller=fake_caller,
    )

    proposal, _ = await svc.create_proposal(
        author,
        article.id,
        AIProposalCreate(action=AIProposalAction.DRAFT),
    )

    # Stub doc still ends up with "[AI proposal stub" prefix.
    body = proposal.proposed_content
    joined = " ".join(
        node.get("content", [{}])[0].get("text", "")
        for node in body["content"]
    )
    assert "AI proposal stub" in joined
    # No llm_meta when stub is used.
    assert (proposal.context or {}).get("llm_meta") is None
