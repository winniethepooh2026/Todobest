"""Add completed_by tracking for todos.

Revision ID: 0018_todo_completed_by
Revises: 0017_public_api_tokens
Create Date: 2026-08-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0018_todo_completed_by"
down_revision: str | None = "0017_public_api_tokens"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "todos",
        sa.Column("completed_by_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        op.f("ix_todos_completed_by_id"),
        "todos",
        ["completed_by_id"],
    )
    op.create_foreign_key(
        "fk_todos_completed_by_id_users",
        "todos",
        "users",
        ["completed_by_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_todos_completed_by_id_users", "todos", type_="foreignkey")
    op.drop_index(op.f("ix_todos_completed_by_id"), table_name="todos")
    op.drop_column("todos", "completed_by_id")
