"""Add color field to board_columns.

Revision ID: 0012_board_column_color
Revises: 0011_issue_board_default
Create Date: 2026-08-07
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012_board_column_color"
down_revision: str | None = "0011_issue_board_default"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "board_columns",
        sa.Column("color", sa.String(length=7), nullable=True),
    )
    op.create_check_constraint(
        "color_format",
        "board_columns",
        "color IS NULL OR color ~ '^#[0-9a-fA-F]{6}$'",
    )


def downgrade() -> None:
    op.drop_constraint("color_format", "board_columns", type_="check")
    op.drop_column("board_columns", "color")
