"""Add optional encrypted TOTP credentials.

Revision ID: 0026_totp
Revises: 0025_session_devices
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0026_totp"
down_revision: str | None = "0025_session_devices"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("totp_secret", sa.String(512), nullable=True))
    op.add_column("users", sa.Column("totp_pending_secret", sa.String(512), nullable=True))
    op.add_column(
        "users", sa.Column("totp_pending_created_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "users", sa.Column("totp_last_counter", sa.Integer(), server_default="-1", nullable=False)
    )
    op.add_column("users", sa.Column("totp_recovery_hashes", sa.String(2048), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "totp_recovery_hashes")
    op.drop_column("users", "totp_last_counter")
    op.drop_column("users", "totp_pending_created_at")
    op.drop_column("users", "totp_pending_secret")
    op.drop_column("users", "totp_secret")
