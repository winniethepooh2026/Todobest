"""Store private S3 avatar object metadata on users.

Revision ID: 0010_user_avatars
Revises: 0009_todo_constraints
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010_user_avatars"
down_revision: str | None = "0009_todo_constraints"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("avatar_object_key", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("avatar_content_hash", sa.String(length=64), nullable=True))
    op.add_column(
        "users",
        sa.Column("avatar_source_url_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("avatar_requested_source_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "avatar_import_generation",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column("avatar_synced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_users_avatar_object_and_hash_together",
        "users",
        "(avatar_object_key IS NULL) = (avatar_content_hash IS NULL)",
    )
    op.create_check_constraint(
        "ck_users_avatar_content_hash_length",
        "users",
        "avatar_content_hash IS NULL OR length(avatar_content_hash) = 64",
    )
    op.create_check_constraint(
        "ck_users_avatar_source_url_hash_length",
        "users",
        "avatar_source_url_hash IS NULL OR length(avatar_source_url_hash) = 64",
    )
    op.create_check_constraint(
        "ck_users_avatar_requested_source_hash_length",
        "users",
        "avatar_requested_source_hash IS NULL OR length(avatar_requested_source_hash) = 64",
    )
    op.create_check_constraint(
        "ck_users_avatar_import_generation_nonnegative",
        "users",
        "avatar_import_generation >= 0",
    )
    op.create_unique_constraint("uq_users_avatar_object_key", "users", ["avatar_object_key"])


def downgrade() -> None:
    op.drop_constraint("uq_users_avatar_object_key", "users", type_="unique")
    op.drop_constraint(
        "ck_users_avatar_import_generation_nonnegative",
        "users",
        type_="check",
    )
    op.drop_constraint(
        "ck_users_avatar_requested_source_hash_length",
        "users",
        type_="check",
    )
    op.drop_constraint("ck_users_avatar_source_url_hash_length", "users", type_="check")
    op.drop_constraint("ck_users_avatar_content_hash_length", "users", type_="check")
    op.drop_constraint("ck_users_avatar_object_and_hash_together", "users", type_="check")
    op.drop_column("users", "avatar_synced_at")
    op.drop_column("users", "avatar_import_generation")
    op.drop_column("users", "avatar_requested_source_hash")
    op.drop_column("users", "avatar_source_url_hash")
    op.drop_column("users", "avatar_content_hash")
    op.drop_column("users", "avatar_object_key")
