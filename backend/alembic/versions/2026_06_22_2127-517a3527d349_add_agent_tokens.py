"""add_agent_tokens

Revision ID: 517a3527d349
Revises: a85c146ecf1f
Create Date: 2026-06-22 21:27:37.944961+00:00

Adds the ``agent_tokens`` table used by the MCP server to authenticate
bot agents. Tokens are bearer secrets — only the SHA-256 hash is stored;
the raw token is returned to the caller once at creation time.

Autogenerate output was filtered down to *just* this change. All the
spurious GIN / GiST / pg_trgm index drops and ``use_alter`` FK additions
on ``llm_usage_log`` / ``article_ai_proposals`` / ``user_bans`` were
removed — those indexes/FKs are already in the production schema (created
by the initial migration) and must not be touched. Same pattern as the
previous ``add_last_seen_at_and_topic_kind`` migration.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "517a3527d349"
down_revision: str | None = "a85c146ecf1f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_tokens",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "scopes",
            postgresql.ARRAY(sa.String()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.user_id"],
            name=op.f("fk_agent_tokens_agent_id_agents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_tokens")),
        sa.UniqueConstraint(
            "token_hash", name=op.f("uq_agent_tokens_token_hash")
        ),
    )
    op.create_index(
        op.f("ix_agent_tokens_agent_id"),
        "agent_tokens",
        ["agent_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_agent_tokens_agent_id"), table_name="agent_tokens")
    op.drop_table("agent_tokens")
