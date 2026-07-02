"""Tool implementations exposed by the Neuroforum MCP server.

Each ``@mcp_app.tool()`` runs inside its own short-lived
:class:`AsyncSession` (we don't share sessions across tool calls — that's
both safer for concurrent invocations and keeps the transactional scope
trivial). The authenticated agent is read from
:func:`app.mcp_server.auth.get_current_agent` rather than passed as an
argument so the JSON-Schema MCP exposes to clients doesn't grow phantom
parameters.

Returned shapes are deliberately plain ``dict[str, Any]`` (not Pydantic
models) — the MCP wire format is JSON, and the FastMCP runtime can
serialise plain dicts without an extra ``model_dump`` round trip.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from app.core.db import AsyncSessionLocal
from app.mcp_server.auth import get_current_agent, require_scope
from app.modules.agents.llm_proxy import LLMProxyError, call_provider
from app.modules.agents.models import LLMUsageStatus
from app.modules.agents.repository import AgentRepository
from app.modules.agents.service import AgentService
from app.modules.articles.exceptions import ArticleNotFound
from app.modules.articles.repository import ArticleRepository
from app.modules.articles.schemas import ArticleCreate
from app.modules.articles.service import ArticleService
from app.modules.content.schemas import DocSchema
from app.modules.forum.repository import ForumRepository
from app.modules.forum.service import ForumService
from app.modules.mentions.repository import MentionRepository
from app.modules.mentions.service import MentionService
from app.modules.messages.repository import MessageRepository
from app.modules.messages.schemas import MessageCreate
from app.modules.messages.service import MessageService
from app.modules.notifications.repository import NotificationRepository
from app.modules.notifications.service import NotificationService
from app.modules.search.postgres import PostgresSearchEngine
from app.modules.users.repository import UserRepository
from app.modules.users.service import UserService

if TYPE_CHECKING:  # pragma: no cover
    from mcp.server.fastmcp import FastMCP

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _doc_from_input(content: Any) -> DocSchema:
    """Accept either a raw ProseMirror dict OR a plain string.

    Plain strings are wrapped into a minimal ``doc`` with one paragraph
    node so LLM agents can post comments without knowing the full
    ProseMirror schema.
    """
    if isinstance(content, str):
        # Trivial paragraph wrapper — matches what the frontend editor
        # would produce for a single-line message.
        return DocSchema.model_validate(
            {
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": content}],
                    }
                ],
            }
        )
    if isinstance(content, dict):
        return DocSchema.model_validate(content)
    raise ValueError(
        "content must be either a string or a ProseMirror doc dict"
    )


# ---------------------------------------------------------------------------
# Public registration
# ---------------------------------------------------------------------------


def register_tools(mcp_app: FastMCP) -> None:
    """Attach all Neuroforum tools to ``mcp_app``.

    Called once from :mod:`app.mcp_server.server` after the FastMCP
    instance is created. Splitting registration into a function (rather
    than top-level decorators) lets tests build their own FastMCP instance
    without importing this module's side effects.
    """

    @mcp_app.tool()
    async def search(
        query: str,
        type: Literal["articles", "messages", "users", "all"] = "all",
        limit: int = 10,
    ) -> dict[str, list[dict[str, Any]]]:
        """Full-text + fuzzy search across the forum.

        Args:
            query: Free-text search query (Russian and English both work).
            type:  Restrict to ``articles`` / ``messages`` / ``users``, or
                   ``all`` to fan out across all three.
            limit: Per-category result cap (1..50).
        Returns:
            A dict like ``{"articles": [...], "messages": [...], "users": [...]}``
            where the omitted categories are absent.
        """
        require_scope("search")
        limit = max(1, min(int(limit), 50))
        out: dict[str, list[dict[str, Any]]] = {}
        async with AsyncSessionLocal() as session:
            engine = PostgresSearchEngine(session)
            if type in ("articles", "all"):
                hits = await engine.search_articles(query, limit)
                out["articles"] = [
                    {
                        "id": str(h.article.id),
                        "title": h.article.title,
                        "slug": h.article.slug,
                        "topic_id": str(h.article.topic_id),
                        "summary": h.article.summary,
                        "snippet": h.snippet,
                        "rank": h.rank,
                    }
                    for h in hits
                ]
            if type in ("messages", "all"):
                m_hits = await engine.search_messages(query, limit)
                out["messages"] = [
                    {
                        "message_id": str(h.message_id),
                        "article_id": str(h.article_id),
                        "snippet": h.snippet,
                        "rank": h.rank,
                    }
                    for h in m_hits
                ]
            if type in ("users", "all"):
                u_hits = await engine.search_users(query, limit)
                out["users"] = [
                    {
                        "id": str(u.id),
                        "username": u.username,
                        "display_name": u.display_name,
                        "role": u.role.value,
                    }
                    for u in u_hits
                ]
        return out

    @mcp_app.tool()
    async def list_sections() -> list[dict[str, Any]]:
        """List all forum sections, ordered by position then title."""
        require_scope("search")
        async with AsyncSessionLocal() as session:
            svc = ForumService(ForumRepository(session), session)
            sections = await svc.list_sections()
            return [
                {
                    "id": str(s.id),
                    "slug": s.slug,
                    "title": s.title,
                    "description": s.description,
                    "position": s.position,
                    "icon": s.icon,
                }
                for s in sections
            ]

    @mcp_app.tool()
    async def list_topics(
        section_slug: str,
        kind: Literal["news", "discussion", "help", "flood"] | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List topics within ``section_slug`` (newest pinned first).

        Args:
            section_slug: Slug of the section (e.g. ``fmri``).
            kind:         Optional filter by topic kind.
            limit:        Max topics to return (1..200).
        """
        require_scope("search")
        from app.modules.forum.models import TopicKind

        kind_enum: TopicKind | None = TopicKind(kind) if kind else None
        async with AsyncSessionLocal() as session:
            svc = ForumService(ForumRepository(session), session)
            rows = await svc.list_topics_for_section(
                section_slug, kind=kind_enum, limit=limit
            )
            return [
                {
                    "id": str(topic.id),
                    "slug": topic.slug,
                    "title": topic.title,
                    "description": topic.description,
                    "kind": topic.kind.value,
                    "is_locked": topic.is_locked,
                    "is_pinned": topic.is_pinned,
                    "created_by": {
                        "id": str(author.id),
                        "username": author.username,
                    },
                }
                for topic, author in rows
            ]

    @mcp_app.tool()
    async def read_article(article_id: str) -> dict[str, Any]:
        """Fetch a full article (content + metadata).

        Args:
            article_id: UUID of the article.
        Raises:
            ValueError: If no article matches (including drafts the agent
                cannot see).
        """
        require_scope("article:read")
        agent = get_current_agent()
        async with AsyncSessionLocal() as session:
            article_svc = _build_article_service(session)
            user_repo = UserRepository(session)
            bot_user = await user_repo.get(agent.user_id)
            try:
                article, author = await article_svc.get_for_viewer(
                    UUID(article_id), bot_user
                )
            except ArticleNotFound as exc:
                raise ValueError(f"Article not found: {article_id}") from exc
            return {
                "id": str(article.id),
                "topic_id": str(article.topic_id),
                "slug": article.slug,
                "title": article.title,
                "summary": article.summary,
                "content": article.content,
                "content_text": article.content_text,
                "status": article.status.value,
                "published_at": (
                    article.published_at.isoformat()
                    if article.published_at
                    else None
                ),
                "view_count": article.view_count,
                "comment_count": article.comment_count,
                "reaction_counts": dict(article.reaction_counts or {}),
                "author": {
                    "id": str(author.id),
                    "username": author.username,
                    "role": author.role.value,
                },
                "created_at": article.created_at.isoformat(),
                "updated_at": article.updated_at.isoformat(),
            }

    @mcp_app.tool()
    async def review_article(article_id: str) -> dict[str, Any]:
        """Read an article plus context useful for an AI review.

        Same payload as :func:`read_article` but adds top-comment snippets
        so the agent can decide whether the article still has unanswered
        questions before drafting a review.
        """
        require_scope("article:read")
        agent = get_current_agent()
        async with AsyncSessionLocal() as session:
            article_svc = _build_article_service(session)
            user_repo = UserRepository(session)
            bot_user = await user_repo.get(agent.user_id)
            try:
                article, author = await article_svc.get_for_viewer(
                    UUID(article_id), bot_user
                )
            except ArticleNotFound as exc:
                raise ValueError(f"Article not found: {article_id}") from exc

            mr = MessageRepository(session)
            top = await mr.list_top_level_for_article(
                article.id, limit=5, offset=0
            )

        payload: dict[str, Any] = {
            "id": str(article.id),
            "topic_id": str(article.topic_id),
            "slug": article.slug,
            "title": article.title,
            "summary": article.summary,
            "content": article.content,
            "content_text": article.content_text,
            "status": article.status.value,
            "published_at": (
                article.published_at.isoformat()
                if article.published_at
                else None
            ),
            "view_count": article.view_count,
            "comment_count": article.comment_count,
            "reaction_counts": dict(article.reaction_counts or {}),
            "author": {
                "id": str(author.id),
                "username": author.username,
                "role": author.role.value,
            },
            "created_at": article.created_at.isoformat(),
            "updated_at": article.updated_at.isoformat(),
            "top_comments": [
                {
                    "id": str(msg.id),
                    "author_username": comment_author.username,
                    "snippet": (msg.content_text or "")[:200],
                    "created_at": msg.created_at.isoformat(),
                }
                for msg, comment_author in top
            ],
        }
        return payload

    @mcp_app.tool()
    async def create_article(
        topic_id: str,
        title: str,
        content: dict[str, Any] | str,
        summary: str | None = None,
    ) -> dict[str, Any]:
        """Create a draft article in ``topic_id`` authored by this agent.

        The article starts in ``draft`` status. Use :func:`publish_article`
        to move it to ``published`` so non-author viewers can see it.

        Args:
            topic_id: UUID of the parent topic.
            title:    Headline (1..300 chars).
            content:  ProseMirror doc dict OR a plain string (wrapped into
                      a single paragraph for convenience).
            summary:  Optional short blurb for listings.
        """
        require_scope("article:write")
        agent = get_current_agent()
        doc = _doc_from_input(content)
        async with AsyncSessionLocal() as session:
            article_svc = _build_article_service(session)
            user_repo = UserRepository(session)
            bot_user = await user_repo.get(agent.user_id)
            if bot_user is None:
                raise ValueError("Agent's bot user is missing — corrupted state")
            article, _author = await article_svc.create_article(
                bot_user,
                UUID(topic_id),
                ArticleCreate(title=title, summary=summary, content=doc),
            )
            await session.commit()
            return {
                "id": str(article.id),
                "topic_id": str(article.topic_id),
                "slug": article.slug,
                "title": article.title,
                "status": article.status.value,
                "created_at": article.created_at.isoformat(),
            }

    @mcp_app.tool()
    async def publish_article(article_id: str) -> dict[str, Any]:
        """Flip a draft article to ``published``. Author-only."""
        require_scope("article:write")
        agent = get_current_agent()
        async with AsyncSessionLocal() as session:
            article_svc = _build_article_service(session)
            user_repo = UserRepository(session)
            bot_user = await user_repo.get(agent.user_id)
            if bot_user is None:
                raise ValueError("Agent's bot user is missing — corrupted state")
            article, _author = await article_svc.publish_article(
                bot_user, UUID(article_id)
            )
            await session.commit()
            return {
                "id": str(article.id),
                "status": article.status.value,
                "published_at": (
                    article.published_at.isoformat()
                    if article.published_at
                    else None
                ),
            }

    @mcp_app.tool()
    async def post_comment(
        article_id: str,
        content: dict[str, Any] | str,
        parent_id: str | None = None,
    ) -> dict[str, Any]:
        """Post a top-level comment or a reply under ``article_id``.

        Args:
            article_id: UUID of the article. Must be published.
            content:    ProseMirror doc dict OR plain string.
            parent_id:  Optional UUID of the parent comment for a reply.
        """
        require_scope("comment:write")
        agent = get_current_agent()
        doc = _doc_from_input(content)
        async with AsyncSessionLocal() as session:
            msg_svc = _build_message_service(session)
            user_repo = UserRepository(session)
            bot_user = await user_repo.get(agent.user_id)
            if bot_user is None:
                raise ValueError("Agent's bot user is missing — corrupted state")
            payload = MessageCreate(
                content=doc,
                parent_id=UUID(parent_id) if parent_id else None,
            )
            message, _author = await msg_svc.post_message(
                bot_user, UUID(article_id), payload
            )
            await session.commit()
            return {
                "id": str(message.id),
                "article_id": str(message.article_id),
                "parent_id": (
                    str(message.parent_id) if message.parent_id else None
                ),
                "depth": message.depth,
                "status": message.status.value,
                "created_at": message.created_at.isoformat(),
            }

    @mcp_app.tool()
    async def llm_assist(
        prompt: str,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Forward a single prompt through the agent owner's BYO LLM key.

        Charges the owner's credential — the call is logged to
        ``llm_usage_log`` with the agent's id, the resolved model, and the
        upstream-reported cost.

        Args:
            prompt: Free-form user prompt.
            model:  Override the credential's ``default_model``. Required
                    if the credential has no default.
        Returns:
            ``{"text": "...", "model": "...", "input_tokens": N,
            "output_tokens": M, "cost_usd": "0.0012", "duration_ms": 854}``.
        """
        require_scope("llm:assist")
        agent = get_current_agent()
        if agent.credential_id is None:
            raise ValueError(
                "Agent has no LLM credential attached — owner must wire one"
            )

        async with AsyncSessionLocal() as session:
            svc = AgentService(
                AgentRepository(session), UserRepository(session), session
            )
            # Go through the repository so we skip the service-level
            # owner check — the bot owns its own credential transitively
            # via the agent record, and the actor here is the bot itself.
            credential = await AgentRepository(session).get_credential(
                agent.credential_id
            )
            if credential is None:
                raise ValueError(
                    f"Credential {agent.credential_id} not found "
                    "(may have been deleted)"
                )
            chosen_model = model or credential.default_model
            if not chosen_model:
                raise ValueError(
                    "No model specified and credential has no default_model"
                )

            api_key = svc.decrypt_api_key(credential)
            provider = credential.provider.value

            try:
                text, usage = await call_provider(
                    provider, api_key, chosen_model, prompt
                )
                status = LLMUsageStatus.SUCCESS
                error = None
            except NotImplementedError as exc:
                # cloud_ru and other not-yet-implemented providers.
                await svc.log_usage(
                    credential_id=credential.id,
                    agent_id=agent.user_id,
                    model=chosen_model,
                    input_tokens=0,
                    output_tokens=0,
                    cost=Decimal("0"),
                    status=LLMUsageStatus.ERROR,
                    error=str(exc),
                )
                await session.commit()
                raise
            except LLMProxyError as exc:
                await svc.log_usage(
                    credential_id=credential.id,
                    agent_id=agent.user_id,
                    model=chosen_model,
                    input_tokens=0,
                    output_tokens=0,
                    cost=Decimal("0"),
                    status=LLMUsageStatus.ERROR,
                    error=str(exc)[:1000],
                )
                await session.commit()
                raise ValueError(f"LLM call failed: {exc}") from exc

            await svc.log_usage(
                credential_id=credential.id,
                agent_id=agent.user_id,
                model=chosen_model,
                input_tokens=int(usage["input_tokens"]),
                output_tokens=int(usage["output_tokens"]),
                cost=Decimal(str(usage["cost_usd"])),
                status=status,
                duration_ms=int(usage["duration_ms"]),
                error=error,
            )
            await session.commit()

            return {
                "text": text,
                "model": chosen_model,
                "input_tokens": usage["input_tokens"],
                "output_tokens": usage["output_tokens"],
                "cost_usd": str(usage["cost_usd"]),
                "duration_ms": usage["duration_ms"],
            }


# ---------------------------------------------------------------------------
# Service-wiring helpers
# ---------------------------------------------------------------------------


def _build_article_service(session: Any) -> ArticleService:
    """Wire ``ArticleService`` with the same cross-module hooks the HTTP API uses."""
    repo = ArticleRepository(session)
    forum = ForumRepository(session)
    mentions = MentionService(MentionRepository(session), session)
    notifications = NotificationService(NotificationRepository(session), session)
    users = UserService(UserRepository(session), session)
    return ArticleService(
        repo,
        forum,
        session,
        mention_service=mentions,
        notification_service=notifications,
        user_service=users,
    )


def _build_message_service(session: Any) -> MessageService:
    repo = MessageRepository(session)
    mentions = MentionService(MentionRepository(session), session)
    notifications = NotificationService(NotificationRepository(session), session)
    return MessageService(
        repo,
        session,
        mention_service=mentions,
        notification_service=notifications,
    )


__all__ = ["register_tools"]
