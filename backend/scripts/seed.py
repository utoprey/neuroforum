"""Idempotent seed: 10 users, 6 sections, 8 topics, 8 articles, threads, DMs.

Run from inside the backend container::

    docker compose exec backend python -m scripts.seed

The script:
- TRUNCATEs all forum-content tables (preserves ``alembic_version``)
- Creates users + profiles via :class:`app.modules.users.service.UserService`
- Creates sections + topics via :class:`app.modules.forum.service.ForumService`
- Creates published articles via :class:`app.modules.articles.service.ArticleService`
  — this fans out mentions and notifications automatically.
- Creates message threads, reactions, saves, and DM conversations.

Determinism is achieved by ``random.seed(42)`` so re-running yields the
same fixture data.
"""

# This file is full of Russian copy + en-dashes — RUF001/002/003
# (ambiguous Cyrillic / en-dash) are the precise behaviour we want and
# would only get in the way. The line-length cap also doesn't really
# apply to embedded LaTeX strings.
# ruff: noqa: RUF001, RUF002, RUF003, E501

from __future__ import annotations

import asyncio
import random
import sys
import zlib
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from pydantic import SecretStr
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings
from app.modules.articles.models import Article
from app.modules.articles.repository import ArticleRepository
from app.modules.articles.schemas import ArticleCreate
from app.modules.articles.service import ArticleService
from app.modules.content.schemas import DocSchema
from app.modules.dm.repository import DMRepository
from app.modules.dm.schemas import DirectMessageCreate
from app.modules.dm.service import DMService
from app.modules.forum.models import Section, Topic, TopicKind
from app.modules.forum.repository import ForumRepository
from app.modules.forum.schemas import SectionCreate, TopicCreate
from app.modules.forum.service import ForumService
from app.modules.mentions.repository import MentionRepository
from app.modules.mentions.service import MentionService
from app.modules.messages.repository import MessageRepository
from app.modules.messages.schemas import MessageCreate
from app.modules.messages.service import MessageService
from app.modules.notifications.repository import NotificationRepository
from app.modules.notifications.service import NotificationService
from app.modules.reactions.models import ReactionKind
from app.modules.reactions.service import ReactionService
from app.modules.saved.repository import SavedRepository
from app.modules.saved.service import SavedService
from app.modules.users.models import Role, User
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import ProfileUpdate, UserCreate
from app.modules.users.service import UserService

random.seed(42)

DEFAULT_PASSWORD = "password123"


# ---------------------------------------------------------------------------
# Spec tables (transcribed from the prompt)
# ---------------------------------------------------------------------------

USERS_SPEC: list[dict[str, Any]] = [
    {
        "username": "alice_neuro",
        "role": Role.ADMIN,
        "display_name": "Алиса Кортикалова",
        "bio": "Computational neuroscientist, PI @ Brain Lab",
        "orcid": "0000-0001-2345-6789",
        "social_links": {"github": "alice-neuro", "twitter": "AliceNeuro"},
    },
    {
        "username": "bob_imaging",
        "role": Role.MODERATOR,
        "display_name": "Боб Возгриваев",
        "bio": "fMRI methodologist, postdoc",
        "orcid": "0000-0002-3456-789X",
        "social_links": {
            "github": "bob-imaging",
            "scholar": "https://scholar.google.com/citations?user=xyz",
        },
    },
    {
        "username": "carla_compneuro",
        "role": Role.USER,
        "display_name": "Карла Прецепция",
        "bio": "PhD student, Bayesian brain models",
        "orcid": None,
        "social_links": {"github": "carla-cm"},
    },
    {
        "username": "david_ml",
        "role": Role.MODERATOR,
        "display_name": "Давид Бэкпроп",
        "bio": "ML for brain decoding",
        "orcid": None,
        "social_links": {"twitter": "DavidML"},
    },
    {
        "username": "eve_cognition",
        "role": Role.USER,
        "display_name": "Ева Аттенция",
        "bio": "Cognitive psychology, working memory",
        "orcid": None,
        "social_links": {"mastodon": "@eve@scicomm.xyz"},
    },
    {
        "username": "frank_methods",
        "role": Role.USER,
        "display_name": "Франк Утиль",
        "bio": "Open-source neuroscience tools",
        "orcid": None,
        "social_links": {"github": "frank-tools"},
    },
    {
        "username": "grace_clinical",
        "role": Role.USER,
        "display_name": "Грейс Невро",
        "bio": "Clinical neuroscientist",
        "orcid": "0000-0003-4567-8901",
        "social_links": {"linkedin": "grace-n"},
    },
    {
        "username": "henry_news",
        "role": Role.USER,
        "display_name": "Хенри Дайджест",
        "bio": "Science journalism intern",
        "orcid": None,
        "social_links": {"twitter": "HenryDigests"},
    },
    {
        "username": "iris_lab",
        "role": Role.USER,
        "display_name": "Ирис Хемисфер",
        "bio": "Optogenetics, mouse brain",
        "orcid": None,
        "social_links": {"github": "iris-lab"},
    },
    {
        "username": "jack_student",
        "role": Role.USER,
        "display_name": "Джек Студент",
        "bio": "Master's student, just started",
        "orcid": None,
        "social_links": {},
    },
]


SECTIONS_SPEC: list[dict[str, Any]] = [
    {
        "slug": "computational-neuroscience",
        "title": "Вычислительная нейронаука",
        "description": "Модели нейронных сетей и теории мозга",
        "icon": "brain",
        "position": 1,
    },
    {
        "slug": "neuroimaging",
        "title": "Нейровизуализация",
        "description": "fMRI, EEG, MEG, structural MRI, диффузионка",
        "icon": "scan-line",
        "position": 2,
    },
    {
        "slug": "cognitive-neuroscience",
        "title": "Когнитивная нейронаука",
        "description": "Память, внимание, принятие решений",
        "icon": "sparkles",
        "position": 3,
    },
    {
        "slug": "machine-learning-brain",
        "title": "Машинное обучение в нейронауке",
        "description": "Decoding, predicting, generating",
        "icon": "cpu",
        "position": 4,
    },
    {
        "slug": "methods-tools",
        "title": "Методы и инструменты",
        "description": "Софт, библиотеки, экспериментальные протоколы",
        "icon": "wrench",
        "position": 5,
    },
    {
        "slug": "news-discussion",
        "title": "Новости и обсуждения",
        "description": "Свежие препринты, журнальные клубы, news",
        "icon": "newspaper",
        "position": 6,
    },
]


TOPICS_SPEC: list[dict[str, Any]] = [
    # ----- News topics (long-form article containers) ----------------------
    {
        "section_slug": "computational-neuroscience",
        "slug": "predictive-coding-free-energy",
        "title": "Predictive coding и free energy principle: state of the art",
        "kind": TopicKind.NEWS,
    },
    {
        "section_slug": "computational-neuroscience",
        "slug": "recurrent-network-models",
        "title": "Рекуррентные сети как модель cortex",
        "kind": TopicKind.NEWS,
    },
    {
        "section_slug": "neuroimaging",
        "slug": "bold-signal-interpretation",
        "title": "Что на самом деле говорит BOLD-сигнал",
        "kind": TopicKind.NEWS,
    },
    {
        "section_slug": "neuroimaging",
        "slug": "diffusion-tractography-pitfalls",
        "title": "Подводные камни diffusion tractography",
        "kind": TopicKind.NEWS,
    },
    {
        "section_slug": "cognitive-neuroscience",
        "slug": "working-memory-mechanisms",
        "title": "Механизмы рабочей памяти: где мы сейчас",
        "kind": TopicKind.NEWS,
    },
    {
        "section_slug": "machine-learning-brain",
        "slug": "transformer-eeg-decoding",
        "title": "Transformers для декодирования EEG",
        "kind": TopicKind.NEWS,
    },
    {
        "section_slug": "methods-tools",
        "slug": "nilearn-pipeline-tips",
        "title": "Nilearn: типичные ошибки в pipeline",
        "kind": TopicKind.NEWS,
    },
    {
        "section_slug": "news-discussion",
        "slug": "journal-club-weekly",
        "title": "Еженедельный journal club: июнь 2026",
        "kind": TopicKind.NEWS,
    },
    # --- Extra news topics (short blueprints, filler content for listings) ---
    {
        "section_slug": "computational-neuroscience",
        "slug": "attractor-dynamics-motor-cortex",
        "title": "Attractor dynamics в моторной коре: обзор 2026",
        "kind": TopicKind.NEWS,
    },
    {
        "section_slug": "computational-neuroscience",
        "slug": "bayesian-brain-hypothesis-review",
        "title": "Bayesian brain hypothesis: критический обзор",
        "kind": TopicKind.NEWS,
    },
    {
        "section_slug": "neuroimaging",
        "slug": "resting-state-fmri-networks",
        "title": "Resting-state fMRI: 15 лет спустя",
        "kind": TopicKind.NEWS,
    },
    {
        "section_slug": "neuroimaging",
        "slug": "glm-vs-mvpa-2026",
        "title": "GLM vs MVPA: когда какой подход",
        "kind": TopicKind.NEWS,
    },
    {
        "section_slug": "cognitive-neuroscience",
        "slug": "attention-and-consciousness",
        "title": "Внимание и сознание: нейронные корреляты",
        "kind": TopicKind.NEWS,
    },
    {
        "section_slug": "cognitive-neuroscience",
        "slug": "dual-process-theory-decisions",
        "title": "Dual-process теории принятия решений",
        "kind": TopicKind.NEWS,
    },
    {
        "section_slug": "machine-learning-brain",
        "slug": "deep-generative-models-eeg",
        "title": "Deep generative models для генерации EEG",
        "kind": TopicKind.NEWS,
    },
    {
        "section_slug": "machine-learning-brain",
        "slug": "graph-nets-on-connectomes",
        "title": "Graph neural nets на коннектомах",
        "kind": TopicKind.NEWS,
    },
    {
        "section_slug": "methods-tools",
        "slug": "pytorch-vs-jax-for-neuro",
        "title": "PyTorch vs JAX для нейронауки в 2026",
        "kind": TopicKind.NEWS,
    },
    {
        "section_slug": "methods-tools",
        "slug": "open-neurodata-datasets",
        "title": "Open neurodata: датасеты, которыми стоит пользоваться",
        "kind": TopicKind.NEWS,
    },
    {
        "section_slug": "news-discussion",
        "slug": "weekly-arxiv-digest",
        "title": "arXiv-дайджест недели: новинки q-bio.NC",
        "kind": TopicKind.NEWS,
    },
    {
        "section_slug": "news-discussion",
        "slug": "neurips-2026-highlights",
        "title": "NeurIPS 2026: highlights от neuro-track",
        "kind": TopicKind.NEWS,
    },
]


# Section -> (discussion-title, help-title, flood-title). The seed creates
# one topic per kind per section, each populated with a placeholder
# "container" article and a few messages — so the section listing UI is
# never empty in any kind tab.
EXTRA_TOPICS_BY_SECTION: dict[str, dict[TopicKind, dict[str, str]]] = {
    "computational-neuroscience": {
        TopicKind.DISCUSSION: {
            "slug": "compneuro-discussions",
            "title": "Обсуждения: comp neuro в широком смысле",
            "intro": "Тред для свободных обсуждений: модели, гипотезы, новости.",
        },
        TopicKind.HELP: {
            "slug": "compneuro-help",
            "title": "Помощь: comp neuro — задайте вопрос",
            "intro": "Вопросы по моделям, симуляторам, статьям. Помогаем друг другу.",
        },
        TopicKind.FLOOD: {
            "slug": "compneuro-flood",
            "title": "Флуд: comp neuro on-topic-ish",
            "intro": "Лёгкие разговоры, мемы, sci-news около темы.",
        },
    },
    "neuroimaging": {
        TopicKind.DISCUSSION: {
            "slug": "imaging-discussions",
            "title": "Обсуждения нейровизуализации",
            "intro": "fMRI, PET, MEG, EEG — что обсуждаем сегодня?",
        },
        TopicKind.HELP: {
            "slug": "imaging-help",
            "title": "Помощь: pipelines и артефакты",
            "intro": "Конкретные вопросы по препроцессингу и анализу imaging-данных.",
        },
        TopicKind.FLOOD: {
            "slug": "imaging-flood",
            "title": "Флуд: imaging-curio",
            "intro": "Заходим, делимся забавными артефактами и new toys.",
        },
    },
    "cognitive-neuroscience": {
        TopicKind.DISCUSSION: {
            "slug": "cognitive-discussions",
            "title": "Обсуждения когнитивной нейронауки",
            "intro": "Внимание, память, language, decision-making — всё сюда.",
        },
        TopicKind.HELP: {
            "slug": "cognitive-help",
            "title": "Помощь: эксперименты и анализ",
            "intro": "Дизайн поведенческих экспериментов, обработка RT, статистика.",
        },
        TopicKind.FLOOD: {
            "slug": "cognitive-flood",
            "title": "Флуд: cog-curio",
            "intro": "Любые истории про cog-science вне формата.",
        },
    },
    "machine-learning-brain": {
        TopicKind.DISCUSSION: {
            "slug": "ml-brain-discussions",
            "title": "ML×Brain: обсуждения",
            "intro": "Decoding, RSA, представления, foundation-модели.",
        },
        TopicKind.HELP: {
            "slug": "ml-brain-help",
            "title": "Помощь: модели и тренировки",
            "intro": "PyTorch/JAX-вопросы, baselines, voxel-wise CV — спросите тут.",
        },
        TopicKind.FLOOD: {
            "slug": "ml-brain-flood",
            "title": "Флуд: ML brain news",
            "intro": "Свежие препринты, твиты, hot takes.",
        },
    },
    "methods-tools": {
        TopicKind.DISCUSSION: {
            "slug": "tools-discussions",
            "title": "Обсуждения инструментов и методов",
            "intro": "BIDS, nipype, nilearn, MNE — что используете и почему?",
        },
        TopicKind.HELP: {
            "slug": "tools-help",
            "title": "Помощь: настройка инструментов",
            "intro": "Конкретные стек-вопросы: установка, конфигурация, баги.",
        },
        TopicKind.FLOOD: {
            "slug": "tools-flood",
            "title": "Флуд: dev jokes",
            "intro": "PR-мемы, шутки про reviewer 2, кто как обходит SLURM.",
        },
    },
    "news-discussion": {
        TopicKind.DISCUSSION: {
            "slug": "news-open-discussions",
            "title": "Свободные обсуждения новостей",
            "intro": "Любая neuroscience-новость, которая зацепила.",
        },
        TopicKind.HELP: {
            "slug": "news-help",
            "title": "Помощь: где искать препринты и датасеты",
            "intro": "Хочешь найти датасет / репликацию / статью — спроси тут.",
        },
        TopicKind.FLOOD: {
            "slug": "news-flood",
            "title": "Флуд: nature-cover-art",
            "intro": "Обложки журналов, twitter-drama, прочий лайт-контент.",
        },
    },
}


# A minimal ProseMirror placeholder used as the container article for each
# discussion/help/flood topic — gives messages something to hang off of.
def _placeholder_doc(intro: str) -> dict[str, Any]:
    return doc(
        [
            paragraph([text_node(intro)]),
            paragraph(
                [
                    text_node(
                        "Это тред-контейнер. Пишите ниже сообщения,"
                        " отвечайте друг другу, реагируйте."
                    )
                ]
            ),
        ]
    )


def gif_block(
    attachment_id: UUID, alt: str = "", *, seed: str | None = None
) -> dict[str, Any]:
    """Build a ``gif`` block with ``src`` populated when ``seed`` is known.

    Seed-data flows through ``_make_seed_gif_attachment`` and knows the
    seed string up front, so we can stamp a render-ready URL directly
    into the content JSONB. This means even clients that don't run the
    enricher (e.g. raw JSONB inspection in tests) see a usable URL.
    """
    attrs: dict[str, Any] = {"attachment_id": str(attachment_id), "alt": alt}
    if seed is not None:
        # Picsum doesn't serve animated GIFs but it does serve stable
        # seeded images — good enough for a dev-only placeholder.
        attrs["src"] = f"https://picsum.photos/seed/gif-{seed}/600/400"
    return {"type": "gif", "attrs": attrs}


# ---------------------------------------------------------------------------
# ProseMirror helpers
# ---------------------------------------------------------------------------


def text_node(value: str, marks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    node: dict[str, Any] = {"type": "text", "text": value}
    if marks:
        node["marks"] = marks
    return node


def paragraph(content: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "paragraph", "content": content}


def heading(level: int, value: str) -> dict[str, Any]:
    return {
        "type": "heading",
        "attrs": {"level": level},
        "content": [text_node(value)],
    }


def code_block(language: str, body: str) -> dict[str, Any]:
    return {
        "type": "codeBlock",
        "attrs": {"language": language},
        "content": [text_node(body)],
    }


def math_block(latex: str, display: bool = True) -> dict[str, Any]:
    return {
        "type": "math",
        "attrs": {"latex": latex, "display": display},
    }


def bullet_list(items: list[str]) -> dict[str, Any]:
    return {
        "type": "bulletList",
        "content": [
            {
                "type": "listItem",
                "content": [paragraph([text_node(item)])],
            }
            for item in items
        ],
    }


def callout(
    kind: str, value: str, icon: str = ""
) -> dict[str, Any]:
    return {
        "type": "callout",
        "attrs": {"kind": kind, "icon": icon},
        "content": [paragraph([text_node(value)])],
    }


def mention_node(user_id: UUID) -> dict[str, Any]:
    return {"type": "mention", "attrs": {"user_id": str(user_id)}}


def image_block(
    attachment_id: UUID,
    alt: str = "",
    caption: str = "",
    *,
    seed: str | None = None,
    width: int = 800,
    height: int = 450,
) -> dict[str, Any]:
    """Build an ``image`` block with ``src`` populated when ``seed`` is known.

    See ``gif_block`` for rationale — having a real picsum URL in the
    seed content means tests + curl-checks observe a render-ready doc
    without hitting the enricher path.
    """
    attrs: dict[str, Any] = {
        "attachment_id": str(attachment_id),
        "alt": alt,
        "caption": caption,
    }
    if seed is not None:
        attrs["src"] = f"https://picsum.photos/seed/{seed}/{width}/{height}"
    return {"type": "image", "attrs": attrs}


def quote_block(value: str, cite_url: str | None = None) -> dict[str, Any]:
    attrs: dict[str, Any] = {}
    if cite_url is not None:
        attrs["cite_url"] = cite_url
    return {
        "type": "quote",
        "attrs": attrs,
        "content": [paragraph([text_node(value)])],
    }


def link_node(href: str, title: str | None = None) -> dict[str, Any]:
    attrs: dict[str, Any] = {"href": href}
    if title is not None:
        attrs["title"] = title
    return {"type": "link", "attrs": attrs}


def doc(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "doc", "content": blocks}


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

# Real table names (verified against ``\dt`` on the live DB).
_TABLES_TO_TRUNCATE: list[str] = [
    "notifications",
    "mentions",
    "saved_articles",
    "article_reactions",
    "message_reactions",
    "article_revisions",
    "message_revisions",
    "article_ai_proposals",
    "messages",
    "articles",
    "topics",
    "sections",
    "direct_message_reads",
    "direct_messages",
    "conversation_participants",
    "conversations",
    "agents",
    "agent_credentials",
    "llm_usage_log",
    "user_bans",
    "audit_log",
    "refresh_tokens",
    "user_stats",
    "user_profiles",
    "users",
    "external_sources",
    "embeds",
    "attachment_usages",
    "attachments",
]


async def truncate_all(session: AsyncSession) -> None:
    """Wipe forum data so the seed is idempotent. ``alembic_version`` is preserved."""
    joined = ", ".join(_TABLES_TO_TRUNCATE)
    await session.execute(
        text(f"TRUNCATE TABLE {joined} RESTART IDENTITY CASCADE")
    )
    await session.commit()


async def recompute_all_stats(db: AsyncSession) -> None:
    """Recompute ``user_stats.*`` and ``articles.comment_count`` from scratch.

    Backfill step used at the end of seeding so the denormalised counters
    are guaranteed to match the underlying row counts, regardless of
    whether each service-level bump fired correctly during the run. Also
    safe to call repeatedly — pure SQL aggregates.
    """
    await db.execute(
        text(
            """
            UPDATE user_stats us SET
                articles_count = (
                    SELECT COUNT(*) FROM articles a
                    WHERE a.author_id = us.user_id
                      AND a.status = 'published'
                ),
                messages_count = (
                    SELECT COUNT(*) FROM messages m
                    WHERE m.author_id = us.user_id
                      AND m.status IN ('visible', 'edited')
                ),
                received_reactions_count = (
                    SELECT COUNT(*) FROM article_reactions ar
                    JOIN articles a ON a.id = ar.article_id
                    WHERE a.author_id = us.user_id
                ) + (
                    SELECT COUNT(*) FROM message_reactions mr
                    JOIN messages m ON m.id = mr.message_id
                    WHERE m.author_id = us.user_id
                ),
                saved_articles_count = (
                    SELECT COUNT(*) FROM saved_articles s
                    WHERE s.user_id = us.user_id
                ),
                updated_at = NOW()
            """
        )
    )
    await db.execute(
        text(
            """
            UPDATE articles a SET comment_count = (
                SELECT COUNT(*) FROM messages m
                WHERE m.article_id = a.id
                  AND m.status IN (
                      'visible', 'edited', 'hidden_by_mod', 'deleted_by_author'
                  )
            )
            """
        )
    )
    await db.commit()
    print("Stats recomputed.")


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


async def create_users(
    db: AsyncSession, users_svc: UserService
) -> dict[str, User]:
    """Create users + profiles. Returns ``{username: User}``."""
    created: dict[str, User] = {}
    for spec in USERS_SPEC:
        user = await users_svc.create_user(
            UserCreate(
                username=spec["username"],
                email=f"{spec['username']}@neuroforum.dev",
                password=SecretStr(DEFAULT_PASSWORD),
            ),
            role=spec["role"],
        )
        await users_svc.update_profile(
            user.id,
            ProfileUpdate(
                display_name=spec["display_name"],
                bio=spec["bio"],
                orcid=spec["orcid"],
                social_links=spec["social_links"],
            ),
        )
        # Re-fetch with profile populated.
        refreshed = await users_svc.get_by_id(user.id)
        created[spec["username"]] = refreshed
    return created


# ---------------------------------------------------------------------------
# Sections + topics
# ---------------------------------------------------------------------------


async def create_sections(
    db: AsyncSession, forum_svc: ForumService, admin: User
) -> dict[str, Section]:
    sections: dict[str, Section] = {}
    for spec in SECTIONS_SPEC:
        section = await forum_svc.create_section(
            admin,
            SectionCreate(
                title=spec["title"],
                slug=spec["slug"],
                description=spec["description"],
                icon=spec["icon"],
                position=spec["position"],
            ),
        )
        sections[spec["slug"]] = section
    return sections


async def create_topics(
    db: AsyncSession,
    forum_svc: ForumService,
    sections: dict[str, Section],
    users: dict[str, User],
) -> dict[str, Topic]:
    """Each NEWS topic is created by alice (admin) or bob/david (moderators).

    Extra discussion/help/flood topics are created by varied users (we use
    a small pool to mimic real activity).
    """
    eligible_news_creators = [
        users["alice_neuro"],
        users["bob_imaging"],
        users["david_ml"],
    ]
    extra_creators = [
        users["carla_compneuro"],
        users["eve_cognition"],
        users["frank_methods"],
        users["grace_clinical"],
        users["iris_lab"],
        users["jack_student"],
        users["henry_news"],
    ]
    topics: dict[str, Topic] = {}
    for i, spec in enumerate(TOPICS_SPEC):
        creator = eligible_news_creators[i % len(eligible_news_creators)]
        topic, _ = await forum_svc.create_topic(
            creator,
            spec["section_slug"],
            TopicCreate(
                title=spec["title"],
                slug=spec["slug"],
                kind=spec.get("kind", TopicKind.NEWS),
            ),
        )
        topics[spec["slug"]] = topic

    # Discussion / help / flood — one per section, varied creators.
    pick_idx = 0
    for section_slug, by_kind in EXTRA_TOPICS_BY_SECTION.items():
        for kind, info in by_kind.items():
            creator = extra_creators[pick_idx % len(extra_creators)]
            pick_idx += 1
            topic, _ = await forum_svc.create_topic(
                creator,
                section_slug,
                TopicCreate(
                    title=info["title"],
                    slug=info["slug"],
                    description=info["intro"],
                    kind=kind,
                ),
            )
            topics[info["slug"]] = topic
    return topics


async def create_extra_articles(
    db: AsyncSession,
    articles_svc: ArticleService,
    topics: dict[str, Topic],
    sections: dict[str, Section],
    users: dict[str, User],
) -> list[Article]:
    """Create a content-rich container article for each non-news topic.

    Discussion / help / flood topics each get a real opening post (6–10
    blocks: paragraphs, headings, images, mentions, callouts, code, lists,
    quotes, GIFs) so the UI never lands on an empty "тред-контейнер"
    paragraph. The per-kind builder selects a stylistically appropriate
    layout (see ``make_discussion_doc`` / ``make_help_doc`` /
    ``make_flood_doc``).

    Discussion / help / flood topics still need a published article so
    ``messages`` can hang off it (the ``messages.article_id`` FK is
    ``RESTRICT``).
    """
    created: list[Article] = []
    extra_authors = [
        users["alice_neuro"],
        users["bob_imaging"],
        users["carla_compneuro"],
        users["david_ml"],
        users["eve_cognition"],
        users["frank_methods"],
    ]
    # Pool of authors we'll @-mention inside the bodies (excluding the
    # post's own author to keep the mention semantically meaningful).
    mention_pool = [
        users["alice_neuro"],
        users["bob_imaging"],
        users["carla_compneuro"],
        users["david_ml"],
        users["eve_cognition"],
        users["frank_methods"],
        users["grace_clinical"],
        users["iris_lab"],
        users["henry_news"],
    ]
    idx = 0
    for section_slug, by_kind in EXTRA_TOPICS_BY_SECTION.items():
        section_title = sections[section_slug].title
        for kind, info in by_kind.items():
            topic = topics[info["slug"]]
            author = extra_authors[idx % len(extra_authors)]
            idx += 1
            # Pick 1–2 mention targets that aren't the author themselves.
            candidates = [u for u in mention_pool if u.id != author.id]
            mention_count = 2 if kind is TopicKind.DISCUSSION else 1
            mentions = random.sample(candidates, k=mention_count)
            seed_slug = _slugify_for_seed(info["slug"])
            if kind is TopicKind.DISCUSSION:
                content_dict = await make_discussion_doc(
                    db,
                    topic_title=info["title"],
                    section_title=section_title,
                    author=author,
                    mentions=mentions,
                    seed_slug=seed_slug,
                )
            elif kind is TopicKind.HELP:
                content_dict = await make_help_doc(
                    db,
                    topic_title=info["title"],
                    section_title=section_title,
                    author=author,
                    mentions=mentions,
                    seed_slug=seed_slug,
                )
            elif kind is TopicKind.FLOOD:
                content_dict = await make_flood_doc(
                    db,
                    topic_title=info["title"],
                    section_title=section_title,
                    author=author,
                    mentions=mentions,
                    seed_slug=seed_slug,
                )
            else:
                # Fall back to the original minimal placeholder for any
                # future topic kinds we haven't styled yet.
                content_dict = _placeholder_doc(info["intro"])

            article, _ = await articles_svc.create_article(
                author,
                topic.id,
                ArticleCreate(
                    title=info["title"],
                    summary=info["intro"],
                    content=DocSchema.model_validate(content_dict),
                ),
            )
            published, _ = await articles_svc.publish_article(author, article.id)
            days_ago = random.randint(1, 30)
            ts = datetime.now(UTC) - timedelta(days=days_ago)
            await db.execute(
                update(Article)
                .where(Article.id == published.id)
                .values(published_at=ts)
            )
            await db.flush()
            created.append(published)
    return created


# ---------------------------------------------------------------------------
# Articles
# ---------------------------------------------------------------------------


def _build_article_doc(
    *,
    title: str,
    intro: str,
    formula_latex: str,
    formula_intro: str,
    callout_text: str,
    bullets: list[str],
    quote: str,
    code: str,
    code_lang: str,
    mention_targets: list[User],
    image_attachment_id: UUID,
    image_seed: str,
    image_caption: str,
    link_href: str,
    link_text: str,
    conclusion: str,
) -> dict[str, Any]:
    """Compose a realistic ProseMirror doc with every required block type."""
    paragraph_with_mentions: list[dict[str, Any]] = [
        text_node("Спасибо за обсуждение — особенно "),
    ]
    for i, user in enumerate(mention_targets):
        paragraph_with_mentions.append(mention_node(user.id))
        if i < len(mention_targets) - 1:
            paragraph_with_mentions.append(text_node(" и "))
    paragraph_with_mentions.append(
        text_node(" — ваши комментарии очень помогли уточнить аргумент.")
    )

    return doc(
        [
            heading(1, title),
            paragraph([text_node(intro)]),
            heading(2, "Формализм"),
            paragraph([text_node(formula_intro)]),
            math_block(formula_latex, display=True),
            callout("info", callout_text),
            heading(2, "Поведенческие предсказания"),
            bullet_list(bullets),
            image_block(
                image_attachment_id,
                alt="Концептуальная иллюстрация",
                caption=image_caption,
                seed=image_seed,
            ),
            heading(2, "Открытые вопросы"),
            paragraph(paragraph_with_mentions),
            code_block(code_lang, code),
            quote_block(quote),
            paragraph(
                [
                    text_node("Подробнее в препринте: "),
                    text_node(
                        link_text,
                        marks=[{"type": "link", "attrs": {"href": link_href}}],
                    ),
                    text_node("."),
                ]
            ),
            paragraph(
                [
                    text_node(conclusion),
                    text_node(" Используется также "),
                    text_node("inline-код", marks=[{"type": "code"}]),
                    text_node(" для повторяемости."),
                ]
            ),
        ]
    )


def _picsum(seed: str) -> str:
    return f"https://picsum.photos/seed/{seed}/800/450"


def _build_short_news_doc(
    *,
    title: str,
    summary: str,
    section_intro: str,
    subheading: str,
    bullets: list[str],
    formula_latex: str,
    image_attachment_id: UUID,
    image_seed: str,
    image_caption: str,
    closing: str,
) -> dict[str, Any]:
    """A shorter but still content-rich blueprint for secondary news posts.

    Roughly 7 blocks vs the full 18-block ``_build_article_doc`` — meant for
    extra topics inside a section so listing UI looks populated without
    writing full editorial copy for each.
    """
    return doc(
        [
            heading(1, title),
            paragraph(
                [
                    text_node(summary, marks=[{"type": "italic"}]),
                ]
            ),
            paragraph([text_node(section_intro)]),
            heading(2, subheading),
            bullet_list(bullets),
            math_block(formula_latex, display=True),
            image_block(
                image_attachment_id,
                alt="Иллюстрация",
                caption=image_caption,
                seed=image_seed,
            ),
            paragraph([text_node(closing)]),
        ]
    )


async def _make_seed_attachment(
    db: AsyncSession, uploader: User, seed: str
) -> UUID:
    """Insert a synthetic ``Attachment`` row + return its UUID.

    ``object_key`` references a real picsum URL so the placeholder image
    renders in dev without MinIO. We bypass the service layer because we
    don't need MIME-whitelist enforcement or presigned URLs here.
    """
    from app.modules.attachments.models import (
        Attachment,
        AttachmentKind,
        ProcessingStatus,
    )

    attachment_id = uuid4()
    attachment = Attachment(
        id=attachment_id,
        uploader_id=uploader.id,
        kind=AttachmentKind.IMAGE,
        bucket="external",
        object_key=f"picsum/{seed}/800/450",
        mime_type="image/jpeg",
        size_bytes=120_000,
        width=800,
        height=450,
        original_filename=f"{seed}.jpg",
        processing_status=ProcessingStatus.READY,
    )
    db.add(attachment)
    await db.flush()
    return attachment_id


async def _make_seed_gif_attachment(
    db: AsyncSession, uploader: User, seed: str
) -> UUID:
    """Insert a synthetic GIF ``Attachment`` row + return its UUID.

    Same trick as ``_make_seed_attachment`` but with ``kind=GIF`` and a
    ``image/gif`` MIME so the frontend can render it as an animated image
    (it currently treats GIFs as plain ``<img>``s, which is fine).
    """
    from app.modules.attachments.models import (
        Attachment,
        AttachmentKind,
        ProcessingStatus,
    )

    attachment_id = uuid4()
    attachment = Attachment(
        id=attachment_id,
        uploader_id=uploader.id,
        kind=AttachmentKind.GIF,
        bucket="external",
        object_key=f"giphy/{seed}.gif",
        mime_type="image/gif",
        size_bytes=480_000,
        width=480,
        height=270,
        original_filename=f"{seed}.gif",
        processing_status=ProcessingStatus.READY,
    )
    db.add(attachment)
    await db.flush()
    return attachment_id


# ---------------------------------------------------------------------------
# Discussion / help / flood content builders
# ---------------------------------------------------------------------------


def _slugify_for_seed(value: str) -> str:
    return (
        value.replace(" ", "-")
        .replace("/", "-")
        .replace(":", "")
        .lower()
    )


_DISCUSSION_OPENERS: list[tuple[str, str, list[str]]] = [
    (
        "Что обсуждаем здесь",
        "Сюда идут открытые вопросы по «{section}», которые не тянут на"
        " отдельную статью, но заслуживают разбора. Тема ветки — {topic}.",
        [
            "Какие модели/подходы вам кажутся недооценёнными?",
            "Есть ли свежие препринты, которые стоит разобрать?",
            "Где видите главные методологические дыры?",
            "Любимые negative results — пишите, разберём.",
        ],
    ),
    (
        "О чём тред",
        "Соберём в одном месте разговоры про «{topic}» в контексте"
        " «{section}» — без нужды заводить статью. Формат — свободный,"
        " от полевых наблюдений до статей.",
        [
            "Какие эмпирические результаты застряли у вас в голове за последний год?",
            "Что вы бы поменяли в стандартном pipeline под эту задачу?",
            "Какие open questions пока не имеют ответа даже приблизительно?",
        ],
    ),
    (
        "Формат обсуждения",
        "Тред-агрегатор по «{topic}»: ссылки, спорные тезисы, свежие"
        " попадания в arXiv. «{section}» — широкая тема, поэтому уместно"
        " всё, что развивает разговор.",
        [
            "Что читаете сейчас по теме — фон / core / бонус?",
            "Какие результаты сомнительны и почему?",
            "Есть ли методики, которые пора списать и заменить?",
        ],
    ),
    (
        "О чём тут говорим",
        "Открываем ветку по «{topic}» в разделе «{section}». Основная"
        " идея — держать конструктив и делиться конкретикой: код, данные,"
        " ссылки, отзывы.",
        [
            "Есть ли reproducibility-issue, которые вас беспокоят?",
            "Какие подходы кажутся модными, но плохо обоснованными?",
            "Что бы вы посоветовали новичку в этой узкой теме?",
        ],
    ),
    (
        "Про что этот тред",
        "«{topic}» — компактная плитка внутри «{section}». Здесь удобно"
        " обсуждать шероховатости, о которых не всегда хочется писать"
        " отдельно: приёмы, привычки, лайфхаки.",
        [
            "Как вы выбираете гиперпараметры под задачу?",
            "Какие библиотеки/подходы вам кажутся underrated?",
            "На что уходит больше всего времени — препроцессинг, валидация, отчётность?",
        ],
    ),
    (
        "Формат",
        "Здесь — обмен наблюдениями и мыслями по «{topic}». Раздел"
        " «{section}» большой, так что не стесняйтесь бросать даже"
        " смежные ссылки — модерация лояльная.",
        [
            "Что в этой теме реально мешает делать хорошую науку?",
            "Какие критерии качества результата вы применяете?",
            "Что бы вы разобрали в отдельной статье, будь у вас время?",
        ],
    ),
]


async def make_discussion_doc(
    db: AsyncSession,
    *,
    topic_title: str,
    section_title: str,
    author: User,
    mentions: list[User],
    seed_slug: str,
) -> dict[str, Any]:
    """Compose a discussion-style container article (heading, questions, image, callout)."""
    img_seed = f"disc-{seed_slug}"
    img = await _make_seed_attachment(db, author, img_seed)
    mention_para: list[dict[str, Any]] = [text_node("Особенно интересно услышать ")]
    for i, user in enumerate(mentions):
        mention_para.append(mention_node(user.id))
        if i < len(mentions) - 1:
            mention_para.append(text_node(" и "))
    mention_para.append(
        text_node(
            " — у вас был хороший вектор в прошлой ветке, было бы здорово"
            " развить его и тут."
        )
    )
    variant_idx = zlib.crc32(seed_slug.encode()) % len(_DISCUSSION_OPENERS)
    variant_heading, variant_body, variant_bullets = _DISCUSSION_OPENERS[variant_idx]
    return doc(
        [
            heading(2, variant_heading),
            paragraph(
                [
                    text_node(
                        variant_body.format(
                            section=section_title,
                            topic=topic_title.lower(),
                        )
                    )
                ]
            ),
            bullet_list(variant_bullets),
            image_block(
                img,
                alt="Иллюстрация к теме",
                caption="Скетч для затравки — не пугайтесь, обсуждаем по сути.",
                seed=img_seed,
            ),
            paragraph(mention_para),
            callout(
                "info",
                "Делитесь опытом, статьями и мыслями. Помните: конструктив"
                " и ссылки на источники — лучшие друзья дискуссии.",
            ),
            paragraph(
                [
                    text_node("Если хочется почитать background — есть "),
                    text_node(
                        "обзор на arXiv",
                        marks=[
                            {
                                "type": "link",
                                "attrs": {
                                    "href": f"https://arxiv.org/search/?searchtype=all&query={seed_slug}"
                                },
                            }
                        ],
                    ),
                    text_node(". Сразу выводим в обсуждение интересные тезисы."),
                ]
            ),
        ]
    )


_HELP_SCENARIOS: list[tuple[str, str, str, list[str]]] = [
    (
        "Столкнулся с тем, что pipeline на fit падает без явной причины:"
        " данные грузятся, shape'ы совпадают, но модель ругается на"
        " NaN/inf. Локально не воспроизвожу, у коллег — то же самое.",
        "import numpy as np\n"
        "from sklearn.linear_model import Ridge\n\n"
        "X = np.random.randn(120, 8)\n"
        "y = np.random.randn(120)\n"
        "model = Ridge(alpha=1.0).fit(X, y)\n"
        "# на реальных данных следующая строка кидает\n"
        "# ConvergenceWarning + ValueError\n"
        "pred = model.predict(X[:10])\n",
        "python",
        [
            "Перепроверил типы и shape входов",
            "Сравнил с прошлой рабочей версией кода",
            "Уменьшил alpha, поменял solver",
            "Перезапустил env с pin-нутыми версиями зависимостей",
        ],
    ),
    (
        "Ищу воспроизводимый бенчмарк для baseline: тестируем метод на"
        " своих данных, но нет уверенности, что делаем сравнение честно."
        " Хочется свести к типовой процедуре, желательно с готовым кодом.",
        "from sklearn.model_selection import KFold, cross_val_score\n"
        "import numpy as np\n\n"
        "kf = KFold(n_splits=5, shuffle=True, random_state=42)\n"
        "scores = cross_val_score(model, X, y, cv=kf, scoring='r2')\n"
        "print(f'R2 = {np.mean(scores):.3f} ± {np.std(scores):.3f}')\n",
        "python",
        [
            "Есть ли канонические train/test split'ы для этой задачи?",
            "Какие метрики принято репортить (median vs mean, IQR)?",
            "Как учитывать subject-level leakage при cross-validation?",
        ],
    ),
    (
        "Гружу большой датасет — MemoryError на этапе feature-extraction."
        " chunk'ать пробовал, но теряю статистику по всему объёму. Есть"
        " идеи как балансировать между памятью и точностью?",
        "for i, chunk in enumerate(pd.read_csv(path, chunksize=50_000)):\n"
        "    features.append(extract(chunk))\n"
        "    # accumulate global stats без full load\n"
        "    stats.update(chunk)\n"
        "features = pd.concat(features, ignore_index=True)\n",
        "python",
        [
            "Пробовал chunksize, dtype-оптимизации, dask — что ещё?",
            "Есть ли способ сохранять промежуточные результаты на диск?",
            "Не смотрел polars/pyarrow — стоит переходить?",
        ],
    ),
    (
        "Настроил CI для проекта, но интеграционные тесты нестабильны:"
        " один и тот же коммит проходит/падает в 30% случаев. Не могу"
        " понять что flake'ит — код или инфра.",
        "@pytest.mark.integration\n"
        "async def test_pipeline(client):\n"
        "    r = await client.post('/api/predict', json={'x': [1, 2, 3]})\n"
        "    assert r.status_code == 200\n"
        "    # иногда падает на timeout, иногда — на assertion error\n",
        "python",
        [
            "Есть ли инструменты, которые находят flaky-тесты по истории CI?",
            "Как правильно писать retry-логику, не маскируя реальные баги?",
            "Что делать с DB fixtures — testcontainers, transaction rollback, что-то ещё?",
        ],
    ),
    (
        "Разворачиваю сервис на арендованный GPU-сервер — модель работает"
        " локально на CPU, но на CUDA падает с out-of-memory даже на"
        " маленьком batch. Что можно проверить?",
        "import torch\n"
        "model = model.to('cuda')\n"
        "for batch in loader:\n"
        "    with torch.autocast('cuda', dtype=torch.float16):\n"
        "        out = model(batch.to('cuda'))\n"
        "    # OOM даже при batch_size=1\n",
        "python",
        [
            "Проверить нужно ли включить gradient checkpointing?",
            "Какие библиотеки помогают профилировать VRAM?",
            "Стоит ли пробовать mixed-precision или сразу int8?",
        ],
    ),
    (
        "Пытаюсь распараллелить тяжёлый анализ на несколько ядер, но"
        " ускорения почти нет — multiprocessing даёт +30% вместо ожидаемых"
        " x4. Похоже упираюсь в что-то не то, что казалось.",
        "from multiprocessing import Pool\n"
        "with Pool(processes=4) as pool:\n"
        "    results = pool.map(analyze, chunks)\n"
        "# наблюдается: 4 ядра активны, но wallclock лишь чуть меньше\n",
        "python",
        [
            "Может быть GIL при передаче больших объектов?",
            "Что лучше — Pool.map, ProcessPoolExecutor или joblib?",
            "Есть ли смысл посмотреть в сторону ray/dask для этой задачи?",
        ],
    ),
]


async def make_help_doc(
    db: AsyncSession,
    *,
    topic_title: str,
    section_title: str,
    author: User,
    mentions: list[User],
    seed_slug: str,
) -> dict[str, Any]:
    """Compose a help-style container article (problem, code MWE, callout)."""
    img_seed = f"help-{seed_slug}"
    img = await _make_seed_attachment(db, author, img_seed)
    expert_mention_para: list[dict[str, Any]] = [
        text_node("Если есть свободная минутка — позову "),
    ]
    for i, user in enumerate(mentions):
        expert_mention_para.append(mention_node(user.id))
        if i < len(mentions) - 1:
            expert_mention_para.append(text_node(", "))
    expert_mention_para.append(
        text_node(", вы вроде сталкивались с похожим.")
    )
    scenario_idx = zlib.crc32(seed_slug.encode()) % len(_HELP_SCENARIOS)
    body, code_snippet, code_lang, tried_bullets = _HELP_SCENARIOS[scenario_idx]
    return doc(
        [
            paragraph(
                [
                    text_node(f"Привет! Нужен совет по «{section_title}». {body}")
                ]
            ),
            heading(3, "Минимальный воспроизводимый пример"),
            code_block(code_lang, code_snippet),
            heading(3, "Что уже пробовал / хочу спросить"),
            bullet_list(tried_bullets),
            image_block(
                img,
                alt="Скриншот ошибки",
                caption="Скрин ошибки из логов — для контекста.",
                seed=img_seed,
            ),
            callout(
                "warn",
                "Желательно прикладывать MWE, версии библиотек и ОС —"
                " иначе помочь практически невозможно.",
            ),
            paragraph(expert_mention_para),
        ]
    )


_FLOOD_OPENERS: list[tuple[str, str, str, str]] = [
    (
        "Тред без темы для «{section}»: мемы, скрины из статей, кривые"
        " графики. Правило одно — без холивара.",
        "Очередной мем уровня journal-club.",
        "Реакция на reviewer 2",
        "«Главный шаг в любом анализе — кофе.» — local wisdom",
    ),
    (
        "Курилка «{section}». Кидайте сюда факапы, tweet'ы от известных"
        " учёных, странные плоты. Всё, что не тянет на статью.",
        "Кривой figure — тот случай, когда авторы явно спешили к дедлайну.",
        "Когда peer review принял статью с прошлой недели",
        "«Rigor is what happens after the deadline.» — anonymous PhD",
    ),
    (
        "Пятничная ветка для «{section}»: делимся тем, что рассмешило за"
        " неделю. Скрины из slack'ов, sci-hub цитаты, странные ключевые"
        " слова из грантов.",
        "Стандартный ландшафт открытого офиса нашей лабы.",
        "Когда grant application прошёл первый tier",
        "«Все статьи пишутся в последние 48 часов дедлайна.» — local proverb",
    ),
    (
        "Флуд-тред «{section}»: подписи из твиттера, картинки из мемов,"
        " ссылки на смешные препринты. Всё, что не заслуживает отдельной"
        " ветки, но заслуживает улыбки.",
        "Когда график из статьи неожиданно красивый — приятно.",
        "Reviewer после чтения abstract",
        "«Two graduate students walk into a lab — the punchline is on r/PhD.»",
    ),
    (
        "«{section}»: место для sci-news, gif'ов из конференций, шуток"
        " про peer review. Без выяснения кто круче — Python или R.",
        "Утро понедельника, коллеги в лабе, вид сзади.",
        "Ошибка на 12-часу отладки: закат солнца вручную",
        "«Every plot is a story — some just have plot twists.»",
    ),
    (
        "Тред для нерабочих постов по теме «{section}»: смешные скрины,"
        " ассоциации, забавные paper titles. Формат — свободный.",
        "Когда plot внезапно сходится к нужному значению.",
        "Реакция на reviewer 2, вторая часть",
        "«Правильный анализ данных — тот, который переживёт reviewer 2.»",
    ),
]


async def make_flood_doc(
    db: AsyncSession,
    *,
    topic_title: str,
    section_title: str,
    author: User,
    mentions: list[User],
    seed_slug: str,
) -> dict[str, Any]:
    """Compose a flood-style container article (meme image, gif, short quote)."""
    img_seed = f"flood-{seed_slug}"
    gif_seed = f"flood-{seed_slug}"
    img = await _make_seed_attachment(db, author, img_seed)
    gif = await _make_seed_gif_attachment(db, author, gif_seed)
    mention_para: list[dict[str, Any]] = [
        text_node("Привет, "),
    ]
    for i, user in enumerate(mentions):
        mention_para.append(mention_node(user.id))
        if i < len(mentions) - 1:
            mention_para.append(text_node(", "))
    mention_para.append(text_node(" — на правах вечного флуда :)"))
    variant_idx = zlib.crc32(seed_slug.encode()) % len(_FLOOD_OPENERS)
    intro, img_caption, gif_alt, quote_text = _FLOOD_OPENERS[variant_idx]
    return doc(
        [
            paragraph(
                [text_node(intro.format(section=section_title))]
            ),
            paragraph(mention_para),
            image_block(
                img,
                alt="Картинка для настроения",
                caption=img_caption,
                seed=img_seed,
            ),
            gif_block(gif, alt=gif_alt, seed=gif_seed),
            quote_block(quote_text),
            paragraph(
                [
                    text_node(
                        "Кидайте сюда что угодно по теме. Главное —"
                        " доброжелательно."
                    )
                ]
            ),
        ]
    )


ARTICLE_BLUEPRINTS: list[dict[str, Any]] = [
    {
        "topic_slug": "predictive-coding-free-energy",
        "author_username": "alice_neuro",
        "title": "Predictive coding и free energy principle: state of the art",
        "intro": (
            "Со времени работ Karl Friston (2010) free energy principle"
            " (FEP) превратился в один из самых амбициозных кандидатов на"
            " общую теорию мозга. Идея проста: любая адаптивная система"
            " минимизирует variational free energy, что эквивалентно"
            " максимизации evidence модели окружения."
        ),
        "formula_intro": (
            "Variational free energy записывается как KL-расхождение между"
            " распознавательным распределением и совместным распределением"
            " состояний и наблюдений:"
        ),
        "formula_latex": (
            r"F = \int q(\theta) \log \frac{q(\theta)}{p(\theta, y)} \, d\theta"
        ),
        "callout_text": (
            "TL;DR — мозг минимизирует variational free energy, что"
            " эквивалентно максимизации evidence модели."
        ),
        "bullets": [
            "Сенсорные иллюзии как ошибки предсказания",
            "Active inference: выбор действия как минимизация ожидаемой free energy",
            "Иерархическая байесовская структура корковых колонн",
            "Связь с predictive coding van Helmholtz–Friston",
        ],
        "quote": (
            "“The free-energy principle says that any self-organizing"
            " system must minimize its free energy.” — Friston, 2010."
        ),
        "code": (
            "import torch\n"
            "import torch.nn as nn\n\n"
            "class PredictiveCodingBlock(nn.Module):\n"
            "    def __init__(self, dim: int) -> None:\n"
            "        super().__init__()\n"
            "        self.prior = nn.Linear(dim, dim)\n"
            "        self.likelihood = nn.Linear(dim, dim)\n\n"
            "    def forward(self, h_prev: torch.Tensor, y: torch.Tensor) -> torch.Tensor:\n"
            "        pred = self.prior(h_prev)\n"
            "        error = y - pred\n"
            "        return h_prev + self.likelihood(error)\n"
        ),
        "code_lang": "python",
        "mention_usernames": ["bob_imaging", "eve_cognition"],
        "image_seed": "predcoding",
        "image_caption": "Иерархическая структура predictive coding",
        "link_href": "https://arxiv.org/abs/1909.10363",
        "link_text": "Buckley et al., A free energy principle for a particular physics",
        "conclusion": (
            "Эмпирическая верификация FEP — открытый вопрос: предсказания"
            " слишком общие, чтобы быть фальсифицируемыми по одному"
            " эксперименту."
        ),
        "inline_math": "p(y \\mid m)",
    },
    {
        "topic_slug": "recurrent-network-models",
        "author_username": "carla_compneuro",
        "title": "Рекуррентные сети как модель cortex: куда мы пришли",
        "intro": (
            "Recurrent neural networks (RNN) остаются основной"
            " вычислительной моделью корковой динамики. От ранних работ"
            " Hopfield до современных LSTM/GRU — мы расширили арсенал, но"
            " по-прежнему спорим, что именно ловит модель."
        ),
        "formula_intro": (
            "Динамика классической continuous-time RNN с матрицей весов"
            " W и нелинейностью φ записывается как:"
        ),
        "formula_latex": (
            r"\tau \frac{d \mathbf{h}}{dt} = -\mathbf{h} + W \, \varphi(\mathbf{h}) + \mathbf{u}(t)"
        ),
        "callout_text": (
            "Важно: RNN-модель воспроизводит трибуны нейронной активности"
            " (low-dimensional manifolds), но не объясняет, почему именно"
            " такая геометрия."
        ),
        "bullets": [
            "Low-dimensional dynamics в моторной коре",
            "Line attractors и working memory",
            "Sequence memory через chaotic transients",
            "Reservoir computing как нулевая гипотеза",
        ],
        "quote": (
            "“RNNs are not models of the brain; they are models OF models"
            " of the brain.” — Sussillo, 2014."
        ),
        "code": (
            "import jax.numpy as jnp\n\n"
            "def rnn_step(h, x, W_rec, W_in):\n"
            "    return jnp.tanh(W_rec @ h + W_in @ x)\n"
        ),
        "code_lang": "python",
        "mention_usernames": ["alice_neuro", "david_ml"],
        "image_seed": "rnncortex",
        "image_caption": "Динамика RNN в моторной коре",
        "link_href": "https://www.nature.com/articles/s41593-019-0520-2",
        "link_text": "Vyas et al., Computation Through Neural Population Dynamics",
        "conclusion": (
            "Следующий шаг — нелинейные операторы и attention-механизмы"
            " как добавка к чисто рекуррентному ядру."
        ),
        "inline_math": "\\mathbf{h}_t \\in \\mathbb{R}^d",
    },
    {
        "topic_slug": "bold-signal-interpretation",
        "author_username": "bob_imaging",
        "title": "Что на самом деле говорит BOLD-сигнал: между нейронами и гемодинамикой",
        "intro": (
            "BOLD-сигнал — наш основной окно в активность мозга через"
            " fMRI, но он измеряет не нейронную активность напрямую, а"
            " гемодинамический отклик. Что мы можем и не можем сказать на"
            " его основе?"
        ),
        "formula_intro": (
            "Канонический BOLD-отклик моделируется суммой двух гамма-функций:"
        ),
        "formula_latex": (
            r"h(t) = \frac{t^{\alpha_1 - 1} e^{-t/\beta_1}}{\Gamma(\alpha_1) \beta_1^{\alpha_1}}"
            r" - c \, \frac{t^{\alpha_2 - 1} e^{-t/\beta_2}}{\Gamma(\alpha_2) \beta_2^{\alpha_2}}"
        ),
        "callout_text": (
            "Помни: BOLD — это neurovascular coupling, не spikes. Любые"
            " выводы про популяционные коды требуют дополнительной"
            " валидации."
        ),
        "bullets": [
            "Каноническая HRF удобна, но не универсальна",
            "Регион-специфичные HRF в V1, M1, ventral stream",
            "Negative BOLD как индикатор торможения",
            "Влияние сосудистого тонуса в стареющем мозге",
        ],
        "quote": (
            "“The relationship between the BOLD signal and neuronal"
            " activity is complex and incompletely understood.” — Logothetis, 2008."
        ),
        "code": (
            "from nilearn.glm import compute_hrf\n"
            "import numpy as np\n\n"
            "hrf = compute_hrf(tr=2.0, oversampling=16, time_length=32.0)\n"
            "print(np.argmax(hrf), 'peak at')\n"
        ),
        "code_lang": "python",
        "mention_usernames": ["alice_neuro", "frank_methods"],
        "image_seed": "boldhrf",
        "image_caption": "Канонический BOLD-отклик",
        "link_href": "https://doi.org/10.1038/nature06976",
        "link_text": "Logothetis, What we can do and what we cannot do with fMRI",
        "conclusion": (
            "BOLD-эксперименты ценны, если ясно проговаривать, что именно"
            " измеряется и какие предположения делаются."
        ),
        "inline_math": "\\Delta R_2^*",
    },
    {
        "topic_slug": "diffusion-tractography-pitfalls",
        "author_username": "bob_imaging",
        "title": "Подводные камни diffusion tractography",
        "intro": (
            "Diffusion MRI tractography обещает реконструкцию пучков"
            " аксонов in vivo. На практике — алгоритмы регулярно"
            " пропускают известные пучки и придумывают несуществующие."
        ),
        "formula_intro": (
            "Diffusion tensor описывается симметричной матрицей с"
            " собственными числами λ₁ ≥ λ₂ ≥ λ₃, fractional anisotropy"
            " считается как:"
        ),
        "formula_latex": (
            r"\mathrm{FA} = \sqrt{\frac{3}{2}} \,"
            r" \frac{\sqrt{(\lambda_1 - \bar\lambda)^2 + (\lambda_2 - \bar\lambda)^2 + (\lambda_3 - \bar\lambda)^2}}"
            r"{\sqrt{\lambda_1^2 + \lambda_2^2 + \lambda_3^2}}"
        ),
        "callout_text": (
            "Crossing fibers убивают tensor-модель — нужны hardi-протоколы"
            " и более сложные алгоритмы (CSD, MSMT)."
        ),
        "bullets": [
            "False positives в long-range connections",
            "Gyral bias в кортикальных терминалах",
            "Crossing/kissing/fanning артефакты",
            "Hemispheric asymmetry intepretation",
        ],
        "quote": (
            "“Tractography is best regarded as an exploratory tool.” —"
            " Maier-Hein et al., 2017."
        ),
        "code": (
            "import dipy.reconst.dti as dti\n"
            "tenmodel = dti.TensorModel(gtab)\n"
            "tenfit = tenmodel.fit(data)\n"
            "fa = tenfit.fa\n"
        ),
        "code_lang": "python",
        "mention_usernames": ["frank_methods"],
        "image_seed": "tractography",
        "image_caption": "Пример crossing fibers артефакта",
        "link_href": "https://www.nature.com/articles/s41467-017-01285-x",
        "link_text": "Maier-Hein et al., The challenge of mapping the human connectome",
        "conclusion": (
            "Не интерпретируйте tractography как анатомическую истину —"
            " только как гипотезу."
        ),
        "inline_math": "\\mathrm{FA} \\in [0, 1]",
    },
    {
        "topic_slug": "working-memory-mechanisms",
        "author_username": "eve_cognition",
        "title": "Механизмы рабочей памяти: где мы сейчас",
        "intro": (
            "Working memory (WM) — рабочая лошадка когнитивных процессов."
            " Старые модели persistent activity vs новые activity-silent"
            " теории — какие данные на чьей стороне?"
        ),
        "formula_intro": (
            "Капасити WM по Bays & Husain моделируется через precision и"
            " набор слотов:"
        ),
        "formula_latex": (
            r"p(\hat\theta \mid \theta, k) = \kappa \exp(\kappa \cos(\hat\theta - \theta)) / (2 \pi I_0(\kappa))"
        ),
        "callout_text": (
            "Note: модели слотов и continuous resource не взаимоисключаемы"
            " — современный консенсус смешанный."
        ),
        "bullets": [
            "Persistent activity в PFC: остаётся ли важной?",
            "Silent memory через synaptic traces",
            "Connection to attention bottleneck",
            "Aging effects on capacity",
        ],
        "quote": (
            "“Working memory may not be a single thing.” — D'Esposito, 2007."
        ),
        "code": (
            "from scipy.stats import vonmises\n"
            "kappa = 4.0\n"
            "err = np.linspace(-np.pi, np.pi, 100)\n"
            "p = vonmises.pdf(err, kappa)\n"
        ),
        "code_lang": "python",
        "mention_usernames": ["alice_neuro", "grace_clinical"],
        "image_seed": "wm",
        "image_caption": "Distribution of recall errors",
        "link_href": "https://doi.org/10.1146/annurev-psych-010418-103352",
        "link_text": "Oberauer et al., Benchmarks for models of working memory",
        "conclusion": (
            "WM скорее всего — семья процессов, не один монолитный"
            " механизм."
        ),
        "inline_math": "\\kappa",
    },
    {
        "topic_slug": "transformer-eeg-decoding",
        "author_username": "david_ml",
        "title": "Transformers для декодирования EEG: что получается и что нет",
        "intro": (
            "Attention-based архитектуры начали проникать в EEG-pipeline."
            " Привычные CNN/RNN постепенно уступают трансформерам в"
            " sleep staging, BCI-control и motor imagery."
        ),
        "formula_intro": (
            "Scaled dot-product attention лежит в основе любого"
            " трансформера:"
        ),
        "formula_latex": (
            r"\mathrm{Attention}(Q, K, V) = \mathrm{softmax}\!\left( \frac{Q K^T}{\sqrt{d_k}} \right) V"
        ),
        "callout_text": (
            "Главный риск — переобучение на канал-специфичных артефактах,"
            " не на нейрофизиологически значимом сигнале."
        ),
        "bullets": [
            "EEGNet → Conformer → EEG-Transformer",
            "Self-supervised pretraining на больших наборах",
            "Cross-subject generalization",
            "Quantizing latency для real-time BCI",
        ],
        "quote": (
            "“Attention is all you need.” — Vaswani et al., 2017."
        ),
        "code": (
            "import torch.nn as nn\n"
            "encoder_layer = nn.TransformerEncoderLayer(d_model=64, nhead=8)\n"
            "encoder = nn.TransformerEncoder(encoder_layer, num_layers=4)\n"
        ),
        "code_lang": "python",
        "mention_usernames": ["carla_compneuro", "frank_methods"],
        "image_seed": "transformeeg",
        "image_caption": "Attention карта над EEG-каналами",
        "link_href": "https://arxiv.org/abs/2106.10071",
        "link_text": "Song et al., EEG Conformer for cognition decoding",
        "conclusion": (
            "Трансформеры пока не вытесняют CNN полностью — но в задачах"
            " с длинным контекстом уже выигрывают."
        ),
        "inline_math": "d_k",
    },
    {
        "topic_slug": "nilearn-pipeline-tips",
        "author_username": "frank_methods",
        "title": "Nilearn: типичные ошибки в pipeline и как их избежать",
        "intro": (
            "Nilearn — стандарт де факто для статистического анализа"
            " fMRI на Python. За простой API скрывается ряд ловушек,"
            " куда регулярно попадают новички и не только."
        ),
        "formula_intro": (
            "GLM-модель остается рабочей лошадкой. Регрессионная схема:"
        ),
        "formula_latex": (
            r"Y = X \beta + \varepsilon, \quad \hat\beta = (X^T X)^{-1} X^T Y"
        ),
        "callout_text": (
            "Внимание: high-pass filter и smoothing меняют residuals."
            " Всегда проверяйте порядок операций."
        ),
        "bullets": [
            "Не делайте smoothing после ICA-cleanup",
            "Правильно стройте design matrix для блок-дизайна",
            "Используйте сохранённые masks между сессиями",
            "Не доверяйте default thresholds — считайте FWER честно",
        ],
        "quote": (
            "“The single most important step in fMRI analysis is the"
            " sanity check of the design matrix.” — Poldrack, 2017."
        ),
        "code": (
            "from nilearn.glm.first_level import FirstLevelModel\n\n"
            "model = FirstLevelModel(t_r=2.0, high_pass=1/128)\n"
            "model = model.fit(bold_imgs, events=events)\n"
        ),
        "code_lang": "python",
        "mention_usernames": ["bob_imaging"],
        "image_seed": "nilearn",
        "image_caption": "Пример design matrix",
        "link_href": "https://nilearn.github.io/stable/",
        "link_text": "Nilearn documentation",
        "conclusion": (
            "Pipeline — это документ, не скрипт. Версионируйте всё, что"
            " может повлиять на оценки."
        ),
        "inline_math": "X^T X",
    },
    {
        "topic_slug": "journal-club-weekly",
        "author_username": "henry_news",
        "title": "Journal club, июнь 2026: главные препринты недели",
        "intro": (
            "В этом выпуске — три препринта, которые на этой неделе"
            " разогрели обсуждения. Соберём ключевые тезисы и приглашаем"
            " к дискуссии."
        ),
        "formula_intro": (
            "В одном из обсуждаемых препринтов оценивается"
            " mutual information между representations и поведением:"
        ),
        "formula_latex": (
            r"I(X; Y) = \sum_{x, y} p(x, y) \log \frac{p(x, y)}{p(x) p(y)}"
        ),
        "callout_text": (
            "Note: для high-dimensional оценок MI используются нейросетевые"
            " оценщики (MINE, InfoNCE) — будьте осторожны с биасом."
        ),
        "bullets": [
            "Anderson et al. — connectome scaling laws в C. elegans",
            "Garcia-Castro et al. — Cortical replay во сне у приматов",
            "Park et al. — Neural decoding под анестезией",
            "Discussion: replicability score на ALBI",
        ],
        "quote": (
            "“Preprints без обсуждения — это сырая руда.” — local wisdom"
        ),
        "code": (
            "# Сравнение MI estimators\n"
            "from npeet import entropy_estimators as ee\n"
            "mi = ee.mi(x, y, k=5)\n"
        ),
        "code_lang": "python",
        "mention_usernames": ["alice_neuro", "iris_lab", "jack_student"],
        "image_seed": "journalclub",
        "image_caption": "Раздаточный материал journal club",
        "link_href": "https://www.biorxiv.org/",
        "link_text": "bioRxiv: свежие препринты",
        "conclusion": (
            "Следующая встреча — через неделю. Подавайте кандидатов в"
            " голосование."
        ),
        "inline_math": "I(X; Y)",
    },
]


SHORT_ARTICLE_BLUEPRINTS: list[dict[str, Any]] = [
    # computational-neuroscience — attractor dynamics
    {
        "topic_slug": "attractor-dynamics-motor-cortex",
        "author_username": "carla_compneuro",
        "title": "Attractor dynamics в моторной коре: обзор 2026",
        "summary": "Как популяции нейронов организуют движение через низкоразмерные аттракторы.",
        "section_intro": "Обзор недавних работ, показывающих, что подготовка движения реализуется через ротационные аттракторы в M1, а не последовательное «включение» нейронов.",
        "subheading": "Ключевые находки",
        "bullets": [
            "Vyas et al. (2020) — универсальность rotational dynamics",
            "Churchland lab — подготовительная активность живёт на своём подпространстве",
            "Aoi & Kao (2020) — иерархия временных масштабов",
        ],
        "formula_latex": r"\dot{\mathbf{x}} = -\mathbf{x} + W\varphi(\mathbf{x}) + \mathbf{u}(t)",
        "image_seed": "attractor-motor",
        "image_caption": "Схема rotational subspace в M1",
        "closing": "Открытый вопрос: universal ли эти паттерны для всех приматов?",
    },
    # computational-neuroscience — bayesian brain
    {
        "topic_slug": "bayesian-brain-hypothesis-review",
        "author_username": "alice_neuro",
        "title": "Bayesian brain hypothesis: критический обзор",
        "summary": "Что удалось подтвердить, что осталось hand-wavy.",
        "section_intro": "Гипотеза байесовского мозга — красивая, но эмпирические тесты на удивление слабые. Разберёмся почему.",
        "subheading": "Аргументы за и против",
        "bullets": [
            "PRO: perceptual biases соответствуют байесовским priors (Weiss et al.)",
            "PRO: neural correlates uncertainty (Ma & Jazayeri, 2014)",
            "CON: экологическая валидность priors под вопросом",
            "CON: cortical circuits не реализуют exact Bayesian inference",
        ],
        "formula_latex": r"P(\theta|D) = \frac{P(D|\theta)\,P(\theta)}{P(D)}",
        "image_seed": "bayes-brain",
        "image_caption": "Иерархия предсказаний в кортикальных слоях",
        "closing": "TL;DR: скорее эвристика ближе к MAP, чем полноценная Bayesian inference.",
    },
    # neuroimaging — resting state
    {
        "topic_slug": "resting-state-fmri-networks",
        "author_username": "bob_imaging",
        "title": "Resting-state fMRI: 15 лет спустя",
        "summary": "Что мы узнали про default mode network и что она не показывает.",
        "section_intro": "После работ Raichle 2001 rs-fMRI взлетел. Обсудим, что action items выдержали проверку временем.",
        "subheading": "Устоявшиеся находки",
        "bullets": [
            "DMN стабильно репродуцируется в разных когортах",
            "Функциональные сети коррелируют со структурой (DWI)",
            "Individual differences в connectivity ↔ поведение (Finn 2015)",
            "Reliability низкая на коротких скан-сессиях (<10 min)",
        ],
        "formula_latex": r"r_{ij} = \frac{\sum_t (x_i^t - \bar{x_i})(x_j^t - \bar{x_j})}{\sigma_{x_i}\sigma_{x_j}}",
        "image_seed": "rsfmri-networks",
        "image_caption": "7-network parcellation Yeo et al.",
        "closing": "Что дальше: наивная functional connectivity как биомаркер уходит, on-topic — dynamic + graph-based метрики.",
    },
    # neuroimaging — GLM vs MVPA
    {
        "topic_slug": "glm-vs-mvpa-2026",
        "author_username": "bob_imaging",
        "title": "GLM vs MVPA: когда какой подход",
        "summary": "Univariate vs multivariate — не заменяют друг друга, а решают разные вопросы.",
        "section_intro": "Практический guide: когда достаточно GLM, а когда MVPA даёт содержательный вклад.",
        "subheading": "Что выбирать",
        "bullets": [
            "GLM: локализация активности, hypothesis-driven contrasts",
            "MVPA: представления, декодирование конкретных категорий",
            "RSA (representational similarity): сравнение геометрий между модели/мозг",
            "Не забывайте про cross-validation в MVPA — иначе overfitting",
        ],
        "formula_latex": r"\text{acc} = \frac{1}{k}\sum_{i=1}^{k}\mathbb{1}[\hat{y}_i = y_i]",
        "image_seed": "glm-mvpa",
        "image_caption": "GLM contrast map vs MVPA searchlight",
        "closing": "Гибридные подходы (GLM + RSA) — самое интересное направление 2026.",
    },
    # cognitive-neuroscience — attention & consciousness
    {
        "topic_slug": "attention-and-consciousness",
        "author_username": "eve_cognition",
        "title": "Внимание и сознание: нейронные корреляты",
        "summary": "Global workspace theory vs integrated information theory — status quo.",
        "section_intro": "Обзор недавних экспериментов, которые тестируют GWT (Dehaene, Baars) vs IIT (Tononi) через adversarial collaborations.",
        "subheading": "Adversarial предсказания",
        "bullets": [
            "GWT предсказывает ignition в front-parietal cortex",
            "IIT предсказывает posterior hot zone",
            "Ferrante et al. 2023 — данные не решают спор однозначно",
            "Нужны более чувствительные paradigms",
        ],
        "formula_latex": r"\Phi = \min_{P \in \mathcal{P}} D_{KL}(p(X)\,\|\,p_P(X))",
        "image_seed": "attention-conscious",
        "image_caption": "Пре-регистрированные предсказания GWT vs IIT",
        "closing": "Пока ни одна теория не «выиграла», но эксперименты становятся всё изящнее.",
    },
    # cognitive-neuroscience — dual process
    {
        "topic_slug": "dual-process-theory-decisions",
        "author_username": "eve_cognition",
        "title": "Dual-process теории принятия решений",
        "summary": "Быстрое vs медленное мышление — что говорит нейронаука.",
        "section_intro": "Kahneman прочно засел в поп-психологии. Что реально видно на fMRI и EEG?",
        "subheading": "Что действительно бывает",
        "bullets": [
            "Автоматические ответы — быстрый striatal habit system",
            "Аналитические — DLPFC + parietal control network",
            "Переключение регулируется ACC (conflict monitoring)",
            "Но: это не два бинарных «режима», а continuum",
        ],
        "formula_latex": r"V(a) = \sum_s P(s|a)\,U(s)",
        "image_seed": "dual-process",
        "image_caption": "System 1 vs System 2 схематически",
        "closing": "Кризис репликации не миновал и эту область — треть популярных находок не воспроизводится.",
    },
    # machine-learning-brain — deep generative
    {
        "topic_slug": "deep-generative-models-eeg",
        "author_username": "david_ml",
        "title": "Deep generative models для генерации EEG",
        "summary": "VAE, GAN, diffusion — что реально работает для нейросигналов.",
        "section_intro": "Синтетические EEG-данные для аугментации, приватности и симуляции.",
        "subheading": "Обзор архитектур",
        "bullets": [
            "GAN (Hartmann 2018) — реалистичные wavelets, но mode collapse",
            "VAE — стабильно, но smooth signals без high-freq deталей",
            "Diffusion (2023-2024) — SOTA по FID + spectral matching",
            "Оценка качества всё ещё не решена — нет consensus metric",
        ],
        "formula_latex": r"\mathcal{L} = \mathbb{E}_{t,\epsilon}\|\epsilon - \epsilon_\theta(\mathbf{x}_t, t)\|^2",
        "image_seed": "gen-eeg",
        "image_caption": "Diffusion training loop для EEG",
        "closing": "Downstream: augmented training + differential privacy — killer app.",
    },
    # machine-learning-brain — graph nets
    {
        "topic_slug": "graph-nets-on-connectomes",
        "author_username": "david_ml",
        "title": "Graph neural nets на коннектомах",
        "summary": "GNN для brain connectivity: обзор моделей + подводные камни.",
        "section_intro": "Мозг — граф. GNN — естественный fit. Но результаты пока mixed.",
        "subheading": "Что важно помнить",
        "bullets": [
            "GCN / GAT / GraphSAGE — стандартный zoo",
            "Проблема: маленькие датасеты (n<1000 участников)",
            "Interpretability методов слабая: attention veghts != causal",
            "Comparison to simple baselines редко fair",
        ],
        "formula_latex": r"\mathbf{h}_v^{(l+1)} = \sigma\!\left(\sum_{u \in \mathcal{N}(v)} \frac{1}{c_{uv}} W^{(l)} \mathbf{h}_u^{(l)}\right)",
        "image_seed": "gnn-connectome",
        "image_caption": "Message passing на brain graph",
        "closing": "Reproducibility crisis: publications не воспроизводятся, если убрать один трюк.",
    },
    # methods-tools — pytorch vs jax
    {
        "topic_slug": "pytorch-vs-jax-for-neuro",
        "author_username": "frank_methods",
        "title": "PyTorch vs JAX для нейронауки в 2026",
        "summary": "Куда двигаться neuro-ML коммьюнити?",
        "section_intro": "После нескольких лет борьбы: PyTorch уверенно лидирует по ecosystem, но JAX выигрывает в моделирующих задачах.",
        "subheading": "Кому что",
        "bullets": [
            "PyTorch: prototyping, transfer learning, стандартный ML pipeline",
            "JAX: differentiable simulation (jax.grad + jit), neuroscience-specific",
            "Julia: остался в нише, но растёт в neurosimulations",
            "TensorFlow: практически ушёл из neuro-research",
        ],
        "formula_latex": r"\theta_{t+1} = \theta_t - \eta \nabla_\theta \mathcal{L}(\theta_t)",
        "image_seed": "pytorch-jax",
        "image_caption": "Benchmark: forward + backward на NeurIPS benchmark",
        "closing": "Для neuromechanistic моделей JAX — уже де-факто стандарт. Для applied ML — PyTorch.",
    },
    # methods-tools — open datasets
    {
        "topic_slug": "open-neurodata-datasets",
        "author_username": "frank_methods",
        "title": "Open neurodata: датасеты, которыми стоит пользоваться",
        "summary": "Систематизированный обзор доступных нейродатасетов на 2026.",
        "section_intro": "Если пишете paper с публикацией кода, вот куда посмотреть.",
        "subheading": "Ключевые репозитории",
        "bullets": [
            "Human Connectome Project — sMRI + dMRI + rs-fMRI n=1200",
            "UK Biobank — n=100000+, но access controlled",
            "OpenNeuro — стандартизация BIDS, любые модальности",
            "MOABB — motor imagery EEG benchmarks",
            "NWB (Neurodata Without Borders) — становится стандартом",
        ],
        "formula_latex": r"\text{coverage} = \frac{|\{\text{datasets with FAIR compliance}\}|}{|\text{all datasets}|}",
        "image_seed": "open-neurodata",
        "image_caption": "Ecosystem открытых нейродатасетов",
        "closing": "Reminder: препринт без reproducible dataset & code — этика 2020, не 2026.",
    },
    # news-discussion — arxiv digest
    {
        "topic_slug": "weekly-arxiv-digest",
        "author_username": "henry_news",
        "title": "arXiv-дайджест недели: новинки q-bio.NC",
        "summary": "Обзор трёх интересных препринтов этой недели.",
        "section_intro": "Отбирал по критерию «релевантно + методологически чисто».",
        "subheading": "Топ-3 недели",
        "bullets": [
            "Neural population dynamics during reaching movements — новый multi-region recording",
            "Predictive coding in early visual cortex — refined MEG evidence",
            "Cortical connectomics at 1000 neurons scale — MICrONS follow-up",
        ],
        "formula_latex": r"H(P||Q) = \sum_i P(i) \log\frac{P(i)}{Q(i)}",
        "image_seed": "arxiv-digest",
        "image_caption": "Trending темы q-bio.NC (последние 7 дней)",
        "closing": "Комментируйте, что показалось интересным — соберём коллективный ranking.",
    },
    # news-discussion — neurips
    {
        "topic_slug": "neurips-2026-highlights",
        "author_username": "henry_news",
        "title": "NeurIPS 2026: highlights от neuro-track",
        "summary": "Что смотреть из NeurIPS 2026 сессии по нейронаукам.",
        "section_intro": "Тезисы с neuro-related треков конференции.",
        "subheading": "Заслуживают внимания",
        "bullets": [
            "Workshop «Brain-Score» — метрика для сравнения модель↔мозг",
            "Oral: contrastive learning на brain-behaviour paired data",
            "Poster: MERLIN — новый фреймворк для generative brain models",
            "Panel: interpretability of DNNs modeling visual cortex",
        ],
        "formula_latex": r"L_{\text{NCE}} = -\mathbb{E}_{(x,y^+)}\log\frac{e^{f(x,y^+)}}{\sum_{y}e^{f(x,y)}}",
        "image_seed": "neurips-2026",
        "image_caption": "Word cloud neuroscience mentions в NeurIPS 2026 papers",
        "closing": "Сохраняйте темы, обменяемся ссылками — соберу компилацию.",
    },
]


async def create_articles(
    db: AsyncSession,
    articles_svc: ArticleService,
    topics: dict[str, Topic],
    users: dict[str, User],
) -> list[Article]:
    """Create + publish one article per blueprint. Returns list of articles."""
    created: list[Article] = []
    for blueprint in ARTICLE_BLUEPRINTS:
        author = users[blueprint["author_username"]]
        topic = topics[blueprint["topic_slug"]]
        mention_targets = [users[u] for u in blueprint["mention_usernames"]]

        image_attachment_id = await _make_seed_attachment(
            db, author, blueprint["image_seed"]
        )

        content_dict = _build_article_doc(
            title=blueprint["title"],
            intro=blueprint["intro"],
            formula_latex=blueprint["formula_latex"],
            formula_intro=blueprint["formula_intro"],
            callout_text=blueprint["callout_text"],
            bullets=blueprint["bullets"],
            quote=blueprint["quote"],
            code=blueprint["code"],
            code_lang=blueprint["code_lang"],
            mention_targets=mention_targets,
            image_attachment_id=image_attachment_id,
            image_seed=blueprint["image_seed"],
            image_caption=blueprint["image_caption"],
            link_href=blueprint["link_href"],
            link_text=blueprint["link_text"],
            conclusion=blueprint["conclusion"],
        )

        article, _ = await articles_svc.create_article(
            author,
            topic.id,
            ArticleCreate(
                title=blueprint["title"],
                content=DocSchema.model_validate(content_dict),
            ),
        )
        published, _ = await articles_svc.publish_article(author, article.id)

        # Backdate ``published_at`` so the feed has variety. Within the
        # last 1–30 days, deterministic via random.seed(42).
        days_ago = random.randint(1, 30)
        ts = datetime.now(UTC) - timedelta(days=days_ago)
        await db.execute(
            update(Article)
            .where(Article.id == published.id)
            .values(published_at=ts)
        )
        await db.flush()
        created.append(published)

    # Short blueprints — filler content so section listings show ≥3 items.
    for blueprint in SHORT_ARTICLE_BLUEPRINTS:
        author = users[blueprint["author_username"]]
        topic = topics[blueprint["topic_slug"]]
        image_attachment_id = await _make_seed_attachment(
            db, author, blueprint["image_seed"]
        )
        content_dict = _build_short_news_doc(
            title=blueprint["title"],
            summary=blueprint["summary"],
            section_intro=blueprint["section_intro"],
            subheading=blueprint["subheading"],
            bullets=blueprint["bullets"],
            formula_latex=blueprint["formula_latex"],
            image_attachment_id=image_attachment_id,
            image_seed=blueprint["image_seed"],
            image_caption=blueprint["image_caption"],
            closing=blueprint["closing"],
        )
        article, _ = await articles_svc.create_article(
            author,
            topic.id,
            ArticleCreate(
                title=blueprint["title"],
                summary=blueprint["summary"],
                content=DocSchema.model_validate(content_dict),
            ),
        )
        published, _ = await articles_svc.publish_article(author, article.id)
        days_ago = random.randint(1, 14)
        ts = datetime.now(UTC) - timedelta(days=days_ago)
        await db.execute(
            update(Article)
            .where(Article.id == published.id)
            .values(published_at=ts)
        )
        await db.flush()
        created.append(published)
    return created


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


COMMENT_TEMPLATES: list[str] = [
    "Отличный обзор. Не хватило обсуждения нелинейных эффектов.",
    "Помогло — особенно блок про формулы. Спасибо!",
    "А что насчёт обобщения на multimodal-данные?",
    "Есть аналогичная работа Smith et al. 2025, стоит сравнить.",
    "Согласен с автором, но осторожнее с интерпретацией.",
    "В моей лаборатории мы получили противоположный результат — пришлю детали.",
    "Можете дать ссылку на dataset?",
    "Эта картинка нуждается в пояснении.",
    "Вопрос: какие baseline-модели вы сравнивали?",
    "Будет ли follow-up препринт?",
    "Скептичен относительно FEP, но аргументы любопытные.",
    "Идея заходит, спасибо что подняли тему.",
]


async def create_messages(
    db: AsyncSession,
    messages_svc: MessageService,
    articles: Iterable[Article],
    users: dict[str, User],
    *,
    min_count: int = 5,
    max_count: int = 10,
    force_deep_chain: bool = True,
) -> int:
    """Build 5–12 messages per article, with at least 2 replies + 1 depth-2."""
    user_list = list(users.values())
    total = 0
    for article in articles:
        author_id = article.author_id
        # Choose msg count + ensure at least one reply chain.
        count = random.randint(min_count, max_count)
        msgs: list[Any] = []
        for _ in range(count):
            commenter = random.choice(
                [u for u in user_list if u.id != author_id]
            )
            content_text = random.choice(COMMENT_TEMPLATES)
            # ~30% of messages: reply to an earlier message in the article.
            parent_id = None
            if msgs and random.random() < 0.4:
                parent_id = random.choice(msgs).id
            doc_payload = doc(
                [
                    paragraph(
                        [
                            text_node(content_text),
                            text_node(" "),
                            text_node(
                                "интересно",
                                marks=[{"type": "italic"}],
                            ),
                            text_node("!"),
                        ]
                    )
                ]
            )
            message, _ = await messages_svc.post_message(
                commenter,
                article.id,
                MessageCreate(
                    content=DocSchema.model_validate(doc_payload),
                    parent_id=parent_id,
                ),
            )
            msgs.append(message)
            total += 1

        # Force at least one depth-2 chain.
        if force_deep_chain and msgs:
            roots = [m for m in msgs if m.parent_id is None]
            if roots:
                first_reply, _ = await messages_svc.post_message(
                    random.choice(user_list),
                    article.id,
                    MessageCreate(
                        content=DocSchema.model_validate(
                            doc(
                                [paragraph([text_node("Согласен с этой веткой.")])]
                            )
                        ),
                        parent_id=roots[0].id,
                    ),
                )
                msgs.append(first_reply)
                total += 1
                deep, _ = await messages_svc.post_message(
                    random.choice(user_list),
                    article.id,
                    MessageCreate(
                        content=DocSchema.model_validate(
                            doc(
                                [
                                    paragraph(
                                        [
                                            text_node("Уточняющий вопрос: "),
                                            text_node(
                                                "что именно вы имели в виду?",
                                                marks=[{"type": "bold"}],
                                            ),
                                        ]
                                    )
                                ]
                            )
                        ),
                        parent_id=first_reply.id,
                    ),
                )
                msgs.append(deep)
                total += 1
    return total


# ---------------------------------------------------------------------------
# Reactions + saved + DM
# ---------------------------------------------------------------------------


REACTION_KINDS: list[ReactionKind] = list(ReactionKind)


async def create_reactions(
    db: AsyncSession,
    reactions_svc: ReactionService,
    articles: Iterable[Article],
    users: dict[str, User],
) -> None:
    """Random 2–5 reactors per article + reactions on subset of messages."""
    user_list = list(users.values())
    for article in articles:
        reactors = random.sample(user_list, k=random.randint(2, 5))
        for reactor in reactors:
            kind = random.choice(REACTION_KINDS)
            await reactions_svc.react_to_article(reactor, article.id, kind)

    # Sample a few messages too.
    messages = (
        await db.execute(
            select(text("id"))
            .select_from(text("messages"))
            .where(text("status = 'visible'"))
            .order_by(text("created_at"))
            .limit(40)
        )
    ).all()
    for row in random.sample(messages, k=min(20, len(messages))):
        message_id = UUID(str(row[0]))
        for reactor in random.sample(user_list, k=random.randint(1, 3)):
            kind = random.choice(REACTION_KINDS)
            try:
                await reactions_svc.react_to_message(reactor, message_id, kind)
            except Exception:
                # Message may have been soft-deleted in a deeper round.
                continue


async def create_saved(
    db: AsyncSession,
    saved_svc: SavedService,
    articles: list[Article],
    users: dict[str, User],
) -> None:
    """Each user saves 2–3 random articles."""
    for user in users.values():
        picks = random.sample(articles, k=min(len(articles), random.randint(2, 3)))
        for article in picks:
            await saved_svc.save(user, article.id)


async def create_dms(
    db: AsyncSession,
    dm_svc: DMService,
    users: dict[str, User],
) -> None:
    """Three DM conversations with prearranged content."""
    threads: list[tuple[str, str, list[tuple[str, str]]]] = [
        (
            "alice_neuro",
            "bob_imaging",
            [
                ("alice_neuro", "Привет, видел реплику на наш rebuttal?"),
                ("bob_imaging", "Да, готов набросок ответа на review 2."),
                ("alice_neuro", "Главное — закрыть вопрос про HRF."),
                ("bob_imaging", "Согласен, добавлю ссылку на Logothetis."),
                ("alice_neuro", "Прекрасно, отправляй финальную версию."),
            ],
        ),
        (
            "carla_compneuro",
            "david_ml",
            [
                ("carla_compneuro", "Думаю про коллаб по transformer×RNN."),
                ("david_ml", "Звучит! Поделись черновиком idea-draft."),
                ("carla_compneuro", "Скину в воскресенье, нужно структурировать."),
            ],
        ),
        (
            "eve_cognition",
            "frank_methods",
            [
                ("eve_cognition", "Frank, помоги с design matrix в nilearn."),
                ("frank_methods", "Конечно. Какие условия в эксперименте?"),
                ("eve_cognition", "Block + event-related, 4 условия."),
                ("frank_methods", "Соберу шаблон, шлю через час."),
            ],
        ),
    ]

    for a_name, b_name, messages in threads:
        a = users[a_name]
        b = users[b_name]
        conversation = await dm_svc.start_dm(a, b.id)
        for username, body in messages:
            sender = users[username]
            payload = DirectMessageCreate(
                content=DocSchema.model_validate(
                    doc([paragraph([text_node(body)])])
                )
            )
            await dm_svc.send_message(sender, conversation.id, payload)


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


async def main() -> None:
    engine = create_async_engine(settings.DATABASE_URL, echo=False, future=True)
    session_factory = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )

    async with session_factory() as cleanup_session:
        await truncate_all(cleanup_session)

    async with session_factory() as db:
        users_svc = UserService(UserRepository(db), db)
        mentions_svc = MentionService(MentionRepository(db), db)
        notifications_svc = NotificationService(NotificationRepository(db), db)
        forum_svc = ForumService(ForumRepository(db), db)
        articles_svc = ArticleService(
            ArticleRepository(db),
            ForumRepository(db),
            db,
            mention_service=mentions_svc,
            notification_service=notifications_svc,
            user_service=users_svc,
        )
        messages_svc = MessageService(
            MessageRepository(db),
            db,
            mention_service=mentions_svc,
            notification_service=notifications_svc,
            user_service=users_svc,
        )
        reactions_svc = ReactionService(db)
        saved_svc = SavedService(SavedRepository(db), db)
        dm_svc = DMService(DMRepository(db), UserRepository(db), db)

        users = await create_users(db, users_svc)
        admin = users["alice_neuro"]
        sections = await create_sections(db, forum_svc, admin)
        topics = await create_topics(db, forum_svc, sections, users)
        articles = await create_articles(db, articles_svc, topics, users)
        extra_articles = await create_extra_articles(
            db, articles_svc, topics, sections, users
        )
        msg_count = await create_messages(db, messages_svc, articles, users)
        # Lighter footprint for discussion/help/flood containers.
        extra_msg_count = await create_messages(
            db,
            messages_svc,
            extra_articles,
            users,
            min_count=3,
            max_count=5,
            force_deep_chain=False,
        )
        await create_reactions(db, reactions_svc, articles, users)
        await create_saved(db, saved_svc, articles, users)
        await create_dms(db, dm_svc, users)

        await db.commit()

    # Backfill denormalised counters against the actual row counts in case
    # any service-level bump went missing for old seed runs. Idempotent +
    # safe to run again.
    async with session_factory() as backfill_session:
        await recompute_all_stats(backfill_session)

    total_articles = len(articles) + len(extra_articles)
    total_messages = msg_count + extra_msg_count
    print(
        f"Seeded {len(users)} users, {len(sections)} sections,"
        f" {len(topics)} topics, {total_articles} articles,"
        f" ~{total_messages} messages, 3 DM conversations."
    )

    await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        sys.exit(1)
