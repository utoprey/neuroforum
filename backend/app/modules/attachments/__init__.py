"""Attachments module: MinIO-backed uploads with presigned URLs.

Tracks two tables: ``attachments`` (one row per uploaded blob) and
``attachment_usages`` (which content entity references the attachment —
used by the GC actor to clean orphaned uploads).

Video uploads are processed asynchronously: the route marks the row
``pending``, the client gets a presigned PUT URL, and a Dramatiq worker
(``app.workers.attachments.process_video``) flips it to ``ready`` once
ffmpeg conversion + poster generation finishes.
"""
