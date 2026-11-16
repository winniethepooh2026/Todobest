"""Allow flexible board keys and speed up board card ordering.

Revision ID: 0024_board_keys_and_order
Revises: 0023_online_indexes
Create Date: 2026-09-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import context, op

revision: str = "0024_board_keys_and_order"
down_revision: str | None = "0023_online_indexes"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

INDEXES = (
    (
        "ix_tasks_board_status_position",
        "ON tasks (board_id, status_id, position, id) WHERE deleted_at IS NULL",
    ),
    (
        "ix_tasks_assignee_updated",
        "ON tasks (assignee_id, updated_at, id) "
        "WHERE deleted_at IS NULL AND assignee_id IS NOT NULL",
    ),
)


def _index_valid(name: str) -> bool | None:
    if context.is_offline_mode():
        return None
    return (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT i.indisvalid FROM pg_catalog.pg_index i "
                "JOIN pg_catalog.pg_class c ON c.oid = i.indexrelid "
                "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = current_schema() AND c.relname = :name"
            ),
            {"name": name},
        )
        .scalar_one_or_none()
    )


def _ensure_index(name: str, definition: str) -> None:
    valid = _index_valid(name)
    if valid is False:
        with op.get_context().autocommit_block():
            op.execute(sa.text(f'DROP INDEX CONCURRENTLY IF EXISTS "{name}"'))
        valid = None
    if valid is None:
        with op.get_context().autocommit_block():
            op.execute(sa.text(f'CREATE INDEX CONCURRENTLY IF NOT EXISTS "{name}" {definition}'))


def upgrade() -> None:
    # Build indexes first. If an online build fails, a rerun can drop the
    # invalid index and retry before any column or constraint change.
    for name, definition in INDEXES:
        _ensure_index(name, definition)
    op.drop_constraint("key_format", "issue_boards", type_="check")
    op.alter_column(
        "issue_boards",
        "key",
        existing_type=sa.String(length=3),
        type_=sa.String(length=5),
        existing_nullable=False,
    )
    op.create_check_constraint("key_format", "issue_boards", "key ~ '^[A-Z]{2,5}$'")


def downgrade() -> None:
    # New 2-, 4- or 5-character keys cannot be represented by the old schema.
    overlong = (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM issue_boards WHERE char_length(key) <> 3 LIMIT 1"))
        .scalar_one_or_none()
    )
    if overlong is not None:
        raise RuntimeError("Change every board key to exactly three letters before downgrading")
    for name, _definition in reversed(INDEXES):
        with op.get_context().autocommit_block():
            op.execute(sa.text(f'DROP INDEX CONCURRENTLY IF EXISTS "{name}"'))
    op.drop_constraint("key_format", "issue_boards", type_="check")
    op.alter_column(
        "issue_boards",
        "key",
        existing_type=sa.String(length=5),
        type_=sa.String(length=3),
        existing_nullable=False,
    )
    op.create_check_constraint("key_format", "issue_boards", "key ~ '^[A-Z]{3}$'")
