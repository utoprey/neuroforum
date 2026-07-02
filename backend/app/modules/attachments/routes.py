"""HTTP routes for the ``attachments`` module."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.modules.attachments.deps import get_attachment_service
from app.modules.attachments.exceptions import (
    AttachmentNotFound,
    MimeTypeNotAllowed,
    SizeLimitExceeded,
)
from app.modules.attachments.minio_client import build_public_url
from app.modules.attachments.models import Attachment
from app.modules.attachments.schemas import (
    AttachmentFinalizeRequest,
    AttachmentKindLimits,
    AttachmentLimits,
    AttachmentRead,
    AttachmentUploadRequest,
    AttachmentUploadResponse,
)
from app.modules.attachments.service import KIND_LIMITS, AttachmentService
from app.modules.users.deps import get_current_user
from app.modules.users.models import User

router = APIRouter(prefix="/attachments", tags=["attachments"])


def _read(attachment: Attachment) -> AttachmentRead:
    return AttachmentRead(
        id=attachment.id,
        kind=attachment.kind,
        mime_type=attachment.mime_type,
        size_bytes=attachment.size_bytes,
        width=attachment.width,
        height=attachment.height,
        duration_sec=attachment.duration_sec,
        processing_status=attachment.processing_status,
        url=build_public_url(attachment.bucket, attachment.object_key),
        poster_url=(
            build_public_url(attachment.bucket, attachment.poster_object_key)
            if attachment.poster_object_key
            else None
        ),
        created_at=attachment.created_at,
    )


@router.get(
    "/limits",
    response_model=AttachmentLimits,
    summary="Per-kind upload limits (open endpoint — no auth required)",
)
async def get_limits() -> AttachmentLimits:
    """Return the size + MIME whitelist for every attachment kind.

    Open endpoint: clients need to know the limits before they even pick a
    file, so this must work pre-login. Keep it free of dependencies.
    """
    kinds = [
        AttachmentKindLimits(
            kind=kind,
            max_bytes=cfg["max_bytes"],
            max_mb=round(cfg["max_bytes"] / (1024 * 1024), 2),
            allowed_mime_types=list(cfg["mimes"]),
        )
        for kind, cfg in KIND_LIMITS.items()
    ]
    return AttachmentLimits(kinds=kinds)


@router.post(
    "/upload-url",
    response_model=AttachmentUploadResponse,
    summary="Allocate an attachment row + return a presigned PUT URL",
)
async def request_upload(
    payload: AttachmentUploadRequest,
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[AttachmentService, Depends(get_attachment_service)],
) -> AttachmentUploadResponse:
    try:
        return await svc.request_upload(actor, payload)
    except SizeLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)
        ) from exc
    except MimeTypeNotAllowed as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)
        ) from exc


@router.post(
    "/{attachment_id}/finalize",
    response_model=AttachmentRead,
    summary="Confirm a successful PUT and (for video) kick off processing",
)
async def finalize_upload(
    attachment_id: UUID,
    payload: AttachmentFinalizeRequest,
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[AttachmentService, Depends(get_attachment_service)],
) -> AttachmentRead:
    try:
        attachment = await svc.finalize_upload(actor, attachment_id, payload)
    except AttachmentNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found"
        ) from exc
    return _read(attachment)


@router.get(
    "/{attachment_id}",
    response_model=AttachmentRead,
    summary="Fetch attachment metadata + public URL",
)
async def get_attachment(
    attachment_id: UUID,
    svc: Annotated[AttachmentService, Depends(get_attachment_service)],
) -> AttachmentRead:
    try:
        attachment = await svc.get_attachment(attachment_id)
    except AttachmentNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found"
        ) from exc
    return _read(attachment)


@router.delete(
    "/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete an attachment (uploader or moderator/admin)",
)
async def delete_attachment(
    attachment_id: UUID,
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[AttachmentService, Depends(get_attachment_service)],
) -> Response:
    try:
        await svc.delete_attachment(actor, attachment_id)
    except AttachmentNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found"
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
