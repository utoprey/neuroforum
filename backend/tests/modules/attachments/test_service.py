"""Service-layer tests for the ``attachments`` module."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.attachments.exceptions import (
    AttachmentNotFound,
    MimeTypeNotAllowed,
    SizeLimitExceeded,
)
from app.modules.attachments.models import AttachmentKind, ProcessingStatus
from app.modules.attachments.repository import AttachmentRepository
from app.modules.attachments.schemas import (
    AttachmentFinalizeRequest,
    AttachmentUploadRequest,
)
from app.modules.attachments.service import AttachmentService
from app.modules.users.models import Role, User
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import UserCreate
from app.modules.users.service import UserService


class _FakeMinio:
    """Stand-in for the ``minio.Minio`` client used in tests.

    Records remove_object calls and returns deterministic fake URLs from
    presigned_put_object so we can assert on the routing.
    """

    def __init__(self) -> None:
        self.removed: list[tuple[str, str]] = []

    def presigned_put_object(
        self, bucket_name: str, object_name: str, expires: timedelta = timedelta(minutes=15)
    ) -> str:
        return f"https://fake-minio/{bucket_name}/{object_name}?presigned=1"

    def remove_object(self, bucket_name: str, object_name: str) -> None:
        self.removed.append((bucket_name, object_name))


@pytest.fixture
def users_svc(db_session: AsyncSession) -> UserService:
    return UserService(UserRepository(db_session), db_session)


@pytest.fixture
def fake_minio() -> _FakeMinio:
    return _FakeMinio()


@pytest.fixture
def attachments_svc(
    db_session: AsyncSession, fake_minio: _FakeMinio
) -> AttachmentService:
    return AttachmentService(
        AttachmentRepository(db_session), db_session, minio_client=fake_minio
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
            email=f"{username}@x.io",
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
# request_upload — happy path + validation
# ---------------------------------------------------------------------------


async def test_request_upload_image_returns_presigned_url(
    attachments_svc: AttachmentService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    user = await _make_user(users_svc, db_session, username="uploader_img")
    resp = await attachments_svc.request_upload(
        user,
        AttachmentUploadRequest(
            filename="photo.png",
            mime_type="image/png",
            size_bytes=1024,
            kind=AttachmentKind.IMAGE,
        ),
    )
    assert resp.upload_method == "PUT"
    assert resp.upload_url.startswith("https://fake-minio/")
    assert resp.object_key.startswith("attachments/")
    assert resp.object_key.endswith(".png")
    # IMAGE → READY immediately.
    attachment = await attachments_svc.get_attachment(resp.attachment_id)
    assert attachment.processing_status == ProcessingStatus.READY
    assert attachment.kind == AttachmentKind.IMAGE
    assert attachment.uploader_id == user.id


async def test_request_upload_video_is_pending(
    attachments_svc: AttachmentService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    user = await _make_user(users_svc, db_session, username="uploader_vid")
    resp = await attachments_svc.request_upload(
        user,
        AttachmentUploadRequest(
            filename="clip.mp4",
            mime_type="video/mp4",
            size_bytes=2_000_000,
            kind=AttachmentKind.VIDEO,
        ),
    )
    attachment = await attachments_svc.get_attachment(resp.attachment_id)
    assert attachment.processing_status == ProcessingStatus.PENDING


async def test_request_upload_size_limit(
    attachments_svc: AttachmentService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    user = await _make_user(users_svc, db_session, username="uploader_big")
    with pytest.raises(SizeLimitExceeded):
        await attachments_svc.request_upload(
            user,
            AttachmentUploadRequest(
                filename="big.png",
                mime_type="image/png",
                size_bytes=21 * 1024 * 1024,
                kind=AttachmentKind.IMAGE,
            ),
        )


async def test_request_upload_mime_whitelist(
    attachments_svc: AttachmentService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    user = await _make_user(users_svc, db_session, username="uploader_bad_mime")
    with pytest.raises(MimeTypeNotAllowed):
        await attachments_svc.request_upload(
            user,
            AttachmentUploadRequest(
                filename="hack.exe",
                mime_type="application/x-msdownload",
                size_bytes=1024,
                kind=AttachmentKind.FILE,
            ),
        )


# ---------------------------------------------------------------------------
# finalize_upload
# ---------------------------------------------------------------------------


async def test_finalize_video_sets_ready(
    attachments_svc: AttachmentService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    user = await _make_user(users_svc, db_session, username="finalizer_vid")
    resp = await attachments_svc.request_upload(
        user,
        AttachmentUploadRequest(
            filename="clip.mp4",
            mime_type="video/mp4",
            size_bytes=2_000_000,
            kind=AttachmentKind.VIDEO,
        ),
    )
    out = await attachments_svc.finalize_upload(
        user,
        resp.attachment_id,
        AttachmentFinalizeRequest(width=1280, height=720, duration_sec=42),
    )
    assert out.processing_status == ProcessingStatus.READY
    assert out.width == 1280
    assert out.height == 720
    assert out.duration_sec == 42


async def test_finalize_non_owner_forbidden(
    attachments_svc: AttachmentService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    owner = await _make_user(users_svc, db_session, username="owner_fin")
    stranger = await _make_user(users_svc, db_session, username="stranger_fin")
    resp = await attachments_svc.request_upload(
        owner,
        AttachmentUploadRequest(
            filename="x.png",
            mime_type="image/png",
            size_bytes=1024,
            kind=AttachmentKind.IMAGE,
        ),
    )
    with pytest.raises(AttachmentNotFound):
        await attachments_svc.finalize_upload(
            stranger,
            resp.attachment_id,
            AttachmentFinalizeRequest(width=10, height=10),
        )


# ---------------------------------------------------------------------------
# delete_attachment
# ---------------------------------------------------------------------------


async def test_delete_by_uploader(
    attachments_svc: AttachmentService,
    users_svc: UserService,
    db_session: AsyncSession,
    fake_minio: _FakeMinio,
) -> None:
    user = await _make_user(users_svc, db_session, username="deleter_owner")
    resp = await attachments_svc.request_upload(
        user,
        AttachmentUploadRequest(
            filename="x.png",
            mime_type="image/png",
            size_bytes=512,
            kind=AttachmentKind.IMAGE,
        ),
    )
    await attachments_svc.delete_attachment(user, resp.attachment_id)
    with pytest.raises(AttachmentNotFound):
        await attachments_svc.get_attachment(resp.attachment_id)
    # MinIO remove was called for the original object.
    assert any(key.endswith(".png") for _b, key in fake_minio.removed)


async def test_delete_by_admin(
    attachments_svc: AttachmentService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    owner = await _make_user(users_svc, db_session, username="del_owner")
    admin = await _make_user(
        users_svc, db_session, username="del_admin", role=Role.ADMIN
    )
    resp = await attachments_svc.request_upload(
        owner,
        AttachmentUploadRequest(
            filename="x.png",
            mime_type="image/png",
            size_bytes=512,
            kind=AttachmentKind.IMAGE,
        ),
    )
    await attachments_svc.delete_attachment(admin, resp.attachment_id)
    with pytest.raises(AttachmentNotFound):
        await attachments_svc.get_attachment(resp.attachment_id)


async def test_delete_by_stranger_forbidden(
    attachments_svc: AttachmentService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    owner = await _make_user(users_svc, db_session, username="del_owner2")
    stranger = await _make_user(users_svc, db_session, username="del_stranger")
    resp = await attachments_svc.request_upload(
        owner,
        AttachmentUploadRequest(
            filename="x.png",
            mime_type="image/png",
            size_bytes=512,
            kind=AttachmentKind.IMAGE,
        ),
    )
    with pytest.raises(AttachmentNotFound):
        await attachments_svc.delete_attachment(stranger, resp.attachment_id)
    # Still there.
    fetched = await attachments_svc.get_attachment(resp.attachment_id)
    assert fetched.id == resp.attachment_id


# ---------------------------------------------------------------------------
# record_usage
# ---------------------------------------------------------------------------


async def test_record_usage_idempotent(
    attachments_svc: AttachmentService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    user = await _make_user(users_svc, db_session, username="usage_owner")
    resp = await attachments_svc.request_upload(
        user,
        AttachmentUploadRequest(
            filename="x.png",
            mime_type="image/png",
            size_bytes=512,
            kind=AttachmentKind.IMAGE,
        ),
    )
    entity_id = uuid.uuid4()
    u1 = await attachments_svc.record_usage(
        resp.attachment_id, "article", entity_id
    )
    u2 = await attachments_svc.record_usage(
        resp.attachment_id, "article", entity_id
    )
    assert u1 is not None and u2 is not None
    assert u1.id == u2.id
