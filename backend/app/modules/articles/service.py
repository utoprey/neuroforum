"""Article business logic: create / edit / publish + immutable revisions."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.articles.exceptions import (
    ArticleNotEditable,
    ArticleNotFound,
    MissingEditReason,
    SlugConflict,
)
from app.modules.articles.models import Article, ArticleRevision, ArticleStatus
from app.modules.articles.repository import ArticleRepository
from app.modules.articles.schemas import ArticleCreate, ArticleUpdate
from app.modules.content.schemas import DocSchema
from app.modules.content.utils import (
    extract_mentioned_user_ids,
    extract_plain_text,
)
from app.modules.forum.exceptions import TopicLocked, TopicNotFound
from app.modules.forum.repository import ForumRepository
from app.modules.forum.utils import make_slug
from app.modules.mentions.models import MentionSourceType
from app.modules.mentions.service import MentionService
from app.modules.notifications.service import NotificationService
from app.modules.rbac.exceptions import InsufficientRole
from app.modules.users.models import Role, User
from app.modules.users.service import UserService

_MOD_OR_ADMIN: frozenset[Role] = frozenset({Role.MODERATOR, Role.ADMIN})

_SLUG_COLLISION_RETRIES = 10


class ArticleService:
    """Orchestrates article CRUD with content validation + visibility rules."""

    def __init__(
        self,
        repo: ArticleRepository,
        forum: ForumRepository,
        db: AsyncSession,
        mention_service: MentionService | None = None,
        notification_service: NotificationService | None = None,
        user_service: UserService | None = None,
    ) -> None:
        self._repo = repo
        self._forum = forum
        self._db = db
        # Optional cross-module hooks. ``None`` keeps the service usable in
        # narrow unit tests (the existing 100+ tests pass nothing through).
        self._mentions = mention_service
        self._notifications = notification_service
        # Optional user lookup so notification payloads can carry the
        # author's display name. ``None`` falls back to plain ids.
        self._users = user_service

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def create_article(
        self, actor: User, topic_id: UUID, payload: ArticleCreate
    ) -> tuple[Article, User]:
        """Create a draft article in ``topic_id``. Any authed user may do this."""
        topic = await self._forum.get_topic(topic_id)
        if topic is None:
            raise TopicNotFound(str(topic_id))
        if topic.is_locked and actor.role not in _MOD_OR_ADMIN:
            raise TopicLocked(str(topic_id))

        doc = payload.content
        content_text = extract_plain_text(doc)
        mentioned = sorted(extract_mentioned_user_ids(doc))

        base_slug = payload.slug or make_slug(payload.title, max_length=180)
        slug = await self._allocate_slug(topic.id, base_slug)

        article = Article(
            topic_id=topic.id,
            slug=slug,
            title=payload.title,
            summary=payload.summary,
            # ``mode='json'`` turns nested UUIDs and other non-JSON-native
            # types into strings so asyncpg can encode the JSONB value.
            content=doc.model_dump(mode="json"),
            content_text=content_text,
            author_id=actor.id,
            status=ArticleStatus.DRAFT,
            mentioned_user_ids=mentioned,
        )
        await self._repo.add(article)

        # Cross-module fan-out: persist mention rows + emit notifications.
        if mentioned:
            await self._fan_out_mentions(article, actor, set(mentioned))
        return (article, actor)

    async def _fan_out_mentions(
        self,
        article: Article,
        actor: User,
        new_mention_ids: set[UUID],
    ) -> None:
        """Record new mention rows and emit ``type='mention'`` notifications.

        Both hooks are optional; if either DI param wasn't provided the
        respective step is silently skipped. ``record_mentions`` already
        deduplicates, so re-edits never double-notify.

        Notification payload is rich enough for the frontend to render a
        human-readable line ("@alice mentioned you in *Title*") + link to
        ``/articles/{article_id}``.
        """
        if not new_mention_ids or self._mentions is None:
            return
        new_rows = await self._mentions.record_mentions(
            MentionSourceType.ARTICLE,
            article.id,
            actor.id,
            new_mention_ids,
        )
        if not new_rows or self._notifications is None:
            return
        author_username = actor.username
        author_display_name = (
            actor.profile.display_name if actor.profile else None
        )
        snippet = (article.content_text or "")[:140]
        for mention in new_rows:
            payload = {
                "kind": "article_mention",
                "article_id": str(article.id),
                "article_title": article.title,
                "article_slug": article.slug,
                "topic_id": str(article.topic_id),
                "author_id": str(actor.id),
                "author_username": author_username,
                "author_display_name": author_display_name,
                "snippet": snippet,
            }
            await self._notifications.create_notification(
                user_id=mention.mentioned_user_id,
                type="mention",
                payload=payload,
            )

    async def _allocate_slug(self, topic_id: UUID, base: str) -> str:
        if await self._repo.get_by_topic_and_slug(topic_id, base) is None:
            return base
        for i in range(2, 2 + _SLUG_COLLISION_RETRIES):
            candidate = f"{base}-{i}"
            if (
                await self._repo.get_by_topic_and_slug(topic_id, candidate)
                is None
            ):
                return candidate
        raise SlugConflict(
            f"Could not allocate a free article slug for base {base!r}"
        )

    # ------------------------------------------------------------------
    # Read with visibility check
    # ------------------------------------------------------------------

    async def get_for_viewer(
        self, article_id: UUID, viewer: User | None
    ) -> tuple[Article, User]:
        """Return ``(article, author)`` honouring draft visibility.

        Drafts are visible only to the author, moderators, and admins.
        """
        row = await self._repo.get_with_author(article_id)
        if row is None:
            raise ArticleNotFound(str(article_id))
        article, author = row
        if not self._is_visible(article, viewer):
            raise ArticleNotFound(str(article_id))
        return (article, author)

    @staticmethod
    def _is_visible(article: Article, viewer: User | None) -> bool:
        if article.status != ArticleStatus.DRAFT:
            return True
        if viewer is None:
            return False
        if viewer.id == article.author_id:
            return True
        return viewer.role in _MOD_OR_ADMIN

    # ------------------------------------------------------------------
    # Publish
    # ------------------------------------------------------------------

    async def publish_article(
        self, actor: User, article_id: UUID
    ) -> tuple[Article, User]:
        row = await self._repo.get_with_author(article_id)
        if row is None:
            raise ArticleNotFound(str(article_id))
        article, author = row
        if actor.id != article.author_id and actor.role not in _MOD_OR_ADMIN:
            raise ArticleNotEditable("Only the author or a moderator may publish")
        # Only count the *first* publish — re-publishing an already-published
        # article (no-op in practice, but defensive) must not double-bump.
        was_published_before = article.status == ArticleStatus.PUBLISHED
        article.status = ArticleStatus.PUBLISHED
        article.published_at = datetime.now(UTC)
        await self._db.flush()
        await self._db.refresh(article, attribute_names=("updated_at",))
        if not was_published_before:
            await self._bump_author_articles_count(article.author_id, +1)
        return (article, author)

    async def _bump_author_articles_count(self, user_id: UUID, delta: int) -> None:
        """Atomic bump of ``user_stats.articles_count`` via UserRepository.

        Routed through ``UserRepository.increment_stat`` so the SQL lives in
        one place. We instantiate a thin repository over the current
        session rather than depend on the optional ``UserService`` DI so
        existing narrow unit tests (which pass ``user_service=None``)
        continue to update stats correctly.
        """
        from app.modules.users.repository import UserRepository

        await UserRepository(self._db).increment_stat(
            user_id, "articles_count", delta
        )

    # ------------------------------------------------------------------
    # Edit (with revision snapshot)
    # ------------------------------------------------------------------

    async def edit_article(
        self, actor: User, article_id: UUID, payload: ArticleUpdate
    ) -> tuple[Article, User]:
        row = await self._repo.get_with_author(article_id)
        if row is None:
            raise ArticleNotFound(str(article_id))
        article, author = row

        is_author = actor.id == article.author_id
        is_mod = actor.role in _MOD_OR_ADMIN
        if not is_author and not is_mod:
            raise ArticleNotEditable(
                "Only the author or a moderator/admin may edit this article"
            )
        # Moderator/admin who isn't the author must provide an explanation.
        edit_reason = payload.edit_reason
        if not is_author and not (edit_reason and edit_reason.strip()):
            raise MissingEditReason(
                "edit_reason is required when a moderator edits another user's article"
            )

        data = payload.model_dump(exclude_unset=True, exclude={"edit_reason"})
        new_content: DocSchema | None = data.pop("content", None) if "content" in data else None
        # ``model_dump(exclude_unset=True)`` returns the *dict form* of nested
        # pydantic models — for ``DocSchema`` that loses the DocSchema type.
        # Pull the typed value from the original payload instead.
        if "content" in payload.model_fields_set:
            new_content = payload.content
        new_title = data.get("title")
        new_summary = data.get("summary") if "summary" in data else None
        summary_changed = "summary" in payload.model_fields_set

        # --- Snapshot previous state into a revision row --------------------
        next_rev = await self._repo.max_revision_for_article(article.id) + 1
        revision = ArticleRevision(
            article_id=article.id,
            revision=next_rev,
            editor_id=actor.id,
            editor_role_at_edit=actor.role.value,
            title=article.title,
            content=article.content,
            edit_reason=edit_reason,
        )
        await self._repo.add_revision(revision)

        # --- Apply patch ----------------------------------------------------
        previous_mentions: set[UUID] = set(article.mentioned_user_ids or [])
        if new_title is not None:
            article.title = new_title
        if summary_changed:
            article.summary = new_summary
        if new_content is not None:
            article.content = new_content.model_dump(mode="json")
            article.content_text = extract_plain_text(new_content)
            article.mentioned_user_ids = sorted(
                extract_mentioned_user_ids(new_content)
            )
        await self._db.flush()
        await self._db.refresh(article, attribute_names=("updated_at",))

        # Fan out only NEW mentions (not in the prior revision).
        if new_content is not None:
            current_mentions: set[UUID] = set(article.mentioned_user_ids or [])
            newly_mentioned = current_mentions - previous_mentions
            if newly_mentioned:
                await self._fan_out_mentions(article, actor, newly_mentioned)
        return (article, author)

    # ------------------------------------------------------------------
    # Delete (soft / hard)
    # ------------------------------------------------------------------

    async def delete_article(
        self, actor: User, article_id: UUID, hard: bool = False
    ) -> None:
        """Delete an article.

        - Author or moderator/admin: soft delete (status -> ARCHIVED),
          row + content stay in the DB so revisions / saved-by-user remain
          referentially valid.
        - ``hard=True`` is admin-only and physically removes the row;
          messages, revisions, reactions and saved-pointers cascade away
          via their FKs.
        - Soft-deleting an already-archived article is an idempotent no-op
          (no second decrement of the author's published-articles counter).
        - If the article was ``PUBLISHED`` before this call, the author's
          ``user_stats.articles_count`` is decremented by 1.
        """
        row = await self._repo.get_with_author(article_id)
        if row is None:
            raise ArticleNotFound(str(article_id))
        article, _author = row

        is_author = actor.id == article.author_id
        is_mod_or_admin = actor.role in _MOD_OR_ADMIN
        is_admin = actor.role == Role.ADMIN

        if hard:
            if not is_admin:
                raise InsufficientRole("Only admins may hard-delete an article")
            # If the row was counted in the author's stats, drop it first
            # so the counter ends up consistent post-delete.
            if article.status == ArticleStatus.PUBLISHED:
                await self._bump_author_articles_count(article.author_id, -1)
            await self._repo.delete(article.id)
            await self._db.flush()
            return

        # --- soft path -------------------------------------------------
        if not is_author and not is_mod_or_admin:
            raise ArticleNotEditable(
                "Only the author or a moderator/admin may delete this article"
            )

        # Idempotent: archived already, nothing to do.
        if article.status == ArticleStatus.ARCHIVED:
            return

        was_published = article.status == ArticleStatus.PUBLISHED
        article.status = ArticleStatus.ARCHIVED
        await self._db.flush()
        await self._db.refresh(article, attribute_names=("updated_at",))

        if was_published:
            await self._bump_author_articles_count(article.author_id, -1)

    # ------------------------------------------------------------------
    # Listings
    # ------------------------------------------------------------------

    async def list_for_topic(
        self,
        topic_id: UUID,
        *,
        status: ArticleStatus | None = ArticleStatus.PUBLISHED,
        limit: int = 20,
        offset: int = 0,
    ) -> list[tuple[Article, User]]:
        return await self._repo.list_for_topic(
            topic_id,
            status=status,
            limit=max(1, min(limit, 100)),
            offset=max(0, offset),
        )

    async def list_drafts_for_user(
        self, user_id: UUID, *, limit: int = 20, offset: int = 0
    ) -> list[tuple[Article, User]]:
        return await self._repo.list_drafts_for_user(
            user_id,
            limit=max(1, min(limit, 100)),
            offset=max(0, offset),
        )

    # ------------------------------------------------------------------
    # Revisions
    # ------------------------------------------------------------------

    async def list_revisions(
        self, article_id: UUID, viewer: User
    ) -> list[tuple[ArticleRevision, User]]:
        row = await self._repo.get_with_author(article_id)
        if row is None:
            raise ArticleNotFound(str(article_id))
        article, _author = row
        if viewer.id != article.author_id and viewer.role not in _MOD_OR_ADMIN:
            raise ArticleNotEditable(
                "Only the author or a moderator/admin may view revisions"
            )
        return await self._repo.list_revisions(article.id)

    async def get_revision(
        self, article_id: UUID, revision: int, viewer: User
    ) -> tuple[ArticleRevision, User]:
        row = await self._repo.get_with_author(article_id)
        if row is None:
            raise ArticleNotFound(str(article_id))
        article, _author = row
        if viewer.id != article.author_id and viewer.role not in _MOD_OR_ADMIN:
            raise ArticleNotEditable(
                "Only the author or a moderator/admin may view revisions"
            )
        rev_row = await self._repo.get_revision(article.id, revision)
        if rev_row is None:
            raise ArticleNotFound(f"revision {revision} of article {article.id}")
        return rev_row


__all__ = ["ArticleService"]
