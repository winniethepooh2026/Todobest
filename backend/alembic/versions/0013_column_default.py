"""Move is_default flag from issue_boards to board_columns.

Revision ID: 0013_column_default
Revises: 0012_board_column_color
Create Date: 2026-08-08
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013_column_default"
down_revision: str | None = "0012_board_column_color"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # 0011 originally shipped as a boolean-composite unique constraint. New
    # installations use a partial index instead, so accept either shape while
    # crossing this historical revision.
    op.drop_constraint(
        "uq_issue_boards_team_default",
        "issue_boards",
        type_="unique",
        if_exists=True,
    )
    op.drop_index(
        "uq_issue_boards_team_default",
        table_name="issue_boards",
        if_exists=True,
    )
    op.drop_column("issue_boards", "is_default")

    op.add_column(
        "board_columns",
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.execute(
        sa.text(
            """
            WITH ranked_columns AS (
                SELECT id,
                       row_number() OVER (
                           PARTITION BY board_id
                           ORDER BY position, created_at, id
                       ) AS column_rank
                FROM board_columns
            )
            UPDATE board_columns
            SET is_default = true
            FROM ranked_columns
            WHERE board_columns.id = ranked_columns.id
              AND ranked_columns.column_rank = 1
            """
        )
    )
    op.create_index(
        "uq_board_columns_board_default",
        "board_columns",
        ["board_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
        sqlite_where=sa.text("is_default"),
    )
    op.alter_column("board_columns", "is_default", server_default=None)


def downgrade() -> None:
    op.drop_index("uq_board_columns_board_default", table_name="board_columns")
    op.drop_column("board_columns", "is_default")

    op.add_column(
        "issue_boards",
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.execute(
        sa.text(
            """
            WITH ranked_boards AS (
                SELECT id,
                       row_number() OVER (
                           PARTITION BY team_id
                           ORDER BY created_at, id
                       ) AS board_rank
                FROM issue_boards
            )
            UPDATE issue_boards
            SET is_default = true
            FROM ranked_boards
            WHERE issue_boards.id = ranked_boards.id
              AND ranked_boards.board_rank = 1
            """
        )
    )
    op.create_index(
        "uq_issue_boards_team_default",
        "issue_boards",
        ["team_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
        sqlite_where=sa.text("is_default"),
    )
    op.alter_column("issue_boards", "is_default", server_default=None)
