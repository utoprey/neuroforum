"""Service-layer tests for the ``agents`` module."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agents import crypto
from app.modules.agents.exceptions import (
    AgentNotFound,
    AgentTokenNotFound,
    CredentialNameTaken,
    CredentialNotFound,
    NotAgentOwner,
    NotAgentTokenOwner,
    NotCredentialOwner,
)
from app.modules.agents.models import LLMProvider, LLMUsageStatus
from app.modules.agents.repository import AgentRepository
from app.modules.agents.schemas import (
    AgentCreate,
    AgentCredentialCreate,
    AgentCredentialUpdate,
)
from app.modules.agents.service import AgentService
from app.modules.users.exceptions import UsernameTaken
from app.modules.users.models import Role, User
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import UserCreate
from app.modules.users.service import UserService

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def users_svc(db_session: AsyncSession) -> UserService:
    return UserService(UserRepository(db_session), db_session)


@pytest.fixture
def agents_svc(db_session: AsyncSession) -> AgentService:
    return AgentService(
        AgentRepository(db_session), UserRepository(db_session), db_session
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
            email=f"{username}@ag.io",
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


# ---------------------------------------------------------------------------
# Crypto module
# ---------------------------------------------------------------------------


def test_crypto_roundtrip() -> None:
    plaintext = "sk-test-1234567890abcdef"
    ct = crypto.encrypt(plaintext)
    assert isinstance(ct, bytes)
    assert ct != plaintext.encode()
    assert crypto.decrypt(ct) == plaintext


def test_fingerprint_format() -> None:
    fp = crypto.fingerprint("sk-test-abcd")
    # Format: ***-<last4>-<sha256[:4]>
    assert fp.startswith("***-")
    parts = fp.split("-")
    assert len(parts) == 3
    assert parts[1] == "abcd"
    assert len(parts[2]) == 4
    assert len(fp) <= 16


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


async def test_create_credential_encrypts_and_round_trips(
    agents_svc: AgentService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    actor = await _make_user(users_svc, db_session, username="cred_owner_1")
    credential = await agents_svc.create_credential(
        actor,
        AgentCredentialCreate(
            provider=LLMProvider.OPENROUTER,
            display_name="primary",
            api_key=SecretStr("sk-or-1234567890"),
            default_model="anthropic/claude-3.5-sonnet",
            monthly_budget_usd=Decimal("25.00"),
        ),
    )
    assert credential.user_id == actor.id
    assert credential.encrypted_api_key != b"sk-or-1234567890"
    # Plaintext is never returned by service.create_credential.
    assert agents_svc.decrypt_api_key(credential) == "sk-or-1234567890"
    # Fingerprint exposes the last 4 chars but never the secret.
    assert "7890" in credential.key_fingerprint
    assert "sk-or" not in credential.key_fingerprint
    assert credential.monthly_budget_usd == Decimal("25.00")
    assert credential.spent_this_month == Decimal("0")


async def test_create_credential_duplicate_name_rejected(
    agents_svc: AgentService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    actor = await _make_user(users_svc, db_session, username="cred_owner_2")
    await agents_svc.create_credential(
        actor,
        AgentCredentialCreate(
            provider=LLMProvider.OPENROUTER,
            display_name="dup",
            api_key=SecretStr("sk-1"),
        ),
    )
    with pytest.raises(CredentialNameTaken):
        await agents_svc.create_credential(
            actor,
            AgentCredentialCreate(
                provider=LLMProvider.CLOUD_RU,
                display_name="dup",
                api_key=SecretStr("sk-2"),
            ),
        )


async def test_get_credential_non_owner_rejected(
    agents_svc: AgentService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    owner = await _make_user(users_svc, db_session, username="cred_owner_3")
    intruder = await _make_user(users_svc, db_session, username="intruder_3")
    credential = await agents_svc.create_credential(
        owner,
        AgentCredentialCreate(
            provider=LLMProvider.OPENROUTER,
            display_name="primary",
            api_key=SecretStr("sk-secret"),
        ),
    )
    with pytest.raises(NotCredentialOwner):
        await agents_svc.get_credential(intruder, credential.id)


async def test_admin_can_get_anyone_credential(
    agents_svc: AgentService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    owner = await _make_user(users_svc, db_session, username="cred_owner_3b")
    admin = await _make_user(
        users_svc, db_session, username="admin_3b", role=Role.ADMIN
    )
    credential = await agents_svc.create_credential(
        owner,
        AgentCredentialCreate(
            provider=LLMProvider.OPENROUTER,
            display_name="primary",
            api_key=SecretStr("sk-secret"),
        ),
    )
    # Admin can read; not raised.
    fetched = await agents_svc.get_credential(admin, credential.id)
    assert fetched.id == credential.id


async def test_update_credential_rotates_key(
    agents_svc: AgentService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    actor = await _make_user(users_svc, db_session, username="cred_owner_4")
    credential = await agents_svc.create_credential(
        actor,
        AgentCredentialCreate(
            provider=LLMProvider.OPENROUTER,
            display_name="primary",
            api_key=SecretStr("sk-old-abcd"),
        ),
    )
    old_fp = credential.key_fingerprint
    updated = await agents_svc.update_credential(
        actor,
        credential.id,
        AgentCredentialUpdate(api_key=SecretStr("sk-new-wxyz")),
    )
    assert updated.key_fingerprint != old_fp
    assert agents_svc.decrypt_api_key(updated) == "sk-new-wxyz"


async def test_delete_credential(
    agents_svc: AgentService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    actor = await _make_user(users_svc, db_session, username="cred_owner_5")
    credential = await agents_svc.create_credential(
        actor,
        AgentCredentialCreate(
            provider=LLMProvider.OPENROUTER,
            display_name="tmp",
            api_key=SecretStr("sk-x"),
        ),
    )
    await agents_svc.delete_credential(actor, credential.id)
    with pytest.raises(CredentialNotFound):
        await agents_svc.get_credential(actor, credential.id)


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------


async def test_create_agent_creates_bot_user_and_record(
    agents_svc: AgentService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    owner = await _make_user(users_svc, db_session, username="agent_owner_1")
    credential = await agents_svc.create_credential(
        owner,
        AgentCredentialCreate(
            provider=LLMProvider.OPENROUTER,
            display_name="primary",
            api_key=SecretStr("sk-xyz"),
        ),
    )
    agent, bot_user, returned_owner = await agents_svc.create_agent(
        owner,
        AgentCreate(
            username="claude_bot_1",
            display_name="Claude (research)",
            credential_id=credential.id,
            system_prompt="You are helpful.",
            allowed_actions=["draft", "rephrase"],
        ),
    )
    assert bot_user.role == Role.AGENT
    assert bot_user.email is None
    assert bot_user.password_hash is None
    assert bot_user.username == "claude_bot_1"
    assert agent.owner_user_id == owner.id
    assert agent.credential_id == credential.id
    assert "rephrase" in agent.allowed_actions
    assert returned_owner.id == owner.id


async def test_create_agent_with_other_users_credential_rejected(
    agents_svc: AgentService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    alice = await _make_user(users_svc, db_session, username="alice_ag2")
    bob = await _make_user(users_svc, db_session, username="bob_ag2")
    cred_a = await agents_svc.create_credential(
        alice,
        AgentCredentialCreate(
            provider=LLMProvider.OPENROUTER,
            display_name="alice_primary",
            api_key=SecretStr("sk-a"),
        ),
    )
    with pytest.raises(NotCredentialOwner):
        await agents_svc.create_agent(
            bob,
            AgentCreate(
                username="bobs_bot",
                credential_id=cred_a.id,
                allowed_actions=[],
            ),
        )


async def test_create_agent_duplicate_username_rejected(
    agents_svc: AgentService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    owner = await _make_user(users_svc, db_session, username="agent_owner_3")
    credential = await agents_svc.create_credential(
        owner,
        AgentCredentialCreate(
            provider=LLMProvider.OPENROUTER,
            display_name="p",
            api_key=SecretStr("sk-x"),
        ),
    )
    await agents_svc.create_agent(
        owner,
        AgentCreate(
            username="bot_3",
            credential_id=credential.id,
            allowed_actions=[],
        ),
    )
    with pytest.raises(UsernameTaken):
        await agents_svc.create_agent(
            owner,
            AgentCreate(
                username="bot_3",
                credential_id=credential.id,
                allowed_actions=[],
            ),
        )


async def test_delete_agent_soft_deactivates_user(
    agents_svc: AgentService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    owner = await _make_user(users_svc, db_session, username="agent_owner_4")
    credential = await agents_svc.create_credential(
        owner,
        AgentCredentialCreate(
            provider=LLMProvider.OPENROUTER,
            display_name="p",
            api_key=SecretStr("sk-x"),
        ),
    )
    agent, bot_user, _ = await agents_svc.create_agent(
        owner,
        AgentCreate(
            username="bot_4",
            credential_id=credential.id,
            allowed_actions=[],
        ),
    )
    await agents_svc.delete_agent(owner, agent.user_id)
    refreshed = await users_svc.get_by_id(bot_user.id)
    assert refreshed.is_active is False


async def test_delete_agent_by_non_owner_rejected(
    agents_svc: AgentService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    owner = await _make_user(users_svc, db_session, username="agent_owner_5")
    other = await _make_user(users_svc, db_session, username="other_5")
    credential = await agents_svc.create_credential(
        owner,
        AgentCredentialCreate(
            provider=LLMProvider.OPENROUTER,
            display_name="p",
            api_key=SecretStr("sk-x"),
        ),
    )
    agent, _, _ = await agents_svc.create_agent(
        owner,
        AgentCreate(
            username="bot_5",
            credential_id=credential.id,
            allowed_actions=[],
        ),
    )
    with pytest.raises(NotAgentOwner):
        await agents_svc.delete_agent(other, agent.user_id)


async def test_get_agent_not_found(
    agents_svc: AgentService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    actor = await _make_user(users_svc, db_session, username="agent_owner_6")
    with pytest.raises(AgentNotFound):
        await agents_svc.get_agent(actor, uuid.uuid4())


# ---------------------------------------------------------------------------
# Usage log
# ---------------------------------------------------------------------------


async def test_log_usage_updates_spent_this_month(
    agents_svc: AgentService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    owner = await _make_user(users_svc, db_session, username="usage_owner_1")
    credential = await agents_svc.create_credential(
        owner,
        AgentCredentialCreate(
            provider=LLMProvider.OPENROUTER,
            display_name="p",
            api_key=SecretStr("sk-x"),
        ),
    )
    await agents_svc.log_usage(
        credential_id=credential.id,
        model="claude-3.5-sonnet",
        input_tokens=120,
        output_tokens=80,
        cost=Decimal("0.012345"),
        status=LLMUsageStatus.SUCCESS,
        duration_ms=854,
    )
    await agents_svc.log_usage(
        credential_id=credential.id,
        model="claude-3.5-sonnet",
        input_tokens=10,
        output_tokens=20,
        cost=Decimal("0.001000"),
        status=LLMUsageStatus.SUCCESS,
    )
    refreshed = await agents_svc.get_credential(owner, credential.id)
    assert refreshed.spent_this_month == Decimal("0.013345")
    assert refreshed.last_used_at is not None


async def test_get_monthly_usage_aggregates(
    agents_svc: AgentService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    owner = await _make_user(users_svc, db_session, username="usage_owner_2")
    credential = await agents_svc.create_credential(
        owner,
        AgentCredentialCreate(
            provider=LLMProvider.OPENROUTER,
            display_name="p",
            api_key=SecretStr("sk-x"),
        ),
    )
    for _ in range(3):
        await agents_svc.log_usage(
            credential_id=credential.id,
            model="x",
            input_tokens=1,
            output_tokens=1,
            cost=Decimal("0.5"),
            status=LLMUsageStatus.SUCCESS,
        )
    info = await agents_svc.get_monthly_usage(credential.id)
    assert info["cost_usd"] == Decimal("1.5")


# ---------------------------------------------------------------------------
# Agent tokens (bot bearer tokens)
# ---------------------------------------------------------------------------


async def _make_agent_for_owner(
    agents_svc: AgentService,
    users_svc: UserService,
    db_session: AsyncSession,
    *,
    owner_name: str,
    bot_name: str,
) -> tuple[User, User, uuid.UUID]:
    """Build (owner, bot_user, agent_user_id) — common scaffolding."""
    owner = await _make_user(users_svc, db_session, username=owner_name)
    credential = await agents_svc.create_credential(
        owner,
        AgentCredentialCreate(
            provider=LLMProvider.OPENROUTER,
            display_name="primary",
            api_key=SecretStr("sk-x"),
        ),
    )
    agent, bot_user, _ = await agents_svc.create_agent(
        owner,
        AgentCreate(
            username=bot_name,
            credential_id=credential.id,
            allowed_actions=[],
        ),
    )
    return owner, bot_user, agent.user_id


async def test_create_agent_token_returns_raw_and_stores_hash(
    agents_svc: AgentService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    owner, _bot, agent_id = await _make_agent_for_owner(
        agents_svc,
        users_svc,
        db_session,
        owner_name="tok_owner_1",
        bot_name="tok_bot_1",
    )
    token, raw = await agents_svc.create_agent_token(
        owner,
        agent_id,
        name="main",
        scopes=["search", "article:read", "article:write"],
    )
    # Raw token is a non-trivial url-safe secret.
    assert isinstance(raw, str)
    assert len(raw) >= 40
    # Hash stored is *not* the raw token; matches our SHA-256 helper.
    import hashlib

    assert token.token_hash == hashlib.sha256(raw.encode()).hexdigest()
    assert token.token_hash != raw
    assert token.scopes == ["search", "article:read", "article:write"]
    assert token.agent_id == agent_id
    assert token.revoked_at is None


async def test_create_agent_token_rejects_non_owner(
    agents_svc: AgentService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    _owner, _bot, agent_id = await _make_agent_for_owner(
        agents_svc,
        users_svc,
        db_session,
        owner_name="tok_owner_2",
        bot_name="tok_bot_2",
    )
    intruder = await _make_user(users_svc, db_session, username="tok_intruder_2")
    with pytest.raises(NotAgentOwner):
        await agents_svc.create_agent_token(
            intruder, agent_id, name="evil", scopes=[]
        )


async def test_create_agent_token_admin_can_mint_for_any_agent(
    agents_svc: AgentService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    _owner, _bot, agent_id = await _make_agent_for_owner(
        agents_svc,
        users_svc,
        db_session,
        owner_name="tok_owner_2b",
        bot_name="tok_bot_2b",
    )
    admin = await _make_user(
        users_svc, db_session, username="tok_admin_2b", role=Role.ADMIN
    )
    token, raw = await agents_svc.create_agent_token(
        admin, agent_id, name="admin-mint", scopes=["search"]
    )
    assert raw  # non-empty
    assert token.agent_id == agent_id


async def test_authenticate_bot_happy_path_bumps_last_used(
    agents_svc: AgentService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    owner, _bot, agent_id = await _make_agent_for_owner(
        agents_svc,
        users_svc,
        db_session,
        owner_name="tok_owner_3",
        bot_name="tok_bot_3",
    )
    token, raw = await agents_svc.create_agent_token(
        owner, agent_id, name="main", scopes=["search"]
    )
    assert token.last_used_at is None

    found = await agents_svc.authenticate_bot(raw)
    assert found is not None
    assert found.user_id == agent_id

    # Token row was updated in-place.
    await db_session.refresh(token)
    assert token.last_used_at is not None


async def test_authenticate_bot_revoked_returns_none(
    agents_svc: AgentService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    owner, _bot, agent_id = await _make_agent_for_owner(
        agents_svc,
        users_svc,
        db_session,
        owner_name="tok_owner_4",
        bot_name="tok_bot_4",
    )
    token, raw = await agents_svc.create_agent_token(
        owner, agent_id, name="main", scopes=["search"]
    )
    await agents_svc.revoke_agent_token(owner, token.id)
    assert await agents_svc.authenticate_bot(raw) is None


async def test_authenticate_bot_unknown_token_returns_none(
    agents_svc: AgentService,
) -> None:
    assert await agents_svc.authenticate_bot("totally-bogus-token") is None
    # And empty string returns None too — defensive against a missing header.
    assert await agents_svc.authenticate_bot("") is None


async def test_revoke_agent_token_idempotent_and_owner_gated(
    agents_svc: AgentService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    owner, _bot, agent_id = await _make_agent_for_owner(
        agents_svc,
        users_svc,
        db_session,
        owner_name="tok_owner_5",
        bot_name="tok_bot_5",
    )
    intruder = await _make_user(users_svc, db_session, username="tok_intruder_5")
    token, _raw = await agents_svc.create_agent_token(
        owner, agent_id, name="m", scopes=[]
    )

    # Non-owner cannot revoke.
    with pytest.raises(NotAgentTokenOwner):
        await agents_svc.revoke_agent_token(intruder, token.id)

    # Owner revoke succeeds, second call is a no-op (idempotent).
    await agents_svc.revoke_agent_token(owner, token.id)
    await agents_svc.revoke_agent_token(owner, token.id)

    # Unknown token id raises.
    with pytest.raises(AgentTokenNotFound):
        await agents_svc.revoke_agent_token(owner, uuid.uuid4())


async def test_list_agent_tokens_owner_only_and_newest_first(
    agents_svc: AgentService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    owner, _bot, agent_id = await _make_agent_for_owner(
        agents_svc,
        users_svc,
        db_session,
        owner_name="tok_owner_6",
        bot_name="tok_bot_6",
    )
    intruder = await _make_user(users_svc, db_session, username="tok_intruder_6")
    t1, _ = await agents_svc.create_agent_token(
        owner, agent_id, name="first", scopes=["search"]
    )
    t2, _ = await agents_svc.create_agent_token(
        owner, agent_id, name="second", scopes=["article:read"]
    )
    tokens = await agents_svc.list_agent_tokens(owner, agent_id)
    ids = {t.id for t in tokens}
    assert {t1.id, t2.id} <= ids

    with pytest.raises(NotAgentOwner):
        await agents_svc.list_agent_tokens(intruder, agent_id)


async def test_get_token_scopes_returns_none_for_unknown_or_revoked(
    agents_svc: AgentService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    owner, _bot, agent_id = await _make_agent_for_owner(
        agents_svc,
        users_svc,
        db_session,
        owner_name="tok_owner_7",
        bot_name="tok_bot_7",
    )
    token, raw = await agents_svc.create_agent_token(
        owner, agent_id, name="m", scopes=["llm:assist"]
    )
    assert await agents_svc.get_token_scopes(raw) == ["llm:assist"]

    await agents_svc.revoke_agent_token(owner, token.id)
    assert await agents_svc.get_token_scopes(raw) is None
    assert await agents_svc.get_token_scopes("nope") is None


# ---------------------------------------------------------------------------
# MCP server smoke import (no network/uvicorn boot)
# ---------------------------------------------------------------------------


def test_mcp_server_module_imports() -> None:
    """Smoke: importing the MCP server registers all tools without errors."""
    import asyncio

    from app.mcp_server.server import build_asgi_app, mcp_app

    assert mcp_app.name == "neuroforum"
    asgi = build_asgi_app()
    assert asgi is not None

    tool_names = {t.name for t in asyncio.run(mcp_app.list_tools())}
    # Spot-check a representative subset.
    assert {"search", "read_article", "create_article", "post_comment", "llm_assist"} <= tool_names
