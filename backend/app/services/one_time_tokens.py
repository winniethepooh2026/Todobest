from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OneTimeToken


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


async def issue_one_time_token(
    db: AsyncSession, *, user_id: UUID, purpose: str, ttl: timedelta
) -> tuple[OneTimeToken, str]:
    now = datetime.now(UTC)
    await db.execute(
        update(OneTimeToken)
        .where(
            OneTimeToken.user_id == user_id,
            OneTimeToken.purpose == purpose,
            OneTimeToken.consumed_at.is_(None),
        )
        .values(consumed_at=now)
    )
    raw = secrets.token_urlsafe(32)
    record = OneTimeToken(
        user_id=user_id,
        purpose=purpose,
        token_hash=hash_token(raw),
        expires_at=now + ttl,
    )
    db.add(record)
    await db.flush()
    return record, raw
