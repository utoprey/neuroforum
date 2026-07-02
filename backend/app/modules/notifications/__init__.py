"""Notifications module: per-user inbox of typed events (mention, reply, …).

Service-layer hook from ``mentions`` / ``moderation`` writes rows here; the
client polls or subscribes for updates.
"""
