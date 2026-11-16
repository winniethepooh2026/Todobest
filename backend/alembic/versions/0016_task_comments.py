"""Add task_comments for Issue discussion threads.

Revision ID: 0016_task_comments
Revises: 0015_platform_admin
Create Date: 2026-08-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0016_task_comments"
down_revision: str | None = "0015_platform_admin"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "task_comments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("body_ciphertext", sa.LargeBinary, nullable=False),
        sa.Column("body_nonce", sa.LargeBinary(12), nullable=False),
        sa.Column("body_tag", sa.LargeBinary(16), nullable=False),
        sa.Column("encryption_key_version", sa.SmallInteger, nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("encryption_key_version = 1", name="encryption_key_version_valid"),
        sa.CheckConstraint(
            "length(body_nonce) = 12 AND length(body_tag) = 16",
            name="encryption_metadata_lengths",
        ),
    )
    op.create_index(op.f("ix_task_comments_task_id"), "task_comments", ["task_id"])
    op.create_index(op.f("ix_task_comments_created_by_id"), "task_comments", ["created_by_id"])


def downgrade() -> None:
    op.drop_table("task_comments")
