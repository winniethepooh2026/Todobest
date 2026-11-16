from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.options import postgres_connect_args

engine_options: dict[str, object] = {
    "pool_pre_ping": True,
    "pool_recycle": 1800,
    "hide_parameters": True,
}
if make_url(settings.database_url).drivername == "postgresql+asyncpg":
    engine_options.update(
        {
            "pool_size": settings.db_pool_size,
            "max_overflow": settings.db_max_overflow,
            "pool_timeout": settings.db_pool_timeout,
            "pool_use_lifo": True,
            "connect_args": postgres_connect_args("noki-api"),
        }
    )

engine = create_async_engine(
    settings.database_url,
    **engine_options,
)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session


async def dispose_engine() -> None:
    await engine.dispose()
