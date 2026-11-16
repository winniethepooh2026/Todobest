"""Add is_default flag to issue_boards.

Revision ID: 0011_issue_board_default
Revises: 0010_user_avatars
Create Date: 2026-08-07
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011_issue_board_default"
down_revision: str | None = "0010_user_avatars"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "issue_boards",
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_unique_constraint(
        "uq_issue_boards_team_default",
        "issue_boards",
        ["team_id", "is_default"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.alter_column("issue_boards", "is_default", server_default=None)


def downgrade() -> None:
    op.drop_constraint("uq_issue_boards_team_default", "issue_boards", type_="unique")
    op.drop_column("issue_boards", "is_default")
