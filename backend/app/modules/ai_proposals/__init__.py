"""AI proposals module.

Article-scoped AI assist suggestions. Each pending proposal lives for 3 days
(TTL via ``expires_at``); a Dramatiq cron actor (``workers.ai_proposals``)
flips stale ones to ``expired``.
"""
