"""Enforce encrypted metadata and cross-board task integrity.

Revision ID: 0006_data_integrity
Revises: 0005_security_hardening
Create Date: 2026-07-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_data_integrity"
down_revision: str | None = "0005_security_hardening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    mismatched_statuses = int(
        bind.scalar(
            sa.text(
                """
                SELECT count(*)
                FROM tasks AS task
                JOIN board_columns AS status_column ON status_column.id = task.status_id
                WHERE task.board_id <> status_column.board_id
                """
            )
        )
        or 0
    )
    if mismatched_statuses:
        raise RuntimeError(
            "Cannot enforce task status integrity: "
            f"{mismatched_statuses} task(s) reference a column from another board"
        )

    op.create_check_constraint(
        op.f("ck_issue_boards_next_task_number_positive"),
        "issue_boards",
        "next_task_number > 0",
    )
    op.create_unique_constraint(
        "uq_board_columns_id_board_id",
        "board_columns",
        ["id", "board_id"],
    )
    op.create_check_constraint(
        op.f("ck_board_columns_position_nonnegative"),
        "board_columns",
        "position >= 0",
    )
    op.drop_constraint(
        "fk_tasks_status_id_board_columns",
        "tasks",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_tasks_status_id_board_columns",
        "tasks",
        "board_columns",
        ["status_id"],
        ["id"],
        ondelete="NO ACTION",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_tasks_status_board_columns",
        "tasks",
        "board_columns",
        ["status_id", "board_id"],
        ["id", "board_id"],
        ondelete="NO ACTION",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_check_constraint(
        op.f("ck_tasks_number_positive"),
        "tasks",
        "number > 0",
    )
    op.create_check_constraint(
        op.f("ck_tasks_position_nonnegative"),
        "tasks",
        "position >= 0",
    )
    op.create_check_constraint(
        op.f("ck_tasks_encryption_key_version_valid"),
        "tasks",
        "encryption_key_version = 1",
    )
    op.create_check_constraint(
        op.f("ck_tasks_encryption_metadata_lengths"),
        "tasks",
        "length(title_nonce) = 12 AND length(title_tag) = 16 "
        "AND length(description_nonce) = 12 AND length(description_tag) = 16",
    )
    op.create_check_constraint(
        op.f("ck_pages_encryption_key_version_valid"),
        "pages",
        "encryption_key_version = 1",
    )
    op.create_check_constraint(
        op.f("ck_pages_encryption_metadata_lengths"),
        "pages",
        "length(title_nonce) = 12 AND length(title_tag) = 16 "
        "AND length(content_nonce) = 12 AND length(content_tag) = 16 "
        "AND length(markdown_nonce) = 12 AND length(markdown_tag) = 16",
    )
    op.create_check_constraint(
        op.f("ck_uploads_content_type_webp"),
        "uploads",
        "content_type = 'image/webp'",
    )
    op.create_check_constraint(
        op.f("ck_uploads_encryption_key_version_valid"),
        "uploads",
        "encryption_key_version = 1",
    )
    op.create_check_constraint(
        op.f("ck_uploads_encryption_metadata_lengths"),
        "uploads",
        "length(original_name_nonce) = 12 AND length(original_name_tag) = 16",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_uploads_encryption_metadata_lengths"),
        "uploads",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_uploads_encryption_key_version_valid"),
        "uploads",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_uploads_content_type_webp"),
        "uploads",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_pages_encryption_metadata_lengths"),
        "pages",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_pages_encryption_key_version_valid"),
        "pages",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_tasks_encryption_metadata_lengths"),
        "tasks",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_tasks_encryption_key_version_valid"),
        "tasks",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_tasks_position_nonnegative"),
        "tasks",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_tasks_number_positive"),
        "tasks",
        type_="check",
    )
    op.drop_constraint(
        "fk_tasks_status_board_columns",
        "tasks",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_tasks_status_id_board_columns",
        "tasks",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_tasks_status_id_board_columns",
        "tasks",
        "board_columns",
        ["status_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        op.f("ck_board_columns_position_nonnegative"),
        "board_columns",
        type_="check",
    )
    op.drop_constraint(
        "uq_board_columns_id_board_id",
        "board_columns",
        type_="unique",
    )
    op.drop_constraint(
        op.f("ck_issue_boards_next_task_number_positive"),
        "issue_boards",
        type_="check",
    )
