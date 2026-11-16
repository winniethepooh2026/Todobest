"""Add plans, subscriptions and billing history.

Revision ID: 0020_billing_foundations
Revises: 0019_product_foundations
Create Date: 2026-09-14
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0020_billing_foundations"
down_revision: str | None = "0019_product_foundations"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("spaces", sa.Column("owner_user_id", sa.Uuid(), nullable=True))
    op.add_column("spaces", sa.Column("billing_email", sa.String(320), nullable=True))
    # Existing owner and billing values are populated by the resumable
    # production backfill before the new application version is started.
    op.create_foreign_key(
        op.f("fk_spaces_owner_user_id_users"),
        "spaces",
        "users",
        ["owner_user_id"],
        ["id"],
        ondelete="RESTRICT",
        postgresql_not_valid=True,
    )
    op.execute("ALTER TABLE spaces VALIDATE CONSTRAINT fk_spaces_owner_user_id_users")

    op.create_table(
        "plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("price_month_minor", sa.Integer(), nullable=True),
        sa.Column("price_year_minor", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("limits", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("features", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_public", sa.Boolean(), nullable=False),
        sa.Column("sort", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("code IN ('free', 'team', 'enterprise')", name="code_valid"),
        sa.CheckConstraint(
            "price_month_minor IS NULL OR price_month_minor >= 0", name="month_price_nonnegative"
        ),
        sa.CheckConstraint(
            "price_year_minor IS NULL OR price_year_minor >= 0", name="year_price_nonnegative"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index(op.f("ix_plans_code"), "plans", ["code"], unique=True)

    plans = sa.table(
        "plans",
        sa.column("id", sa.Uuid()),
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("price_month_minor", sa.Integer()),
        sa.column("price_year_minor", sa.Integer()),
        sa.column("currency", sa.String()),
        sa.column("limits", postgresql.JSONB()),
        sa.column("features", postgresql.JSONB()),
        sa.column("is_public", sa.Boolean()),
        sa.column("sort", sa.Integer()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    now = datetime.now(UTC)
    op.bulk_insert(
        plans,
        [
            {
                "id": UUID("00000000-0000-0000-0000-000000000001"),
                "code": "free",
                "name": "Free",
                "price_month_minor": 0,
                "price_year_minor": 0,
                "currency": "USD",
                "limits": {
                    "members": 3,
                    "teams": 1,
                    "boards": 2,
                    "pages": 5,
                    "tasks": 300,
                    "storage_bytes": 209715200,
                    "public_api_requests_per_minute": 100,
                    "api_tokens": 5,
                },
                "features": {
                    "public_api_read": True,
                    "public_api_write": False,
                    "history_days": 7,
                    "audit_log": False,
                    "guest_roles": False,
                },
                "is_public": True,
                "sort": 10,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": UUID("00000000-0000-0000-0000-000000000002"),
                "code": "team",
                "name": "Team",
                "price_month_minor": None,
                "price_year_minor": None,
                "currency": "USD",
                "limits": {
                    "members": "seats",
                    "teams": None,
                    "boards": None,
                    "pages": None,
                    "tasks_soft": 50000,
                    "storage_base_bytes": 5368709120,
                    "storage_per_seat_bytes": 1073741824,
                    "public_api_requests_per_minute": 600,
                    "api_tokens": 50,
                },
                "features": {
                    "public_api_read": True,
                    "public_api_write": True,
                    "history_days": 90,
                    "audit_log": True,
                    "guest_roles": True,
                },
                "is_public": True,
                "sort": 20,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": UUID("00000000-0000-0000-0000-000000000003"),
                "code": "enterprise",
                "name": "Enterprise",
                "price_month_minor": None,
                "price_year_minor": None,
                "currency": "USD",
                "limits": {
                    "members": None,
                    "teams": None,
                    "boards": None,
                    "pages": None,
                    "tasks": None,
                    "storage_bytes": None,
                    "public_api_requests_per_minute": None,
                },
                "features": {
                    "public_api_read": True,
                    "public_api_write": True,
                    "history_days": None,
                    "audit_log": True,
                    "guest_roles": True,
                    "sso": True,
                    "scim": True,
                    "byok": True,
                },
                "is_public": True,
                "sort": 30,
                "created_at": now,
                "updated_at": now,
            },
        ],
    )

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("seats", sa.Integer(), nullable=False),
        sa.Column("seats_used", sa.Integer(), nullable=False),
        sa.Column("current_period_start", sa.DateTime(timezone=True)),
        sa.Column("current_period_end", sa.DateTime(timezone=True)),
        sa.Column("trial_end", sa.DateTime(timezone=True)),
        sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False),
        sa.Column("provider", sa.String(32)),
        sa.Column("provider_customer_id", sa.String(255)),
        sa.Column("provider_subscription_id", sa.String(255)),
        sa.Column("grace_until", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('trialing', 'active', 'past_due', 'paused', 'canceled', 'read_only')",
            name="status_valid",
        ),
        sa.CheckConstraint("seats >= 0 AND seats_used >= 0", name="seats_nonnegative"),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("space_id"),
        sa.UniqueConstraint(
            "provider", "provider_subscription_id", name="uq_subscriptions_provider_external_id"
        ),
    )
    for column in (
        "space_id",
        "plan_id",
        "status",
        "current_period_end",
        "trial_end",
        "provider_customer_id",
        "grace_until",
    ):
        op.create_index(op.f(f"ix_subscriptions_{column}"), "subscriptions", [column])

    op.create_table(
        "billing_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("event_id", sa.String(255), nullable=False),
        sa.Column("type", sa.String(120), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id"),
    )
    op.create_index(op.f("ix_billing_events_type"), "billing_events", ["type"])
    op.create_index(op.f("ix_billing_events_processed_at"), "billing_events", ["processed_at"])

    op.create_table(
        "invoices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("subscription_id", sa.Uuid(), nullable=False),
        sa.Column("provider_invoice_id", sa.String(255), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True)),
        sa.Column("period_end", sa.DateTime(timezone=True)),
        sa.Column("hosted_url", sa.String(2048)),
        sa.Column("pdf_url", sa.String(2048)),
        sa.ForeignKeyConstraint(["subscription_id"], ["subscriptions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_invoice_id"),
    )
    op.create_index(op.f("ix_invoices_subscription_id"), "invoices", ["subscription_id"])
    op.create_index(op.f("ix_invoices_status"), "invoices", ["status"])

    op.create_table(
        "usage_snapshots",
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("metric", sa.String(64), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("space_id", "metric", "measured_at"),
    )


def downgrade() -> None:
    op.drop_table("usage_snapshots")
    op.drop_table("invoices")
    op.drop_table("billing_events")
    op.drop_table("subscriptions")
    op.drop_table("plans")
    op.drop_constraint(op.f("fk_spaces_owner_user_id_users"), "spaces", type_="foreignkey")
    op.drop_column("spaces", "billing_email")
    op.drop_column("spaces", "owner_user_id")
