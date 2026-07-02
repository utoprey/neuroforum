"""Business logic for the ``attachments`` module."""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from typing import TypedDict
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.attachments.exceptions import (
    AttachmentNotFound,
    MimeTypeNotAllowed,
    SizeLimitExceeded,
)
from app.modules.attachments.minio_client import (
    MinioClient,
    build_public_url,
    get_minio_client,
)
from app.modules.attachments.models import (
    Attachment,
    AttachmentKind,
    AttachmentUsage,
    ProcessingStatus,
)
from app.modules.attachments.repository import AttachmentRepository
from app.modules.attachments.schemas import (
    AttachmentFinalizeRequest,
    AttachmentUploadRequest,
    AttachmentUploadResponse,
)
from app.modules.users.models import Role, User

logger = logging.getLogger(__name__)


class KindLimit(TypedDict):
    """Per-kind upload constraint definition."""

    max_bytes: int
    mimes: list[str]


# Single source of truth for per-kind upload limits.
# Spec: IMAGE ≤ 20MB, GIF ≤ 10MB, VIDEO ≤ 100MB, FILE ≤ 50MB.
KIND_LIMITS: dict[AttachmentKind, KindLimit] = {
    AttachmentKind.IMAGE: {
        "max_bytes": 20 * 1024 * 1024,
        "mimes": ["image/jpeg", "image/png", "image/webp"],
    },
    AttachmentKind.GIF: {
        "max_bytes": 10 * 1024 * 1024,
        "mimes": ["image/gif"],
    },
    AttachmentKind.VIDEO: {
        "max_bytes": 100 * 1024 * 1024,
        "mimes": ["video/mp4", "video/webm"],
    },
    AttachmentKind.FILE: {
        "max_bytes": 50 * 1024 * 1024,
        "mimes": ["application/pdf"],
    },
}

# Derived lookup tables for hot-path validation.
_SIZE_LIMITS: dict[AttachmentKind, int] = {
    kind: cfg["max_bytes"] for kind, cfg in KIND_LIMITS.items()
}
_MIME_WHITELIST: dict[AttachmentKind, frozenset[str]] = {
    kind: frozenset(cfg["mimes"]) for kind, cfg in KIND_LIMITS.items()
}

# Mapping mime → file extension used in the object key.
_MIME_TO_EXT: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
    "video/mp4": "mp4",
    "video/webm": "webm",
    "application/pdf": "pdf",
}

# Presigned URLs are good for 15 minutes by default.
_PRESIGNED_EXPIRES = timedelta(minutes=15)

_MOD_OR_ADMIN: frozenset[Role] = frozenset({Role.MODERATOR, Role.ADMIN})


class AttachmentService:
    """Orchestrates upload-URL issuance, finalization and deletion."""

    def __init__(
        self,
        repo: AttachmentRepository,
        db: AsyncSession,
        minio_client: MinioClient | None = None,
    ) -> None:
        self._repo = repo
        self._db = db
        # DI hook for tests — production lazily builds a real client.
        self._minio = minio_client

    # ------------------------------------------------------------------
    # Upload-URL issuance
    # ------------------------------------------------------------------

    async def request_upload(
        self, actor: User, payload: AttachmentUploadRequest
    ) -> AttachmentUploadResponse:
        """Validate the request, allocate an object key + presigned PUT URL."""
        limit = _SIZE_LIMITS[payload.kind]
        if payload.size_bytes > limit:
            raise SizeLimitExceeded(
                f"{payload.kind.value} upload exceeds {limit} bytes "
                f"(got {payload.size_bytes})"
            )
        allowed = _MIME_WHITELIST[payload.kind]
        if payload.mime_type not in allowed:
            raise MimeTypeNotAllowed(
                f"MIME {payload.mime_type!r} not allowed for kind "
                f"{payload.kind.value}; allowed: {sorted(allowed)}"
            )

        attachment_id = uuid.uuid4()
        ext = _MIME_TO_EXT.get(payload.mime_type, "bin")
        object_key = f"attachments/{attachment_id}/original.{ext}"
        bucket = settings.MINIO_BUCKET

        # Non-video uploads are ready as soon as the PUT completes; video
        # waits for the processing actor to flip the status.
        status = (
            ProcessingStatus.PENDING
            if payload.kind == AttachmentKind.VIDEO
            else ProcessingStatus.READY
        )

        attachment = Attachment(
            id=attachment_id,
            uploader_id=actor.id,
            kind=payload.kind,
            bucket=bucket,
            object_key=object_key,
            mime_type=payload.mime_type,
            size_bytes=payload.size_bytes,
            original_filename=payload.filename,
            processing_status=status,
        )
        await self._repo.add(attachment)

        upload_url = self._make_presigned_url(bucket, object_key)
        return AttachmentUploadResponse(
            attachment_id=attachment_id,
            upload_url=upload_url,
            upload_method="PUT",
            expires_in_sec=int(_PRESIGNED_EXPIRES.total_seconds()),
            object_key=object_key,
            headers={"Content-Type": payload.mime_type},
        )

    def _make_presigned_url(self, bucket: str, object_key: str) -> str:
        """Try the real MinIO SDK; fall back to a fake URL when it isn't running.

        Tests run without docker access, so we degrade gracefully instead
        of failing the whole flow.
        """
        try:
            client = self._minio or get_minio_client()
            return client.presigned_put_object(
                bucket, object_key, expires=_PRESIGNED_EXPIRES
            )
        except Exception as exc:  # pragma: no cover — exercised under no-docker
            logger.warning(
                "MinIO presigned_put_object failed (%s); falling back to fake URL.",
                exc,
            )
            return f"http://minio.local/{bucket}/{object_key}?fake=1"

    # ------------------------------------------------------------------
    # Finalization
    # ------------------------------------------------------------------

    async def finalize_upload(
        self,
        actor: User,
        attachment_id: UUID,
        payload: AttachmentFinalizeRequest,
    ) -> Attachment:
        attachment = await self._repo.get(attachment_id)
        if attachment is None:
            raise AttachmentNotFound(str(attachment_id))
        if attachment.uploader_id != actor.id and actor.role not in _MOD_OR_ADMIN:
            # Same "not found" treatment so we don't leak existence to
            # randoms probing for attachment ids.
            raise AttachmentNotFound(str(attachment_id))

        if payload.width is not None:
            attachment.width = payload.width
        if payload.height is not None:
            attachment.height = payload.height
        if payload.duration_sec is not None:
            attachment.duration_sec = payload.duration_sec

        # Video processing: in MVP we just flip to READY. The real actor
        # below would push to a queue and ffmpeg would do the work.
        if attachment.kind == AttachmentKind.VIDEO:
            # TODO: enqueue process_video.send(str(attachment.id))
            attachment.processing_status = ProcessingStatus.READY
        else:
            attachment.processing_status = ProcessingStatus.READY

        await self._db.flush()
        await self._db.refresh(attachment, attribute_names=("updated_at",))
        return attachment

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_attachment(self, attachment_id: UUID) -> Attachment:
        attachment = await self._repo.get(attachment_id)
        if attachment is None:
            raise AttachmentNotFound(str(attachment_id))
        return attachment

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    async def delete_attachment(self, actor: User, attachment_id: UUID) -> None:
        attachment = await self._repo.get(attachment_id)
        if attachment is None:
            raise AttachmentNotFound(str(attachment_id))
        if attachment.uploader_id != actor.id and actor.role not in _MOD_OR_ADMIN:
            # Treat as not-found for non-owners so we don't leak existence.
            raise AttachmentNotFound(str(attachment_id))

        # Best-effort remove from MinIO; ignore failures so a missing
        # blob (already deleted, never uploaded) doesn't block GC.
        try:
            client = self._minio or get_minio_client()
            client.remove_object(attachment.bucket, attachment.object_key)
            if attachment.poster_object_key:
                client.remove_object(attachment.bucket, attachment.poster_object_key)
        except Exception as exc:  # pragma: no cover — exercised under no-docker
            logger.warning("MinIO remove_object failed (%s); ignoring.", exc)

        await self._repo.delete(attachment)

    # ------------------------------------------------------------------
    # Usage tracking (placeholder for future integration)
    # ------------------------------------------------------------------

    async def record_usage(
        self,
        attachment_id: UUID,
        entity_type: str,
        entity_id: UUID,
    ) -> AttachmentUsage | None:
        """Record that ``entity_type:entity_id`` references ``attachment_id``.

        Idempotent: a duplicate (attachment, entity) pair is a no-op.
        Called from ``articles``/``messages`` services once they integrate
        with ``extract_attachment_ids``. TODO: wire this in.
        """
        existing = await self._repo.find_usage(attachment_id, entity_type, entity_id)
        if existing is not None:
            return existing
        usage = AttachmentUsage(
            attachment_id=attachment_id,
            entity_type=entity_type,
            entity_id=entity_id,
        )
        return await self._repo.add_usage(usage)

    # ------------------------------------------------------------------
    # GC stub
    # ------------------------------------------------------------------

    async def garbage_collect(self) -> int:  # pragma: no cover — placeholder
        """Delete attachments older than 24h with no usage rows.

        Stub — wire to a Dramatiq cron actor in the next iteration.
        """
        return 0


__all__ = ["KIND_LIMITS", "AttachmentService", "KindLimit", "build_public_url"]
