"""Add integrity constraints for personal todos.

Revision ID: 0009_todo_constraints
Revises: 0008_todos
Create Date: 2026-08-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009_todo_constraints"
down_revision: str | None = "0008_todos"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("UPDATE todos SET position = 0 WHERE position < 0"))
    op.create_check_constraint(
        op.f("ck_todos_status_valid"),
        "todos",
        "status IN ('todo', 'in_progress', 'done')",
    )
    op.create_check_constraint(
        op.f("ck_todos_position_nonnegative"),
        "todos",
        "position >= 0",
    )
    op.create_check_constraint(
        op.f("ck_todos_encryption_key_version_valid"),
        "todos",
        "encryption_key_version = 1",
    )
    op.create_check_constraint(
        op.f("ck_todos_encryption_metadata_lengths"),
        "todos",
        "length(title_nonce) = 12 AND length(title_tag) = 16 "
        "AND length(description_nonce) = 12 AND length(description_tag) = 16",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_todos_encryption_metadata_lengths"),
        "todos",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_todos_encryption_key_version_valid"),
        "todos",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_todos_position_nonnegative"),
        "todos",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_todos_status_valid"),
        "todos",
        type_="check",
    )
