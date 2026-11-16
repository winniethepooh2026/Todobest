"""Add bio field to users.

Revision ID: 0014_user_bio
Revises: 0013_column_default
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014_user_bio"
down_revision: str | None = "0013_column_default"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("bio", sa.String(length=280), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "bio")
