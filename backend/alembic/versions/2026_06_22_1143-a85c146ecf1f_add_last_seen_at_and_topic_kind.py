"""add_last_seen_at_and_topic_kind

Revision ID: a85c146ecf1f
Revises: 6f7d1e0cabfe
Create Date: 2026-06-22 11:43:08.723544+00:00

Manual additions on top of the autogenerate output:

* ``users.last_seen_at`` — nullable TIMESTAMPTZ, bumped by ``PresenceMiddleware``.
* ``topic_kind`` Postgres enum + ``topics.kind`` column with default ``'discussion'``.

All the spurious GIN / GiST / pg_trgm index "drops" autogenerate emits
(because it can't see those indexes' ``USING gin`` / ``USING gist``
clauses) have been removed — those indexes still exist in production and
must not be touched.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a85c146ecf1f"
down_revision: str | None = "6f7d1e0cabfe"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TOPIC_KIND_VALUES = ("news", "discussion", "help", "flood")


def upgrade() -> None:
    # ``users.last_seen_at`` — presence tracking.
    op.add_column(
        "users",
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ``topic_kind`` enum + ``topics.kind`` column.
    op.execute(
        "CREATE TYPE topic_kind AS ENUM "
        "('news', 'discussion', 'help', 'flood')"
    )
    op.add_column(
        "topics",
        sa.Column(
            "kind",
            sa.Enum(*TOPIC_KIND_VALUES, name="topic_kind", create_type=False),
            server_default="discussion",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("topics", "kind")
    op.execute("DROP TYPE topic_kind")
    op.drop_column("users", "last_seen_at")
