"""Initial Noki MVP schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("google_sub", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_google_sub", "users", ["google_sub"], unique=True)

    op.create_table(
        "user_sessions",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("refresh_jti", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_sessions_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_user_sessions"),
    )
    op.create_index("ix_user_sessions_expires_at", "user_sessions", ["expires_at"], unique=False)
    op.create_index("ix_user_sessions_refresh_jti", "user_sessions", ["refresh_jti"], unique=True)
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"], unique=False)

    op.create_table(
        "spaces",
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "char_length(name) BETWEEN 1 AND 80",
            name=op.f("ck_spaces_name_length"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_spaces_created_by_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_spaces"),
    )
    op.create_index("ix_spaces_created_by_id", "spaces", ["created_by_id"], unique=False)

    op.create_table(
        "space_members",
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(
            ["space_id"],
            ["spaces.id"],
            name="fk_space_members_space_id_spaces",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_space_members_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("space_id", "user_id", name="pk_space_members"),
    )
    op.create_index("ix_space_members_user_id", "space_members", ["user_id"], unique=False)

    op.create_table(
        "teams",
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "char_length(name) BETWEEN 1 AND 80",
            name=op.f("ck_teams_name_length"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_teams_created_by_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["space_id"],
            ["spaces.id"],
            name="fk_teams_space_id_spaces",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_teams"),
        sa.UniqueConstraint("space_id", "name", name="uq_teams_space_name"),
    )
    op.create_index("ix_teams_created_by_id", "teams", ["created_by_id"], unique=False)
    op.create_index("ix_teams_space_id", "teams", ["space_id"], unique=False)

    op.create_table(
        "team_members",
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["teams.id"],
            name="fk_team_members_team_id_teams",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_team_members_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("team_id", "user_id", name="pk_team_members"),
    )
    op.create_index("ix_team_members_user_id", "team_members", ["user_id"], unique=False)

    op.create_table(
        "issue_boards",
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("key", sa.String(length=3), nullable=False),
        sa.Column("next_task_number", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "key ~ '^[A-Z]{3}$'",
            name=op.f("ck_issue_boards_key_format"),
        ),
        sa.CheckConstraint(
            "char_length(name) BETWEEN 1 AND 100",
            name=op.f("ck_issue_boards_name_length"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_issue_boards_created_by_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["teams.id"],
            name="fk_issue_boards_team_id_teams",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_issue_boards"),
        sa.UniqueConstraint("team_id", "key", name="uq_issue_boards_team_key"),
    )
    op.create_index(
        "ix_issue_boards_created_by_id",
        "issue_boards",
        ["created_by_id"],
        unique=False,
    )
    op.create_index("ix_issue_boards_team_id", "issue_boards", ["team_id"], unique=False)

    op.create_table(
        "board_columns",
        sa.Column("board_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "char_length(name) BETWEEN 1 AND 40",
            name=op.f("ck_board_columns_name_length"),
        ),
        sa.ForeignKeyConstraint(
            ["board_id"],
            ["issue_boards.id"],
            name="fk_board_columns_board_id_issue_boards",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_board_columns"),
        sa.UniqueConstraint(
            "board_id",
            "position",
            name="uq_board_columns_board_position",
        ),
    )
    op.create_index("ix_board_columns_board_id", "board_columns", ["board_id"], unique=False)

    op.create_table(
        "tasks",
        sa.Column("board_id", sa.Uuid(), nullable=False),
        sa.Column("status_id", sa.Uuid(), nullable=False),
        sa.Column("assignee_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "char_length(description) <= 5000",
            name=op.f("ck_tasks_description_length"),
        ),
        sa.CheckConstraint(
            "char_length(title) BETWEEN 1 AND 200",
            name=op.f("ck_tasks_title_length"),
        ),
        sa.ForeignKeyConstraint(
            ["assignee_id"],
            ["users.id"],
            name="fk_tasks_assignee_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["board_id"],
            ["issue_boards.id"],
            name="fk_tasks_board_id_issue_boards",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_tasks_created_by_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["status_id"],
            ["board_columns.id"],
            name="fk_tasks_status_id_board_columns",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tasks"),
        sa.UniqueConstraint("board_id", "number", name="uq_tasks_board_number"),
    )
    op.create_index("ix_tasks_assignee_id", "tasks", ["assignee_id"], unique=False)
    op.create_index("ix_tasks_board_id", "tasks", ["board_id"], unique=False)
    op.create_index("ix_tasks_created_by_id", "tasks", ["created_by_id"], unique=False)
    op.create_index("ix_tasks_deadline", "tasks", ["deadline"], unique=False)
    op.create_index("ix_tasks_status_id", "tasks", ["status_id"], unique=False)

    op.create_table(
        "pages",
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "char_length(markdown) <= 200000",
            name=op.f("ck_pages_markdown_length"),
        ),
        sa.CheckConstraint(
            "char_length(title) BETWEEN 1 AND 200",
            name=op.f("ck_pages_title_length"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_pages_created_by_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["teams.id"],
            name="fk_pages_team_id_teams",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_pages"),
    )
    op.create_index("ix_pages_created_by_id", "pages", ["created_by_id"], unique=False)
    op.create_index("ix_pages_team_id", "pages", ["team_id"], unique=False)

    op.create_table(
        "uploads",
        sa.Column("filename", sa.String(length=80), nullable=False),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=80), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("page_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "width > 0 AND height > 0",
            name=op.f("ck_uploads_positive_dimensions"),
        ),
        sa.CheckConstraint(
            "size_bytes > 0",
            name=op.f("ck_uploads_positive_size"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name="fk_uploads_owner_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["page_id"],
            ["pages.id"],
            name="fk_uploads_page_id_pages",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_uploads"),
    )
    op.create_index("ix_uploads_filename", "uploads", ["filename"], unique=True)
    op.create_index("ix_uploads_owner_id", "uploads", ["owner_id"], unique=False)
    op.create_index("ix_uploads_page_id", "uploads", ["page_id"], unique=False)


def downgrade() -> None:
    op.drop_table("uploads")
    op.drop_table("pages")
    op.drop_table("tasks")
    op.drop_table("board_columns")
    op.drop_table("issue_boards")
    op.drop_table("team_members")
    op.drop_table("teams")
    op.drop_table("space_members")
    op.drop_table("spaces")
    op.drop_table("user_sessions")
    op.drop_table("users")
