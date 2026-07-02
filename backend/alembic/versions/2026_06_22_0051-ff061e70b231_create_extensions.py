"""create_extensions

Revision ID: ff061e70b231
Revises:
Create Date: 2026-06-22 00:51:37.738393+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ff061e70b231"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the four extensions required by the schema.

    See docs/data-model.md > Postgres extensions.
    """
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "citext"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "pg_trgm"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "ltree"')


def downgrade() -> None:
    """Drop extensions in reverse order. May fail if dependent objects exist."""
    op.execute('DROP EXTENSION IF EXISTS "ltree"')
    op.execute('DROP EXTENSION IF EXISTS "pg_trgm"')
    op.execute('DROP EXTENSION IF EXISTS "citext"')
    op.execute('DROP EXTENSION IF EXISTS "uuid-ossp"')
