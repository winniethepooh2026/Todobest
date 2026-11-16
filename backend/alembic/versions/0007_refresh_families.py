"""Rotate refresh-token families in one bounded session row.

Revision ID: 0007_refresh_families
Revises: 0006_data_integrity
Create Date: 2026-07-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007_refresh_families"
down_revision: str | None = "0006_data_integrity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_CHECK_CONSTRAINTS = {
    "issue_boards": ["ck_issue_boards_next_task_number_positive"],
    "board_columns": ["ck_board_columns_position_nonnegative"],
    "tasks": [
        "ck_tasks_number_positive",
        "ck_tasks_position_nonnegative",
        "ck_tasks_encryption_key_version_valid",
        "ck_tasks_encryption_metadata_lengths",
    ],
    "pages": [
        "ck_pages_encryption_key_version_valid",
        "ck_pages_encryption_metadata_lengths",
    ],
    "uploads": [
        "ck_uploads_content_type_webp",
        "ck_uploads_encryption_key_version_valid",
        "ck_uploads_encryption_metadata_lengths",
    ],
}


def _repair_legacy_check_constraint_names() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    existing = set(
        bind.scalars(
            sa.text(
                """
                SELECT constraint_name
                FROM information_schema.table_constraints
                WHERE constraint_schema = current_schema()
                  AND constraint_type = 'CHECK'
                """
            )
        ).all()
    )
    for table_name, expected_names in LEGACY_CHECK_CONSTRAINTS.items():
        for expected_name in expected_names:
            legacy_name = f"ck_{table_name}_{expected_name}"
            if legacy_name not in existing:
                continue
            if expected_name in existing:
                op.drop_constraint(
                    op.f(legacy_name),
                    table_name,
                    type_="check",
                )
            else:
                op.execute(
                    sa.text(
                        f'ALTER TABLE "{table_name}" '
                        f'RENAME CONSTRAINT "{legacy_name}" TO "{expected_name}"'
                    )
                )


def upgrade() -> None:
    _repair_legacy_check_constraint_names()
    # Pre-family refresh JWTs do not contain the stable session id. Force a
    # one-time sign-in so every token accepted after this revision participates
    # in replay detection.
    op.execute(sa.text("UPDATE users SET auth_version = auth_version + 1"))
    op.execute(sa.text("DELETE FROM user_sessions"))


def downgrade() -> None:
    # Tokens issued by this revision contain claims older code does not use.
    op.execute(sa.text("UPDATE users SET auth_version = auth_version + 1"))
    op.execute(sa.text("DELETE FROM user_sessions"))
