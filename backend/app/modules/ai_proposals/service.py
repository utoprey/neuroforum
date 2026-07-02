"""Service layer for the ``ai_proposals`` module."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agents import crypto as agent_crypto
from app.modules.agents.llm_proxy import LLMProxyError, call_provider
from app.modules.agents.models import LLMUsageStatus
from app.modules.agents.service import AgentService
from app.modules.ai_proposals.exceptions import (
    NotAllowedToPropose,
    ProposalAlreadyDecided,
    ProposalExpired,
    ProposalNotFound,
)
from app.modules.ai_proposals.models import (
    AIProposalAction,
    AIProposalStatus,
    ArticleAIProposal,
)
from app.modules.ai_proposals.repository import AIProposalRepository
from app.modules.ai_proposals.schemas import AIProposalCreate
from app.modules.articles.exceptions import ArticleNotFound, ContentInvalid
from app.modules.articles.models import Article
from app.modules.articles.service import ArticleService
from app.modules.content.schemas import DocSchema
from app.modules.content.utils import validate_doc
from app.modules.users.models import Role, User

log = logging.getLogger(__name__)

_MOD_OR_ADMIN: frozenset[Role] = frozenset({Role.MODERATOR, Role.ADMIN})

# TTL for pending proposals — see data-model.md.
_PROPOSAL_TTL = timedelta(days=3)

# Per-action instruction templates the LLM prepends to the article body.
ACTION_PROMPTS: dict[AIProposalAction, str] = {
    AIProposalAction.SUMMARIZE: (
        "Сделай краткое резюме статьи на русском (3-5 предложений)."
    ),
    AIProposalAction.REPHRASE: (
        "Перефразируй текст статьи, сохранив смысл, для лучшей читаемости."
    ),
    AIProposalAction.EXPAND: (
        "Расширь содержимое статьи: добавь детали, примеры, контекст."
    ),
    AIProposalAction.CITE_CHECK: (
        "Проверь статью на наличие ссылок и цитат. "
        "Перечисли что отсутствует и предложи источники."
    ),
    AIProposalAction.TRANSLATE: "Переведи статью на английский язык.",
    AIProposalAction.OUTLINE: (
        "Составь структурированный план (outline) для статьи."
    ),
    AIProposalAction.DRAFT: "Напиши черновик статьи на тему '{title}'.",
}

# Default model when the credential has no ``default_model``.
_DEFAULT_MODEL = "anthropic/claude-haiku-4.5"


# Type alias for the optional LLM client. Real impl returns a ProseMirror doc.
LLMClient = Callable[
    [AIProposalAction, str | None, dict[str, Any] | None],
    Awaitable[dict[str, Any]],
]

# Type alias for the low-level LLM caller (matches ``call_provider`` / a fake).
# Returns ``(text, usage_meta)`` where usage_meta carries cost+token info.
LLMCaller = Callable[[str, str, str], Awaitable[tuple[str, dict[str, Any]]]]


def _stub_llm_proposal(
    action: AIProposalAction,
    prompt: str | None,
    _selection: dict[str, Any] | None,
) -> dict[str, Any]:
    """MVP fallback when no real LLM is wired.

    Real implementation will call the user's configured agent + credential.
    For now we return a single-paragraph ProseMirror doc that explains what
    would have been generated — enough to exercise accept/reject flows in
    tests and the frontend.
    """
    body = f"[AI proposal stub for action={action.value}"
    if prompt:
        body += f", prompt={prompt!r}"
    body += "]"
    return {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": body}],
            }
        ],
    }


def _wrap_text_as_doc(text: str) -> dict[str, Any]:
    """Wrap an LLM-produced plain-text response in a minimal ProseMirror doc.

    LLM output is currently treated as one paragraph per line-block; we
    split on double newlines to preserve the visual paragraphing the
    model intended.
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [text or ""]
    return {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": p}],
            }
            for p in paragraphs
        ],
    }


def _build_prompt(
    action: AIProposalAction,
    article: Article,
    user_prompt: str | None,
) -> str:
    """Compose a full prompt from action instruction + article context."""
    instruction = ACTION_PROMPTS.get(action, "Помоги улучшить статью.")
    # ``DRAFT`` references {title} — render lazily so we don't KeyError when
    # the instruction doesn't actually format anything.
    try:
        instruction = instruction.format(title=article.title)
    except (KeyError, IndexError):
        pass

    parts = [instruction]
    parts.append(f"Заголовок: {article.title}")
    body = article.content_text or ""
    if body:
        parts.append(f"Текущий текст:\n{body}")
    if user_prompt:
        parts.append(f"Дополнительные пожелания: {user_prompt}")
    return "\n\n".join(parts)


class AIProposalService:
    """AI-assist suggestions on articles: create, list, accept, reject, expire."""

    def __init__(
        self,
        repo: AIProposalRepository,
        article_service: ArticleService,
        db: AsyncSession,
        *,
        agent_service: AgentService | None = None,
        llm_caller: LLMCaller | None = None,
    ) -> None:
        self._repo = repo
        self._articles = article_service
        self._db = db
        self._agent_service = agent_service
        # ``llm_caller`` overrides the real ``call_provider`` — used by tests
        # so we don't hit the network and skip the credential decryption.
        self._llm_caller = llm_caller

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def create_proposal(
        self,
        actor: User,
        article_id: UUID,
        payload: AIProposalCreate,
        llm_client: LLMClient | None = None,
    ) -> tuple[ArticleAIProposal, User]:
        """Generate a proposal for ``article_id``.

        Authoring permission mirrors article edit rules: actor must be the
        author, a moderator, or an admin. ``llm_client`` defaults to a stub
        for MVP — real callers inject a provider that uses the user's
        agent + credential.
        """
        article = await self._db.get(Article, article_id)
        if article is None:
            raise ArticleNotFound(str(article_id))

        is_author = actor.id == article.author_id
        is_mod = actor.role in _MOD_OR_ADMIN
        if not is_author and not is_mod:
            raise NotAllowedToPropose(
                "Only the author, a moderator, or an admin may propose"
            )

        selection_dict: dict[str, Any] | None = (
            payload.selection.model_dump(mode="json", by_alias=True)
            if payload.selection is not None
            else None
        )

        # Run the LLM call (or stub) to materialise the suggestion content.
        llm_meta: dict[str, Any] | None = None
        proposed_raw: dict[str, Any]
        if llm_client is not None:
            # Explicit injection wins — used in unit tests that want full
            # control over the proposed_content shape.
            proposed_raw = await llm_client(
                payload.action, payload.prompt, selection_dict
            )
        else:
            proposed_raw, llm_meta = await self._maybe_real_llm(
                actor, article, payload
            )

        # Validate the suggestion against the ProseMirror schema so a broken
        # client provider doesn't slip a bad doc into the DB.
        proposed_doc = DocSchema.model_validate(proposed_raw)

        now = datetime.now(UTC)
        context: dict[str, Any] = {}
        if llm_meta is not None:
            context["llm_meta"] = llm_meta
        proposal = ArticleAIProposal(
            article_id=article.id,
            requested_by=actor.id,
            agent_id=payload.agent_id,
            action=payload.action,
            selection=selection_dict,
            prompt=payload.prompt,
            context=context,
            proposed_content=proposed_doc.model_dump(mode="json"),
            status=AIProposalStatus.PENDING,
            created_at=now,
            expires_at=now + _PROPOSAL_TTL,
        )
        await self._repo.add(proposal)
        await self._db.refresh(proposal, attribute_names=("created_at",))
        return (proposal, actor)

    async def _maybe_real_llm(
        self,
        actor: User,
        article: Article,
        payload: AIProposalCreate,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """Try the real LLM via the actor's active credential; else fall back.

        Returns ``(proposed_raw, llm_meta)`` where ``llm_meta`` is non-None
        only if the LLM call (real or fake) succeeded. On any failure we
        return the stub doc with the error appended so the caller can still
        see SOMETHING and tests stay stable.
        """
        # No agent service wiring at all → MVP stub path (preserves old behaviour).
        if self._agent_service is None and self._llm_caller is None:
            return (
                _stub_llm_proposal(
                    payload.action,
                    payload.prompt,
                    payload.selection.model_dump(mode="json", by_alias=True)
                    if payload.selection is not None
                    else None,
                ),
                None,
            )

        # Resolve credential (if any) for this actor.
        credential = None
        if self._agent_service is not None:
            creds = await self._agent_service.list_my_credentials(actor)
            credential = next((c for c in creds if c.is_active), None)

        # Inject-mode (tests): the unit test wants the fake to be called even
        # when there's no credential. We synthesise a "no credential" path
        # that still exercises the LLMCaller.
        if credential is None and self._llm_caller is None:
            return (
                _stub_llm_proposal(
                    payload.action,
                    payload.prompt,
                    payload.selection.model_dump(mode="json", by_alias=True)
                    if payload.selection is not None
                    else None,
                ),
                None,
            )

        # Build prompt + pick model / provider / api_key.
        if credential is not None:
            try:
                api_key = agent_crypto.decrypt(credential.encrypted_api_key)
            except Exception as exc:  # pragma: no cover — corrupt key
                log.exception(
                    "ai_proposals: failed to decrypt credential %s",
                    credential.id,
                )
                return self._stub_with_error(payload, f"decrypt: {exc}"), None
            provider = credential.provider.value
            model = credential.default_model or _DEFAULT_MODEL
            credential_id = credential.id
        else:
            # Fake-only path (unit tests): use placeholder values so the
            # injected caller sees consistent inputs.
            api_key = ""
            provider = "openrouter"
            model = _DEFAULT_MODEL
            credential_id = None

        full_prompt = _build_prompt(payload.action, article, payload.prompt)

        caller: LLMCaller = self._llm_caller or call_provider  # type: ignore[assignment]

        try:
            text, usage = await caller(provider, api_key, model, full_prompt)
        except (LLMProxyError, NotImplementedError) as exc:
            log.warning("ai_proposals: LLM call failed: %s", exc)
            # Best-effort usage log so the user can see the failure in stats.
            if self._agent_service is not None and credential_id is not None:
                try:
                    await self._agent_service.log_usage(
                        credential_id=credential_id,
                        model=model,
                        input_tokens=0,
                        output_tokens=0,
                        cost=Decimal("0"),
                        status=LLMUsageStatus.ERROR,
                        proposal_id=None,
                        error=str(exc)[:1000],
                    )
                except Exception:  # pragma: no cover — accounting is best-effort
                    log.exception("ai_proposals: usage log on failure failed")
            return self._stub_with_error(payload, str(exc)), None
        except Exception as exc:
            log.exception("ai_proposals: unexpected LLM error")
            return self._stub_with_error(payload, str(exc)), None

        # Persist usage log so cost accounting stays accurate even when the
        # proposal isn't accepted later.
        if self._agent_service is not None and credential_id is not None:
            try:
                await self._agent_service.log_usage(
                    credential_id=credential_id,
                    model=model,
                    input_tokens=int(usage.get("input_tokens") or 0),
                    output_tokens=int(usage.get("output_tokens") or 0),
                    cost=Decimal(str(usage.get("cost_usd") or 0)),
                    status=LLMUsageStatus.SUCCESS,
                    duration_ms=usage.get("duration_ms"),
                )
            except Exception:  # pragma: no cover — accounting is best-effort
                log.exception("ai_proposals: usage log failed")

        llm_meta = {
            "model": model,
            "input_tokens": int(usage.get("input_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or 0),
            "cost_usd": str(usage.get("cost_usd") or 0),
            "duration_ms": usage.get("duration_ms"),
        }
        return _wrap_text_as_doc(text), llm_meta

    @staticmethod
    def _stub_with_error(
        payload: AIProposalCreate, error: str
    ) -> dict[str, Any]:
        """Fallback doc when a real LLM call failed — surfaces the error."""
        stub = _stub_llm_proposal(
            payload.action,
            payload.prompt,
            payload.selection.model_dump(mode="json", by_alias=True)
            if payload.selection is not None
            else None,
        )
        stub["content"].append(
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": f"[LLM call failed: {error}]"}
                ],
            }
        )
        return stub

    # ------------------------------------------------------------------
    # Listings
    # ------------------------------------------------------------------

    async def list_for_article(
        self,
        actor: User,
        article_id: UUID,
        *,
        status_filter: AIProposalStatus | None = None,
    ) -> list[tuple[ArticleAIProposal, User]]:
        article = await self._db.get(Article, article_id)
        if article is None:
            raise ArticleNotFound(str(article_id))
        # Accepted proposals = published AI insights — visible to any reader
        # who can see the article. Other statuses (pending/rejected/expired)
        # are management surface, restricted to author/mod/admin.
        if status_filter != AIProposalStatus.ACCEPTED:
            is_author = actor.id == article.author_id
            is_mod = actor.role in _MOD_OR_ADMIN
            if not is_author and not is_mod:
                raise NotAllowedToPropose(
                    "Only the author, a moderator, or an admin may list proposals"
                )
        return await self._repo.list_for_article(
            article_id, status_filter=status_filter
        )

    # ------------------------------------------------------------------
    # Decisions
    # ------------------------------------------------------------------

    async def _load_for_decision(
        self, actor: User, proposal_id: UUID
    ) -> ArticleAIProposal:
        proposal = await self._repo.get(proposal_id)
        if proposal is None:
            raise ProposalNotFound(str(proposal_id))
        if proposal.status != AIProposalStatus.PENDING:
            if proposal.status == AIProposalStatus.EXPIRED:
                raise ProposalExpired(str(proposal_id))
            raise ProposalAlreadyDecided(str(proposal_id))

        # Permission: same as create — author / mod / admin.
        article = await self._db.get(Article, proposal.article_id)
        if article is None:
            raise ArticleNotFound(str(proposal.article_id))
        is_author = actor.id == article.author_id
        is_mod = actor.role in _MOD_OR_ADMIN
        if not is_author and not is_mod:
            raise NotAllowedToPropose(
                "Only the author, a moderator, or an admin may decide"
            )

        # Lazy TTL: if expired but not yet flagged, raise here so accept/
        # reject behave consistently with the cron worker.
        if proposal.expires_at < datetime.now(UTC):
            proposal.status = AIProposalStatus.EXPIRED
            await self._db.flush()
            raise ProposalExpired(str(proposal_id))

        return proposal

    async def accept_proposal(
        self, actor: User, proposal_id: UUID
    ) -> ArticleAIProposal:
        """Mark a proposal as accepted (annotation, NOT a content overwrite).

        The original article.content is left untouched and no ArticleRevision
        is created. Accepting just records that the author / moderator found
        the suggestion useful. If they want to apply the text, they can copy
        ``proposal.proposed_content`` into the editor manually via the
        "Скопировать в редактор" UI action.
        """
        proposal = await self._load_for_decision(actor, proposal_id)
        proposal.status = AIProposalStatus.ACCEPTED
        proposal.decided_by = actor.id
        proposal.decided_at = datetime.now(UTC)
        await self._db.flush()
        return proposal

    async def reject_proposal(
        self,
        actor: User,
        proposal_id: UUID,
        reason: str | None = None,
    ) -> ArticleAIProposal:
        proposal = await self._load_for_decision(actor, proposal_id)
        proposal.status = AIProposalStatus.REJECTED
        proposal.decided_by = actor.id
        proposal.decided_at = datetime.now(UTC)
        if reason:
            # Stash the reason inside the context blob so we don't need a
            # dedicated column.
            new_context = dict(proposal.context or {})
            new_context["reject_reason"] = reason
            proposal.context = new_context
        await self._db.flush()
        return proposal

    async def expire_pending(self) -> int:
        """Cron entry point: flip every overdue pending proposal to expired."""
        return await self._repo.expire_pending()

    # ------------------------------------------------------------------
    # Edit content
    # ------------------------------------------------------------------

    async def update_proposal_content(
        self,
        actor: User,
        proposal_id: UUID,
        new_content: dict[str, Any],
    ) -> ArticleAIProposal:
        """Update ``proposed_content`` of an existing proposal.

        Allowed when:
        - Status is ``PENDING``, ``ACCEPTED``, or ``REJECTED`` (not
          ``EXPIRED`` — too stale to edit, the cron worker has already
          retired it).
        - Actor is ``requested_by`` OR a moderator / admin.

        The content is validated via ``content.validate_doc`` and re-saved.
        Does NOT change ``status`` or ``decided_by`` / ``decided_at`` — this
        is a content correction, not a new decision.
        """
        proposal = await self._repo.get(proposal_id)
        if proposal is None:
            raise ProposalNotFound(str(proposal_id))
        if proposal.status == AIProposalStatus.EXPIRED:
            raise ProposalExpired(str(proposal_id))

        is_requester = actor.id == proposal.requested_by
        is_mod = actor.role in _MOD_OR_ADMIN
        if not is_requester and not is_mod:
            raise NotAllowedToPropose(
                "Only the requester, a moderator, or an admin may edit a proposal"
            )

        try:
            validate_doc(new_content)
        except Exception as exc:
            raise ContentInvalid(str(exc)) from exc

        proposal.proposed_content = new_content
        await self._db.flush()
        await self._db.refresh(proposal)
        return proposal


__all__ = ["ACTION_PROMPTS", "AIProposalService", "LLMCaller", "LLMClient"]
