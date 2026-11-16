"""Add personal access tokens for the public API.

Revision ID: 0017_public_api_tokens
Revises: 0016_task_comments
Create Date: 2026-08-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0017_public_api_tokens"
down_revision: str | None = "0016_task_comments"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "api_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("token_prefix", sa.String(length=17), nullable=False),
        sa.Column("scopes", sa.String(length=32), nullable=False),
        sa.Column("auth_version", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(name) BETWEEN 1 AND 80", name="name_length"),
        sa.CheckConstraint("length(token_hash) = 64", name="token_hash_length"),
        sa.CheckConstraint("length(token_prefix) = 17", name="token_prefix_length"),
        sa.CheckConstraint("scopes IN ('read', 'read,write')", name="scopes_valid"),
        sa.CheckConstraint("auth_version >= 0", name="auth_version_nonnegative"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_api_tokens_user_id"), "api_tokens", ["user_id"])
    op.create_index(
        op.f("ix_api_tokens_token_hash"),
        "api_tokens",
        ["token_hash"],
        unique=True,
    )
    op.create_index(op.f("ix_api_tokens_expires_at"), "api_tokens", ["expires_at"])
    op.create_index(op.f("ix_api_tokens_revoked_at"), "api_tokens", ["revoked_at"])


def downgrade() -> None:
    op.drop_table("api_tokens")
