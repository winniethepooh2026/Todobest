"""Add searchable titles and task attributes.

Revision ID: 0022_search_task_attrs
Revises: 0021_space_quotas
Create Date: 2026-09-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0022_search_task_attrs"
down_revision: str | None = "0021_space_quotas"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    for table in ("tasks", "pages", "todos"):
        op.add_column(
            table, sa.Column("title_blind_index", sa.LargeBinary(length=32), nullable=True)
        )

    # Existing encrypted values are backfilled in small, resumable transactions
    # by `noki backfill-production-data` after the additive schema migration.

    op.add_column(
        "tasks",
        sa.Column("priority", sa.String(length=16), nullable=False, server_default="none"),
    )
    op.add_column("tasks", sa.Column("estimate", sa.Integer(), nullable=True))
    op.add_column("tasks", sa.Column("parent_task_id", sa.Uuid(), nullable=True))
    op.create_check_constraint(
        op.f("ck_tasks_priority_valid"),
        "tasks",
        "priority IN ('none', 'low', 'medium', 'high', 'urgent')",
        postgresql_not_valid=True,
    )
    op.create_check_constraint(
        op.f("ck_tasks_estimate_nonnegative"),
        "tasks",
        "estimate IS NULL OR estimate >= 0",
        postgresql_not_valid=True,
    )
    op.execute("ALTER TABLE tasks VALIDATE CONSTRAINT ck_tasks_priority_valid")
    op.execute("ALTER TABLE tasks VALIDATE CONSTRAINT ck_tasks_estimate_nonnegative")
    op.create_foreign_key(
        op.f("fk_tasks_parent_task_id_tasks"),
        "tasks",
        "tasks",
        ["parent_task_id"],
        ["id"],
        ondelete="SET NULL",
        postgresql_not_valid=True,
    )
    op.execute("ALTER TABLE tasks VALIDATE CONSTRAINT fk_tasks_parent_task_id_tasks")

    op.create_table(
        "task_labels",
        sa.Column("board_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("color", sa.String(length=7), nullable=False, server_default="#71717a"),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "char_length(name) BETWEEN 1 AND 40", name=op.f("ck_task_labels_name_length")
        ),
        sa.CheckConstraint("color ~ '^#[0-9a-fA-F]{6}$'", name=op.f("ck_task_labels_color_format")),
        sa.ForeignKeyConstraint(["board_id"], ["issue_boards.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("board_id", "name", name="uq_task_labels_board_name"),
    )
    op.create_index(op.f("ix_task_labels_board_id"), "task_labels", ["board_id"])
    op.create_table(
        "task_label_links",
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("label_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["label_id"], ["task_labels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("task_id", "label_id"),
        sa.UniqueConstraint("task_id", "label_id", name="uq_task_label_links"),
    )
    op.create_table(
        "task_relations",
        sa.Column("source_task_id", sa.Uuid(), nullable=False),
        sa.Column("target_task_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source_task_id <> target_task_id", name=op.f("ck_task_relations_different_tasks")
        ),
        sa.CheckConstraint(
            "kind IN ('blocks', 'relates_to', 'duplicates')",
            name=op.f("ck_task_relations_kind_valid"),
        ),
        sa.ForeignKeyConstraint(["source_task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_task_id", "target_task_id", "kind", name="uq_task_relation"),
    )
    op.create_index(op.f("ix_task_relations_source_task_id"), "task_relations", ["source_task_id"])
    op.create_index(op.f("ix_task_relations_target_task_id"), "task_relations", ["target_task_id"])
    op.create_table(
        "task_activities",
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("field", sa.String(length=40), nullable=True),
        sa.Column("summary", sa.String(length=300), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_task_activities_task_id"), "task_activities", ["task_id"])
    op.create_index(op.f("ix_task_activities_actor_id"), "task_activities", ["actor_id"])
    op.add_column("uploads", sa.Column("task_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_uploads_task_id_tasks"),
        "uploads",
        "tasks",
        ["task_id"],
        ["id"],
        ondelete="SET NULL",
        postgresql_not_valid=True,
    )
    op.execute("ALTER TABLE uploads VALIDATE CONSTRAINT fk_uploads_task_id_tasks")


def downgrade() -> None:
    op.drop_constraint(op.f("fk_uploads_task_id_tasks"), "uploads", type_="foreignkey")
    op.drop_column("uploads", "task_id")
    op.drop_table("task_activities")
    op.drop_table("task_relations")
    op.drop_table("task_label_links")
    op.drop_table("task_labels")
    op.drop_constraint(op.f("fk_tasks_parent_task_id_tasks"), "tasks", type_="foreignkey")
    op.drop_constraint(op.f("ck_tasks_estimate_nonnegative"), "tasks", type_="check")
    op.drop_constraint(op.f("ck_tasks_priority_valid"), "tasks", type_="check")
    op.drop_column("tasks", "parent_task_id")
    op.drop_column("tasks", "estimate")
    op.drop_column("tasks", "priority")
    for table in ("todos", "pages", "tasks"):
        op.drop_column(table, "title_blind_index")
