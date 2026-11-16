"""Create indexes on populated tables without blocking normal writes.

Revision ID: 0023_online_indexes
Revises: 0022_search_task_attrs
Create Date: 2026-09-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import context, op

revision: str = "0023_online_indexes"
down_revision: str | None = "0022_search_task_attrs"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

INDEXES = (
    ("ix_users_deleted_at", "users", "deleted_at"),
    ("ix_spaces_deleted_at", "spaces", "deleted_at"),
    ("ix_teams_deleted_at", "teams", "deleted_at"),
    ("ix_issue_boards_deleted_at", "issue_boards", "deleted_at"),
    ("ix_pages_deleted_at", "pages", "deleted_at"),
    ("ix_tasks_deleted_at", "tasks", "deleted_at"),
    ("ix_spaces_owner_user_id", "spaces", "owner_user_id"),
    ("ix_uploads_space_id", "uploads", "space_id"),
    ("ix_tasks_title_blind_index", "tasks", "title_blind_index"),
    ("ix_pages_title_blind_index", "pages", "title_blind_index"),
    ("ix_todos_title_blind_index", "todos", "title_blind_index"),
    ("ix_tasks_priority", "tasks", "priority"),
    ("ix_tasks_parent_task_id", "tasks", "parent_task_id"),
    ("ix_uploads_task_id", "uploads", "task_id"),
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


def _create_index(name: str, table: str, column: str) -> None:
    valid = _index_valid(name)
    if valid is False:
        with op.get_context().autocommit_block():
            op.execute(sa.text(f'DROP INDEX CONCURRENTLY IF EXISTS "{name}"'))
        valid = None
    if valid is None:
        with op.get_context().autocommit_block():
            op.execute(
                sa.text(
                    f'CREATE INDEX CONCURRENTLY IF NOT EXISTS "{name}" ON "{table}" ("{column}")'
                )
            )


def upgrade() -> None:
    for name, table, column in INDEXES:
        _create_index(name, table, column)


def downgrade() -> None:
    for name, _table, _column in reversed(INDEXES):
        with op.get_context().autocommit_block():
            op.execute(sa.text(f'DROP INDEX CONCURRENTLY IF EXISTS "{name}"'))
