"""Record session devices for user-visible session management.

Revision ID: 0025_session_devices
Revises: 0024_board_keys_and_order
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0025_session_devices"
down_revision: str | None = "0024_board_keys_and_order"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("user_sessions", sa.Column("user_agent", sa.String(512), nullable=True))
    op.add_column("user_sessions", sa.Column("ip_address", sa.String(45), nullable=True))
    op.add_column(
        "user_sessions", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("user_sessions", "last_seen_at")
    op.drop_column("user_sessions", "ip_address")
    op.drop_column("user_sessions", "user_agent")
