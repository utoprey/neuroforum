"""Service-layer tests for the ``dm`` module."""

from __future__ import annotations

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.content.schemas import DocSchema
from app.modules.dm.exceptions import (
    CannotDmYourself,
    DirectMessageNotFound,
    NotEditable,
    NotParticipant,
)
from app.modules.dm.models import (
    ConversationKind,
    DirectMessageStatus,
    make_dm_key,
)
from app.modules.dm.repository import DMRepository
from app.modules.dm.schemas import (
    DirectMessageCreate,
    DirectMessageUpdate,
)
from app.modules.dm.service import DMService
from app.modules.users.models import User
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
def dm_svc(db_session: AsyncSession) -> DMService:
    return DMService(
        DMRepository(db_session), UserRepository(db_session), db_session
    )


async def _make_user(
    users_svc: UserService, *, username: str
) -> User:
    return await users_svc.create_user(
        UserCreate(
            username=username,
            email=f"{username}@dm.io",
            password=SecretStr("hunter22!"),
        )
    )


def _doc(text_value: str = "Hi") -> dict[str, object]:
    return {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text_value}],
            }
        ],
    }


# ---------------------------------------------------------------------------
# start_dm
# ---------------------------------------------------------------------------


async def test_start_dm_creates_conversation_with_two_participants(
    dm_svc: DMService, users_svc: UserService
) -> None:
    alice = await _make_user(users_svc, username="alice_dm1")
    bob = await _make_user(users_svc, username="bob_dm1")
    conversation = await dm_svc.start_dm(alice, bob.id)
    assert conversation.kind == ConversationKind.DM
    assert conversation.dm_key == make_dm_key(alice.id, bob.id)

    repo = dm_svc._repo
    participants = await repo.list_participants(conversation.id)
    assert len(participants) == 2
    assert {p[1].username for p in participants} == {"alice_dm1", "bob_dm1"}


async def test_start_dm_is_idempotent_for_same_pair(
    dm_svc: DMService, users_svc: UserService
) -> None:
    alice = await _make_user(users_svc, username="alice_dm2")
    bob = await _make_user(users_svc, username="bob_dm2")
    first = await dm_svc.start_dm(alice, bob.id)
    # second call from either side returns the same conversation
    second = await dm_svc.start_dm(bob, alice.id)
    assert first.id == second.id


async def test_cannot_dm_yourself(
    dm_svc: DMService, users_svc: UserService
) -> None:
    alice = await _make_user(users_svc, username="alice_dm3")
    with pytest.raises(CannotDmYourself):
        await dm_svc.start_dm(alice, alice.id)


# ---------------------------------------------------------------------------
# Sending messages
# ---------------------------------------------------------------------------


async def test_send_message_as_participant_succeeds(
    dm_svc: DMService, users_svc: UserService
) -> None:
    alice = await _make_user(users_svc, username="alice_dm4")
    bob = await _make_user(users_svc, username="bob_dm4")
    conversation = await dm_svc.start_dm(alice, bob.id)
    message, author = await dm_svc.send_message(
        alice,
        conversation.id,
        DirectMessageCreate(content=DocSchema.model_validate(_doc("Hello Bob"))),
    )
    assert message.author_id == alice.id
    assert message.content_text == "Hello Bob"
    assert message.status == DirectMessageStatus.VISIBLE
    assert author.id == alice.id


async def test_send_message_as_non_participant_rejected(
    dm_svc: DMService, users_svc: UserService
) -> None:
    alice = await _make_user(users_svc, username="alice_dm5")
    bob = await _make_user(users_svc, username="bob_dm5")
    eve = await _make_user(users_svc, username="eve_dm5")
    conversation = await dm_svc.start_dm(alice, bob.id)
    with pytest.raises(NotParticipant):
        await dm_svc.send_message(
            eve,
            conversation.id,
            DirectMessageCreate(content=DocSchema.model_validate(_doc("snoop"))),
        )


# ---------------------------------------------------------------------------
# Listing messages
# ---------------------------------------------------------------------------


async def test_list_messages_requires_participant(
    dm_svc: DMService, users_svc: UserService
) -> None:
    alice = await _make_user(users_svc, username="alice_dm6")
    bob = await _make_user(users_svc, username="bob_dm6")
    eve = await _make_user(users_svc, username="eve_dm6")
    conversation = await dm_svc.start_dm(alice, bob.id)
    await dm_svc.send_message(
        alice,
        conversation.id,
        DirectMessageCreate(content=DocSchema.model_validate(_doc("hey"))),
    )
    with pytest.raises(NotParticipant):
        await dm_svc.list_messages(eve, conversation.id)

    rows = await dm_svc.list_messages(alice, conversation.id)
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# mark_read + unread_count
# ---------------------------------------------------------------------------


async def test_mark_read_updates_last_read_at_and_zeroes_unread(
    dm_svc: DMService, users_svc: UserService
) -> None:
    alice = await _make_user(users_svc, username="alice_dm7")
    bob = await _make_user(users_svc, username="bob_dm7")
    conversation = await dm_svc.start_dm(alice, bob.id)

    # Bob sends two messages; from Alice's perspective they are unread.
    await dm_svc.send_message(
        bob,
        conversation.id,
        DirectMessageCreate(content=DocSchema.model_validate(_doc("m1"))),
    )
    await dm_svc.send_message(
        bob,
        conversation.id,
        DirectMessageCreate(content=DocSchema.model_validate(_doc("m2"))),
    )

    triples = await dm_svc.list_my_conversations(alice)
    assert len(triples) == 1
    _, _, unread = triples[0]
    assert unread == 2

    await dm_svc.mark_read(alice, conversation.id)
    triples = await dm_svc.list_my_conversations(alice)
    _, _, unread_after = triples[0]
    assert unread_after == 0


# ---------------------------------------------------------------------------
# Edit + soft delete
# ---------------------------------------------------------------------------


async def test_author_can_edit_message(
    dm_svc: DMService, users_svc: UserService
) -> None:
    alice = await _make_user(users_svc, username="alice_dm8")
    bob = await _make_user(users_svc, username="bob_dm8")
    conversation = await dm_svc.start_dm(alice, bob.id)
    message, _ = await dm_svc.send_message(
        alice,
        conversation.id,
        DirectMessageCreate(content=DocSchema.model_validate(_doc("v0"))),
    )
    edited, _ = await dm_svc.edit_message(
        alice,
        message.id,
        DirectMessageUpdate(content=DocSchema.model_validate(_doc("v1"))),
    )
    assert edited.status == DirectMessageStatus.EDITED
    assert edited.content_text == "v1"


async def test_non_author_cannot_edit_or_delete(
    dm_svc: DMService, users_svc: UserService
) -> None:
    alice = await _make_user(users_svc, username="alice_dm9")
    bob = await _make_user(users_svc, username="bob_dm9")
    conversation = await dm_svc.start_dm(alice, bob.id)
    message, _ = await dm_svc.send_message(
        alice,
        conversation.id,
        DirectMessageCreate(content=DocSchema.model_validate(_doc("alice's"))),
    )
    with pytest.raises(NotEditable):
        await dm_svc.edit_message(
            bob,
            message.id,
            DirectMessageUpdate(content=DocSchema.model_validate(_doc("nope"))),
        )
    with pytest.raises(NotEditable):
        await dm_svc.delete_message(bob, message.id)


async def test_soft_delete_clears_content_and_sets_placeholder(
    dm_svc: DMService, users_svc: UserService
) -> None:
    alice = await _make_user(users_svc, username="alice_dm10")
    bob = await _make_user(users_svc, username="bob_dm10")
    conversation = await dm_svc.start_dm(alice, bob.id)
    message, _ = await dm_svc.send_message(
        alice,
        conversation.id,
        DirectMessageCreate(content=DocSchema.model_validate(_doc("oops"))),
    )
    deleted, _ = await dm_svc.delete_message(alice, message.id)
    assert deleted.status == DirectMessageStatus.DELETED_BY_AUTHOR
    assert deleted.content == {"type": "doc", "content": []}
    assert deleted.content_text == ""
    assert DMService.placeholder_for(deleted) == "Сообщение удалено"
    assert DMService.is_redacted(deleted) is True


async def test_edit_after_delete_rejected(
    dm_svc: DMService, users_svc: UserService
) -> None:
    alice = await _make_user(users_svc, username="alice_dm11")
    bob = await _make_user(users_svc, username="bob_dm11")
    conversation = await dm_svc.start_dm(alice, bob.id)
    message, _ = await dm_svc.send_message(
        alice,
        conversation.id,
        DirectMessageCreate(content=DocSchema.model_validate(_doc("hi"))),
    )
    await dm_svc.delete_message(alice, message.id)
    with pytest.raises(NotEditable):
        await dm_svc.edit_message(
            alice,
            message.id,
            DirectMessageUpdate(content=DocSchema.model_validate(_doc("v2"))),
        )


async def test_edit_nonexistent_message_raises(
    dm_svc: DMService, users_svc: UserService
) -> None:
    import uuid

    alice = await _make_user(users_svc, username="alice_dm12")
    with pytest.raises(DirectMessageNotFound):
        await dm_svc.edit_message(
            alice,
            uuid.uuid4(),
            DirectMessageUpdate(content=DocSchema.model_validate(_doc("v"))),
        )
