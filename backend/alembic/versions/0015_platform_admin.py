"""Add platform admin flag to users.

Revision ID: 0015_platform_admin
Revises: 0014_user_bio
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015_platform_admin"
down_revision: str | None = "0014_user_bio"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_platform_admin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.alter_column("users", "is_platform_admin", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "is_platform_admin")
