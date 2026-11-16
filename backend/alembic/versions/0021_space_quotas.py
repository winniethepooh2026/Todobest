"""Scope uploads to Space for plan quotas.

Revision ID: 0021_space_quotas
Revises: 0020_billing_foundations
Create Date: 2026-09-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0021_space_quotas"
down_revision: str | None = "0020_billing_foundations"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("uploads", sa.Column("space_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_uploads_space_id_spaces"),
        "uploads",
        "spaces",
        ["space_id"],
        ["id"],
        ondelete="CASCADE",
        postgresql_not_valid=True,
    )
    op.execute("ALTER TABLE uploads VALIDATE CONSTRAINT fk_uploads_space_id_spaces")


def downgrade() -> None:
    op.drop_constraint(op.f("fk_uploads_space_id_spaces"), "uploads", type_="foreignkey")
    op.drop_column("uploads", "space_id")
