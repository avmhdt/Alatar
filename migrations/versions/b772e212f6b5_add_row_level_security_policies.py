"""Add row level security policies

Revision ID: b772e212f6b5
Revises: 64f98764f76c
Create Date: 2025-05-01 18:31:25.011014

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b772e212f6b5"
down_revision: str | None = "64f98764f76c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# List of tables requiring RLS based on user_id
RLS_TABLES = [
    "linked_accounts",
    "analysis_requests",
    "agent_tasks",
    "cached_shopify_data",
    "proposed_actions",
]

# Policy will check if the table's user_id matches the session variable
# We use `current_setting('app.current_user_id', true)` where 'true' allows the setting to be missing without error
POLICY_SQL = "user_id = current_setting('app.current_user_id', true)::uuid"


def upgrade() -> None:
    # Ensure the setting exists for superusers initially (or handle role permissions)
    # op.execute("ALTER ROLE <your_app_user> SET app.current_user_id = NULL;")

    for table in RLS_TABLES:
        # Enable RLS
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        # Create the policy
        # USING clause applies for SELECT, UPDATE, DELETE
        # WITH CHECK clause applies for INSERT, UPDATE
        op.execute(
            f"""CREATE POLICY user_isolation_policy ON {table}
            FOR ALL
            USING ({POLICY_SQL})
            WITH CHECK ({POLICY_SQL});
            """
        )
        # Ensure table owner (app user) bypasses RLS by default if needed, or rely on policy
        # op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;") # Use FORCE if even owner should be restricted by default


def downgrade() -> None:
    for table in RLS_TABLES:
        op.execute(f"DROP POLICY IF EXISTS user_isolation_policy ON {table};")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")
