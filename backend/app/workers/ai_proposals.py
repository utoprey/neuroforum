"""Dramatiq actor for the ``ai_proposals`` module.

Schedules an hourly sweep that flips overdue pending proposals to
``expired``. The actual scheduler is wired up in deployment infra (a
``dramatiq-periodiq`` or external cron pinging the actor) — this file just
exposes the actor so the broker registers it on import.
"""

from __future__ import annotations

import logging

import dramatiq

logger = logging.getLogger(__name__)


@dramatiq.actor(queue_name="ai_proposals", max_retries=3)
def cleanup_expired_proposals() -> None:
    """Mark pending AI proposals past their ``expires_at`` as expired.

    MVP stub: schedule wiring is deferred. To run, instantiate an
    ``AIProposalService`` against a fresh async session and call
    ``await svc.expire_pending()``. We keep this function thin so the
    queue+actor registration happens on import without forcing a DB
    connection at module load time.
    """
    logger.info("cleanup_expired_proposals stub invoked")
    # TODO: open AsyncSession, call AIProposalService(...).expire_pending().


__all__ = ["cleanup_expired_proposals"]
