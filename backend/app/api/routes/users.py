from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response, status
from jwt import InvalidTokenError
from sqlalchemy import delete, select, update

from app.api.deps import (
    CSRF,
    CurrentUser,
    DBSession,
    RedisClient,
    client_rate_limit_id,
    enforce_rate_limit,
)
from app.core.config import settings
from app.core.security import (
    GOOGLE_REAUTH_COOKIE_NAME,
    PasswordWorkCapacityError,
    clear_auth_cookies,
    clear_google_reauth_cookie,
    decode_token,
    hash_password_async,
    verify_password_async,
)
from app.models import ApiToken, User, UserSession
from app.schemas import (
    ChangePasswordRequest,
    Message,
    UpdateProfileRequest,
    UserOut,
)
from app.schemas.lifecycle import AccountDeleteRequest
from app.services.auth import user_to_schema

router = APIRouter(prefix="/users", tags=["Users"])


def _password_capacity_exceeded(exc: PasswordWorkCapacityError) -> HTTPException:
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        "Password verification is busy; try again shortly",
        headers={"Retry-After": str(max(1, int(settings.password_work_queue_timeout_seconds)))},
    )


@router.get("/me", response_model=UserOut)
async def get_me(current_user: CurrentUser) -> UserOut:
    return user_to_schema(current_user)


@router.patch("/me", response_model=UserOut)
async def update_me(
    payload: UpdateProfileRequest,
    current_user: CurrentUser,
    db: DBSession,
    _: CSRF,
) -> UserOut:
    if payload.name is not None:
        current_user.name = payload.name
    if payload.bio is not None:
        current_user.bio = payload.bio
    if payload.timezone is not None:
        current_user.timezone = payload.timezone
    await db.commit()
    return user_to_schema(current_user)


@router.post("/me/change-password", response_model=Message)
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    response: Response,
    current_user: CurrentUser,
    db: DBSession,
    redis: RedisClient,
    _: CSRF,
) -> Message:
    await enforce_rate_limit(
        redis,
        scope="password-change-user",
        identifier=str(current_user.id),
        limit=settings.password_change_rate_limit_attempts,
        window_seconds=settings.password_change_rate_limit_window_seconds,
    )
    await enforce_rate_limit(
        redis,
        scope="password-change-ip",
        identifier=client_rate_limit_id(request),
        limit=settings.password_change_rate_limit_attempts * 4,
        window_seconds=settings.password_change_rate_limit_window_seconds,
    )
    user = await db.scalar(
        select(User)
        .where(User.id == current_user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User is unavailable")

    google_reauth = False
    google_reauth_token = request.cookies.get(GOOGLE_REAUTH_COOKIE_NAME)
    if google_reauth_token:
        try:
            google_reauth_payload = decode_token(google_reauth_token, "google_reauth")
            google_reauth = (
                google_reauth_payload["sub"] == str(user.id)
                and google_reauth_payload["ver"] == user.auth_version
            )
        except (InvalidTokenError, KeyError, TypeError):
            google_reauth = False

    if user.password_hash is None and not google_reauth:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Password setup for Google-only accounts requires verified reauthentication",
        )

    if user.password_hash is not None:
        try:
            old_password_valid = (
                await verify_password_async(payload.old_password, user.password_hash)
                if payload.old_password
                else False
            )
        except PasswordWorkCapacityError as exc:
            raise _password_capacity_exceeded(exc) from exc
        if not payload.old_password or not old_password_valid:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Old password is incorrect")

    try:
        user.password_hash = await hash_password_async(payload.new_password)
    except PasswordWorkCapacityError as exc:
        raise _password_capacity_exceeded(exc) from exc
    user.auth_version += 1
    now = datetime.now(UTC)
    await db.execute(
        update(UserSession)
        .where(
            UserSession.user_id == user.id,
            UserSession.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    await db.commit()
    clear_google_reauth_cookie(response)
    clear_auth_cookies(response)
    return Message(message="Password changed")


@router.delete("/me", response_model=Message)
async def delete_account(
    payload: AccountDeleteRequest,
    response: Response,
    current_user: CurrentUser,
    db: DBSession,
    _: CSRF,
) -> Message:
    if payload.email.strip().lower() != current_user.email:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Email does not match")
    user = await db.scalar(select(User).where(User.id == current_user.id).with_for_update())
    if user is None or user.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    now = datetime.now(UTC)
    user.email = f"deleted+{user.id}@invalid.noki"
    user.name = "Deleted user"
    user.bio = None
    user.password_hash = None
    user.google_sub = None
    user.totp_secret = None
    user.totp_pending_secret = None
    user.totp_pending_created_at = None
    user.totp_recovery_hashes = None
    user.totp_last_counter = -1
    user.avatar_object_key = None
    user.avatar_content_hash = None
    user.avatar_source_url_hash = None
    user.avatar_requested_source_hash = None
    user.is_active = False
    user.deleted_at = now
    user.auth_version += 1
    await db.execute(delete(UserSession).where(UserSession.user_id == user.id))
    await db.execute(delete(ApiToken).where(ApiToken.user_id == user.id))
    await db.commit()
    clear_google_reauth_cookie(response)
    clear_auth_cookies(response)
    return Message(message="Account deleted and personal profile anonymized")
