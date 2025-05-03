"""Enable pgcrypto extension

Revision ID: 033cc4d830a0
Revises: 2708ec431c24
Create Date: 2025-05-01 18:28:23.167656

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "033cc4d830a0"
down_revision: str | None = "2708ec431c24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")


def downgrade() -> None:
    """Downgrade schema."""
    # pgcrypto doesn't necessarily need a downgrade path,
    # but if you wanted one:
    # op.execute("DROP EXTENSION IF EXISTS pgcrypto;")
