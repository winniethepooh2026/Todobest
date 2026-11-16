"""Add personal todos

Revision ID: 0008_todos
Revises: 0007_refresh_families
Create Date: 2026-08-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008_todos"
down_revision: str | None = "0007_refresh_families"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "todos",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("title_ciphertext", sa.LargeBinary, nullable=False),
        sa.Column("title_nonce", sa.LargeBinary(12), nullable=False),
        sa.Column("title_tag", sa.LargeBinary(16), nullable=False),
        sa.Column("description_ciphertext", sa.LargeBinary, nullable=False),
        sa.Column("description_nonce", sa.LargeBinary(12), nullable=False),
        sa.Column("description_tag", sa.LargeBinary(16), nullable=False),
        sa.Column("encryption_key_version", sa.SmallInteger, nullable=False),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_todos_user_id"), "todos", ["user_id"])
    op.create_index(op.f("ix_todos_deadline"), "todos", ["deadline"])


def downgrade() -> None:
    op.drop_table("todos")
