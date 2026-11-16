from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession, RedisClient, enforce_rate_limit
from app.core.config import settings
from app.models import SpaceMember, User
from app.services.object_storage import (
    AVATAR_CACHE_CONTROL,
    AvatarObjectNotFoundError,
    AvatarStorageError,
    avatar_object_key,
    open_avatar,
)

router = APIRouter(prefix="/media/avatars", tags=["Avatars"])


def _stream_avatar(body: Any) -> Iterator[bytes]:
    try:
        while chunk := body.read(64 * 1024):
            yield chunk
    finally:
        body.close()


def _if_none_match_matches(header_value: str, content_hash: str) -> bool:
    """Apply RFC weak comparison to a possibly comma-separated entity-tag list."""

    position = 0
    value_length = len(header_value)
    while position < value_length:
        while position < value_length and header_value[position] in " \t":
            position += 1
        if position >= value_length:
            return False

        token_start = position
        if header_value[position] == "*":
            position += 1
            while position < value_length and header_value[position] in " \t":
                position += 1
            if position == value_length or header_value[position] == ",":
                return True
        else:
            if header_value.startswith("W/", position):
                position += 2
            if position < value_length and header_value[position] == '"':
                position += 1
                closing_quote = header_value.find('"', position)
                if closing_quote < 0:
                    return False
                candidate = header_value[position:closing_quote]
                position = closing_quote + 1
                while position < value_length and header_value[position] in " \t":
                    position += 1
                if position == value_length or header_value[position] == ",":
                    if candidate == content_hash:
                        return True
                    if position == value_length:
                        return False
                    position += 1
                    continue

        next_separator = header_value.find(",", token_start)
        if next_separator < 0:
            return False
        position = next_separator + 1

    return False


async def _can_view_avatar(db: DBSession, viewer_id: UUID, target_id: UUID) -> bool:
    if viewer_id == target_id:
        return True
    viewer_space_ids = select(SpaceMember.space_id).where(SpaceMember.user_id == viewer_id)
    shared_space_id = await db.scalar(
        select(SpaceMember.space_id)
        .where(
            SpaceMember.user_id == target_id,
            SpaceMember.space_id.in_(viewer_space_ids),
        )
        .limit(1)
    )
    return shared_space_id is not None


@router.get("/{user_id}/{content_hash}.webp", response_model=None)
async def get_avatar(
    user_id: UUID,
    content_hash: Annotated[str, Path(pattern=r"^[0-9a-f]{64}$")],
    request: Request,
    current_user: CurrentUser,
    db: DBSession,
    redis: RedisClient,
) -> Response:
    await enforce_rate_limit(
        redis,
        scope="avatar-read-user",
        identifier=str(current_user.id),
        limit=settings.avatar_read_rate_limit_attempts,
        window_seconds=settings.avatar_read_rate_limit_window_seconds,
    )
    if not settings.avatar_storage_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Avatar not found")

    avatar = (
        await db.execute(
            select(User.avatar_object_key, User.avatar_content_hash).where(User.id == user_id)
        )
    ).one_or_none()
    if (
        avatar is None
        or avatar.avatar_object_key != avatar_object_key(user_id, content_hash)
        or avatar.avatar_content_hash != content_hash
        or not await _can_view_avatar(db, current_user.id, user_id)
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Avatar not found")

    etag = f'"{content_hash}"'
    headers = {
        "Cache-Control": AVATAR_CACHE_CONTROL,
        "ETag": etag,
        "X-Content-Type-Options": "nosniff",
        "Cross-Origin-Resource-Policy": "same-origin",
    }
    if_none_match = ",".join(request.headers.getlist("If-None-Match"))
    if _if_none_match_matches(if_none_match, content_hash):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)

    try:
        opened = await asyncio.to_thread(
            open_avatar,
            avatar.avatar_object_key,
            content_hash,
        )
    except AvatarObjectNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Avatar not found") from exc
    except AvatarStorageError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Avatar is temporarily unavailable",
            headers={"Retry-After": "5"},
        ) from exc

    headers["Content-Length"] = str(opened.size_bytes)
    return StreamingResponse(
        _stream_avatar(opened.body),
        media_type="image/webp",
        headers=headers,
    )
