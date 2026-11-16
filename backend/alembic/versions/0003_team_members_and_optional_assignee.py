"""Complete Team memberships and allow unassigned tasks.

Revision ID: 0003_team_members
Revises: 0002_secure_content
Create Date: 2026-07-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_team_members"
down_revision: str | None = "0002_secure_content"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        op.f("ck_team_members_role_valid"),
        "team_members",
        "role IN ('owner', 'admin', 'member')",
    )

    op.drop_constraint(
        op.f("fk_tasks_assignee_id_users"),
        "tasks",
        type_="foreignkey",
    )
    op.alter_column(
        "tasks",
        "assignee_id",
        existing_type=sa.Uuid(),
        nullable=True,
    )
    op.create_foreign_key(
        op.f("fk_tasks_assignee_id_users"),
        "tasks",
        "users",
        ["assignee_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    bind = op.get_bind()
    unassigned_count = int(
        bind.scalar(sa.text("SELECT count(*) FROM tasks WHERE assignee_id IS NULL")) or 0
    )
    if unassigned_count:
        raise RuntimeError(
            "Cannot downgrade 0003_team_members while unassigned tasks exist. "
            "Assign or export them explicitly first; the migration will not "
            "silently change assignment state."
        )

    op.drop_constraint(
        op.f("fk_tasks_assignee_id_users"),
        "tasks",
        type_="foreignkey",
    )
    op.alter_column(
        "tasks",
        "assignee_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )
    op.create_foreign_key(
        op.f("fk_tasks_assignee_id_users"),
        "tasks",
        "users",
        ["assignee_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.drop_constraint(
        op.f("ck_team_members_role_valid"),
        "team_members",
        type_="check",
    )
