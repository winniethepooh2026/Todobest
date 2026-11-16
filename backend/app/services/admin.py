from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User

logger = logging.getLogger("noki.admin")


async def set_platform_admin(db: AsyncSession, user: User, *, is_admin: bool) -> None:
    user.is_platform_admin = is_admin
    await db.commit()
    logger.info(
        "platform_admin_changed user_id=%s email=%s is_admin=%s",
        user.id,
        user.email,
        is_admin,
    )
