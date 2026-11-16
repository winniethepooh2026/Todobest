from __future__ import annotations

import asyncio
from logging.config import fileConfig

import sqlalchemy as sa
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.core.config import settings
from app.db.options import postgres_connect_args
from app.models import Base

config = context.config
# Alembic stores this value in ConfigParser, where literal percent signs in
# URL-encoded credentials must be escaped. SQLAlchemy receives the original
# single-percent URL after ConfigParser interpolation.
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
MIGRATION_ADVISORY_LOCK_ID = 0x4E4F4B49


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    is_postgresql = connection.dialect.name == "postgresql"
    if is_postgresql:
        # A session lock survives the commits required by CREATE INDEX
        # CONCURRENTLY. A short DDL lock timeout fails the deploy instead of
        # queueing application writes behind a migration.
        connection.execute(sa.text("SET lock_timeout = '5s'"))
        acquired = connection.execute(
            sa.text("SELECT pg_try_advisory_lock(:lock_id)"),
            {"lock_id": MIGRATION_ADVISORY_LOCK_ID},
        ).scalar_one()
        if not acquired:
            raise RuntimeError("Another Noki migration is already running")
        connection.commit()
    try:
        with context.begin_transaction():
            context.run_migrations()
    finally:
        if is_postgresql:
            connection.execute(
                sa.text("SELECT pg_advisory_unlock(:lock_id)"),
                {"lock_id": MIGRATION_ADVISORY_LOCK_ID},
            )
            connection.commit()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        # API request timeouts are intentionally not applied to schema/data
        # migrations. The transaction-level lock timeout above still prevents
        # an indefinitely blocked deployment.
        connect_args=postgres_connect_args("noki-migration", disable_timeouts=True),
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
