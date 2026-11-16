"""Add email security, invitations, exports and trash lifecycle.

Revision ID: 0019_product_foundations
Revises: 0018_todo_completed_by
Create Date: 2026-09-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0019_product_foundations"
down_revision: str | None = "0018_todo_completed_by"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    for column in ("email_verified_at", "terms_accepted_at", "privacy_accepted_at", "deleted_at"):
        op.add_column("users", sa.Column(column, sa.DateTime(timezone=True), nullable=True))
    # Legacy accounts are grandfathered by the resumable production backfill
    # before the new application version is started.
    op.add_column("spaces", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "spaces",
        sa.Column("trash_retention_days", sa.Integer(), server_default="7", nullable=False),
    )
    for table in ("teams", "issue_boards", "pages", "tasks"):
        op.add_column(table, sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        # Indexes on populated tables are created concurrently by revision 0023.

    op.create_table(
        "one_time_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("purpose IN ('verify_email', 'reset_password')", name="purpose_valid"),
        sa.CheckConstraint("length(token_hash) = 64", name="token_hash_length"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("user_id", "purpose", "expires_at"):
        op.create_index(op.f(f"ix_one_time_tokens_{column}"), "one_time_tokens", [column])
    op.create_index(
        op.f("ix_one_time_tokens_token_hash"), "one_time_tokens", ["token_hash"], unique=True
    )

    op.create_table(
        "invitations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=True),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("invited_by_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('owner', 'admin', 'member')", name="role_valid"),
        sa.CheckConstraint("length(token_hash) = 64", name="token_hash_length"),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invited_by_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("space_id", "team_id", "email", "expires_at"):
        op.create_index(op.f(f"ix_invitations_{column}"), "invitations", [column])
    op.create_index(op.f("ix_invitations_token_hash"), "invitations", ["token_hash"], unique=True)

    op.create_table(
        "space_exports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("file_path", sa.String(1024), nullable=True),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'ready', 'failed')", name="status_valid"
        ),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("space_id", "requested_by_id", "expires_at"):
        op.create_index(op.f(f"ix_space_exports_{column}"), "space_exports", [column])


def downgrade() -> None:
    op.drop_table("space_exports")
    op.drop_table("invitations")
    op.drop_table("one_time_tokens")
    for table in ("tasks", "pages", "issue_boards", "teams"):
        op.drop_column(table, "deleted_at")
    op.drop_column("spaces", "trash_retention_days")
    op.drop_column("spaces", "deleted_at")
    for column in ("deleted_at", "privacy_accepted_at", "terms_accepted_at", "email_verified_at"):
        op.drop_column("users", column)
