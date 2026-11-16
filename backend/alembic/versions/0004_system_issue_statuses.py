"""Add stable system statuses for member Issue transitions.

Revision ID: 0004_system_statuses
Revises: 0003_team_members
Create Date: 2026-07-28
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid5

import sqlalchemy as sa

from alembic import op

revision: str = "0004_system_statuses"
down_revision: str | None = "0003_team_members"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GENERATED_STATUS_NAMESPACE = UUID("48f7aa41-af0f-4cca-9e52-1b7c3c60c334")
SYSTEM_STATUS_NAMES = {
    "todo": "Todo",
    "in_progress": "In Progress",
    "done": "Done",
}


def _generated_status_column_id(board_id: object, system_status: str) -> UUID:
    return uuid5(GENERATED_STATUS_NAMESPACE, f"{board_id}:{system_status}")


def _unique_system_column_name(base_name: str, existing_names: set[str]) -> str:
    candidate = base_name
    suffix = 1
    while candidate.casefold() in existing_names:
        suffix += 1
        label = "system" if suffix == 2 else f"system {suffix}"
        candidate = f"{base_name} ({label})"
    existing_names.add(candidate.casefold())
    return candidate


def upgrade() -> None:
    bind = op.get_bind()
    op.add_column(
        "board_columns",
        sa.Column("system_status", sa.String(length=20), nullable=True),
    )

    # Mark only unambiguous legacy defaults. Do not infer security semantics
    # from position: users could rename and reorder arbitrary custom columns.
    op.execute(
        """
        WITH labelled AS (
            SELECT
                id,
                CASE lower(trim(name))
                    WHEN 'todo' THEN 'todo'
                    WHEN 'in progress' THEN 'in_progress'
                    WHEN 'in_progress' THEN 'in_progress'
                    WHEN 'done' THEN 'done'
                END AS system_status,
                count(*) OVER (
                    PARTITION BY
                        board_id,
                        CASE lower(trim(name))
                            WHEN 'todo' THEN 'todo'
                            WHEN 'in progress' THEN 'in_progress'
                            WHEN 'in_progress' THEN 'in_progress'
                            WHEN 'done' THEN 'done'
                        END
                ) AS status_count
            FROM board_columns
            WHERE lower(trim(name)) IN ('todo', 'in progress', 'in_progress', 'done')
        )
        UPDATE board_columns AS target
        SET system_status = labelled.system_status
        FROM labelled
        WHERE target.id = labelled.id
          AND labelled.status_count = 1
        """
    )
    # Legacy boards were configurable and can have fewer than three columns.
    # Add only genuinely missing system statuses so every upgraded board
    # supports the member status endpoint without guessing another column.
    board_columns = sa.table(
        "board_columns",
        sa.column("id", sa.Uuid()),
        sa.column("board_id", sa.Uuid()),
        sa.column("name", sa.String()),
        sa.column("position", sa.Integer()),
        sa.column("system_status", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    board_ids = bind.scalars(sa.text("SELECT id FROM issue_boards")).all()
    now = datetime.now(UTC)
    board_plans: list[tuple[object, int, list[tuple[str, str]]]] = []
    blocked_board_ids: list[str] = []
    for board_id in board_ids:
        existing_statuses = set(
            bind.scalars(
                sa.select(board_columns.c.system_status).where(
                    board_columns.c.board_id == board_id,
                    board_columns.c.system_status.is_not(None),
                )
            ).all()
        )
        max_position = int(
            bind.scalar(
                sa.select(sa.func.coalesce(sa.func.max(board_columns.c.position), -1)).where(
                    board_columns.c.board_id == board_id
                )
            )
            or 0
        )
        missing_statuses = [
            status for status in SYSTEM_STATUS_NAMES if status not in existing_statuses
        ]
        existing_names = {
            name.casefold()
            for name in bind.scalars(
                sa.select(board_columns.c.name).where(board_columns.c.board_id == board_id)
            ).all()
        }
        missing_columns = [
            (
                system_status,
                _unique_system_column_name(
                    SYSTEM_STATUS_NAMES[system_status],
                    existing_names,
                ),
            )
            for system_status in missing_statuses
        ]
        existing_count = int(
            bind.scalar(
                sa.select(sa.func.count())
                .select_from(board_columns)
                .where(board_columns.c.board_id == board_id)
            )
            or 0
        )
        if existing_count + len(missing_statuses) > 10:
            blocked_board_ids.append(str(board_id))
        board_plans.append((board_id, max_position, missing_columns))

    if blocked_board_ids:
        board_list = ", ".join(blocked_board_ids)
        raise RuntimeError(
            "Cannot add safe system status columns without exceeding the "
            f"10-column Board limit. Reduce custom columns and rerun for Boards: {board_list}"
        )

    for board_id, max_position, missing_columns in board_plans:
        for offset, (system_status, column_name) in enumerate(missing_columns, start=1):
            bind.execute(
                sa.insert(board_columns).values(
                    id=_generated_status_column_id(board_id, system_status),
                    board_id=board_id,
                    name=column_name,
                    position=max_position + offset,
                    system_status=system_status,
                    created_at=now,
                    updated_at=now,
                )
            )

    op.create_check_constraint(
        op.f("ck_board_columns_system_status_valid"),
        "board_columns",
        "system_status IS NULL OR system_status IN ('todo', 'in_progress', 'done')",
    )
    op.create_unique_constraint(
        op.f("uq_board_columns_board_system_status"),
        "board_columns",
        ["board_id", "system_status"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    generated_ids = [
        _generated_status_column_id(board_id, system_status)
        for board_id in bind.scalars(sa.text("SELECT id FROM issue_boards")).all()
        for system_status in SYSTEM_STATUS_NAMES
    ]
    if generated_ids:
        tasks = sa.table(
            "tasks",
            sa.column("status_id", sa.Uuid()),
        )
        board_columns = sa.table(
            "board_columns",
            sa.column("id", sa.Uuid()),
        )
        referenced_count = int(
            bind.scalar(
                sa.select(sa.func.count())
                .select_from(tasks)
                .where(tasks.c.status_id.in_(generated_ids))
            )
            or 0
        )
        if referenced_count:
            raise RuntimeError(
                "Cannot downgrade 0004_system_statuses while tasks reference "
                "system columns created for legacy boards. Move or export those "
                "tasks explicitly first; the migration will not change statuses silently."
            )
        bind.execute(sa.delete(board_columns).where(board_columns.c.id.in_(generated_ids)))

    op.drop_constraint(
        op.f("uq_board_columns_board_system_status"),
        "board_columns",
        type_="unique",
    )
    op.drop_constraint(
        op.f("ck_board_columns_system_status_valid"),
        "board_columns",
        type_="check",
    )
    op.drop_column("board_columns", "system_status")
