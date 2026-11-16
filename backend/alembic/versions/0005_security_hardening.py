"""Add a revocable authentication version to users.

Revision ID: 0005_security_hardening
Revises: 0004_system_statuses
Create Date: 2026-07-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_security_hardening"
down_revision: str | None = "0004_system_statuses"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "auth_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.create_check_constraint(
        op.f("ck_users_auth_version_nonnegative"),
        "users",
        "auth_version >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_users_auth_version_nonnegative"),
        "users",
        type_="check",
    )
    op.drop_column("users", "auth_version")
