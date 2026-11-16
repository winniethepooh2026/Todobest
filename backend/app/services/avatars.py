from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TypeGuard
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.db.session import async_session_factory
from app.models import User
from app.services.antivirus import scan_avatar_bytes
from app.services.avatar_processing import (
    InvalidAvatarError,
    avatar_source_hash,
    download_google_avatar,
    process_avatar,
    validate_google_picture_url,
)
from app.services.object_storage import (
    AvatarStorageError,
    avatar_media_url,
    delete_avatar,
    store_avatar,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AvatarImportResult:
    status: str
    uploaded: bool = False


@dataclass(frozen=True, slots=True)
class GoogleAvatarImportRequest:
    generation: int
    picture_url: str | None
    source_hash: str | None
    should_enqueue: bool


def user_avatar_url(user: User) -> str | None:
    return avatar_media_url(user.id, user.avatar_object_key, user.avatar_content_hash)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def avatar_import_is_due(
    source_hash: str,
    stored_source_hash: str | None,
    synced_at: datetime | None,
    *,
    now: datetime | None = None,
) -> bool:
    if source_hash != stored_source_hash or synced_at is None:
        return True
    threshold = (now or datetime.now(UTC)) - timedelta(days=settings.avatar_refresh_days)
    return _as_utc(synced_at) <= threshold


def plan_google_avatar_import(
    user: User,
    picture_url: str | None,
) -> GoogleAvatarImportRequest:
    """Invalidate older imports and persist the latest Google avatar intent."""

    generation = int(getattr(user, "avatar_import_generation", 0) or 0) + 1
    user.avatar_import_generation = generation
    validated_url = validate_google_picture_url(picture_url)
    if validated_url is None:
        user.avatar_requested_source_hash = None
        return GoogleAvatarImportRequest(
            generation=generation,
            picture_url=None,
            source_hash=None,
            should_enqueue=False,
        )

    source_hash = avatar_source_hash(validated_url)
    user.avatar_requested_source_hash = source_hash
    return GoogleAvatarImportRequest(
        generation=generation,
        picture_url=validated_url,
        source_hash=source_hash,
        should_enqueue=avatar_import_is_due(
            source_hash,
            getattr(user, "avatar_source_url_hash", None),
            getattr(user, "avatar_synced_at", None),
        ),
    )


def _avatar_request_is_current(
    user: User,
    generation: int,
    source_hash: str,
) -> bool:
    return (
        user.avatar_import_generation == generation
        and user.avatar_requested_source_hash == source_hash
    )


def _avatar_user_is_available(user: User | None) -> TypeGuard[User]:
    return user is not None and user.google_sub is not None and user.is_active


async def import_google_avatar(
    user_id: UUID,
    picture_url: str,
    generation: int,
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> AvatarImportResult:
    """Fetch, scan, normalize, rescan and only then persist a Google avatar."""

    if not settings.avatar_storage_enabled:
        return AvatarImportResult(status="storage_disabled")
    if not isinstance(generation, int) or isinstance(generation, bool) or generation <= 0:
        return AvatarImportResult(status="stale")
    picture_url = validate_google_picture_url(picture_url)
    if picture_url is None:
        raise InvalidAvatarError("Google profile picture URL is missing")
    source_hash = avatar_source_hash(picture_url)
    import_session_factory = (
        session_factory if session_factory is not None else async_session_factory
    )

    async with import_session_factory() as db:
        user = await db.get(User, user_id)
        if not _avatar_user_is_available(user):
            return AvatarImportResult(status="user_unavailable")
        if not _avatar_request_is_current(user, generation, source_hash):
            return AvatarImportResult(status="stale")
        if not avatar_import_is_due(
            source_hash,
            user.avatar_source_url_hash,
            user.avatar_synced_at,
        ):
            return AvatarImportResult(status="fresh")

    raw = await download_google_avatar(picture_url)
    await asyncio.to_thread(scan_avatar_bytes, raw)
    processed = await asyncio.to_thread(process_avatar, raw)
    # This second scan covers the exact byte sequence sent by store_avatar.
    await asyncio.to_thread(scan_avatar_bytes, processed.data)

    now = datetime.now(UTC)
    async with import_session_factory() as db:
        user = await db.scalar(select(User).where(User.id == user_id).with_for_update())
        if not _avatar_user_is_available(user):
            return AvatarImportResult(status="user_unavailable")
        if not _avatar_request_is_current(user, generation, source_hash):
            return AvatarImportResult(status="stale")
        if user.avatar_content_hash == processed.content_hash:
            user.avatar_source_url_hash = source_hash
            user.avatar_synced_at = now
            await db.commit()
            return AvatarImportResult(status="unchanged")
        # Never hold the user row lock during a paid, remote S3 PUT.
        await db.rollback()

    new_key = await asyncio.to_thread(store_avatar, user_id, processed)
    old_key: str | None = None
    async with import_session_factory() as db:
        user = await db.scalar(select(User).where(User.id == user_id).with_for_update())
        if not _avatar_user_is_available(user):
            # The PUT may already be referenced by an ambiguously committed or
            # concurrent transaction. The grace-period reconciler owns cleanup.
            return AvatarImportResult(status="user_unavailable")
        if not _avatar_request_is_current(user, generation, source_hash):
            return AvatarImportResult(status="stale")

        if user.avatar_content_hash == processed.content_hash:
            user.avatar_source_url_hash = source_hash
            user.avatar_synced_at = now
            await db.commit()
            return AvatarImportResult(status="unchanged")

        old_key = user.avatar_object_key
        user.avatar_object_key = new_key
        user.avatar_content_hash = processed.content_hash
        user.avatar_source_url_hash = source_hash
        user.avatar_synced_at = now
        # If this raises after PostgreSQL committed, deleting new_key would
        # corrupt the committed avatar. Leave it to the idempotent retry or the
        # 24-hour orphan reconciler instead.
        await db.commit()

    if old_key is not None and old_key != new_key:
        try:
            await asyncio.to_thread(delete_avatar, old_key)
        except AvatarStorageError:
            # Do not retry the whole import (and perform another paid PUT). The
            # orphan reconciler deletes this version after its grace period.
            logger.exception("Could not delete previous avatar object for user %s", user_id)
    return AvatarImportResult(status="updated", uploaded=True)
