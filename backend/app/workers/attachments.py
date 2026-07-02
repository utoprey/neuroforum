"""Dramatiq actors for the ``attachments`` module.

These run outside the request loop on a RabbitMQ-backed worker. In tests
nothing imports this module, so dramatiq's default stub broker is fine.
"""

from __future__ import annotations

import logging

import dramatiq

logger = logging.getLogger(__name__)


@dramatiq.actor(queue_name="attachments", max_retries=3)
def process_video(attachment_id: str) -> None:
    """Convert uploaded video to MP4/H.264 + generate a poster image.

    MVP stub: this just logs. Real implementation:

    1. Pull original blob from MinIO.
    2. Run ``ffmpeg -i original.<ext> -c:v libx264 -preset slow output.mp4``
       and ``ffmpeg -ss 00:00:01 -vframes 1 poster.jpg``.
    3. Upload both back to MinIO.
    4. Update ``Attachment.poster_object_key`` and flip
       ``processing_status`` to READY (or FAILED with ``error_message``).
    """
    logger.info("process_video stub called for attachment_id=%s", attachment_id)
    # TODO: implement


__all__ = ["process_video"]
