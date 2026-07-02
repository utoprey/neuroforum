"""Lazily-constructed MinIO client wrapper.

Exposes the bare minimum needed by the attachments service: a presigned
PUT URL generator and a delete helper. We intentionally don't expose the
full ``minio.Minio`` API so the service layer never reaches around us.

In tests MinIO isn't running — ``presigned_put_object`` will raise.
``AttachmentService`` handles that case and falls back to a fake URL so
unit tests can exercise the full path without depending on docker.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Protocol

from minio import Minio

from app.core.config import settings


class MinioClient(Protocol):
    """Subset of the Minio API the service depends on."""

    def presigned_put_object(
        self,
        bucket_name: str,
        object_name: str,
        expires: timedelta = ...,
    ) -> str:
        ...

    def remove_object(self, bucket_name: str, object_name: str) -> None:
        ...


def get_minio_client() -> Minio:
    """Build a fresh ``Minio`` client from ``settings``.

    No caching — the SDK is cheap to instantiate and we want each request
    to pick up live settings changes during tests.
    """
    return Minio(
        settings.MINIO_ENDPOINT,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=settings.MINIO_SECURE,
    )


def build_public_url(bucket: str, object_key: str) -> str:
    """Compose the public-facing URL used by ``AttachmentRead.url``."""
    base = settings.MINIO_PUBLIC_BASE_URL.rstrip("/")
    return f"{base}/{bucket}/{object_key}"


__all__ = ["MinioClient", "build_public_url", "get_minio_client"]
