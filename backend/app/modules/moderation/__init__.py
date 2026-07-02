"""Moderation module: append-only ``audit_log`` + hide/unhide/role assignment.

Every mod / admin action is recorded as a row in :class:`AuditLog` with the
actor's IP and user agent (when available) so the audit trail is permanent
and tamper-evident.
"""
