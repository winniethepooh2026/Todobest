from __future__ import annotations

import asyncio
import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Cookie, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from jwt import InvalidTokenError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.api.deps import (
    CSRF,
    AuthCSRF,
    CurrentUser,
    DBSession,
    RedisClient,
    clear_rate_limit,
    client_rate_limit_id,
    enforce_mail_recipient_rate_limit,
    enforce_rate_limit,
    safe_compare_ascii,
)
from app.core.config import settings
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    MFA_PENDING_COOKIE_NAME,
    PasswordWorkCapacityError,
    clear_auth_cookies,
    clear_google_reauth_cookie,
    clear_mfa_pending_cookie,
    clear_oauth_state_cookie,
    create_google_reauth_token,
    create_mfa_pending_token,
    decode_token,
    hash_password_async,
    password_needs_rehash,
    set_auth_cookies,
    set_google_reauth_cookie,
    set_mfa_pending_cookie,
    set_oauth_state_cookie,
    verify_password_async,
)
from app.models import OneTimeToken, User, UserSession
from app.schemas import (
    AuthResponse,
    EmailRequest,
    LoginRequest,
    Message,
    RegisterRequest,
    ResetPasswordRequest,
    SessionOut,
    TokenRequest,
    TotpCodeRequest,
    TotpConfirmOut,
    TotpSetupOut,
    TotpSetupRequest,
)
from app.services.auth import issue_tokens, user_to_schema
from app.services.avatars import plan_google_avatar_import
from app.services.invitations import accept_matching_invitations
from app.services.mail import enqueue_mail, send_mail
from app.services.mfa import (
    check_totp,
    create_recovery_codes,
    create_totp_secret,
    seal_secret,
    totp_uri,
    verify_second_factor,
)
from app.services.oauth import (
    GoogleOAuthError,
    GoogleOAuthUnavailableError,
    build_google_authorization_url,
    fetch_google_identity,
)
from app.services.one_time_tokens import hash_token, issue_one_time_token

router = APIRouter(prefix="/auth", tags=["Auth"])
logger = logging.getLogger(__name__)


def _session_device(request: Request) -> dict[str, str | None]:
    # Do not trust arbitrary proxy headers; Uvicorn exposes the trusted client IP.
    raw_agent = request.headers.get("user-agent", "")
    agent = "".join(char for char in raw_agent[:512] if char.isprintable()).strip()
    address = client_rate_limit_id(request)
    return {
        "user_agent": agent or None,
        "ip_address": address[:45] if address != "unknown" else None,
    }


def _current_session_id(request: Request, user_id: UUID) -> UUID | None:
    refresh_token = request.cookies.get(settings.refresh_cookie_name)
    if not refresh_token:
        return None
    try:
        payload = decode_token(refresh_token, "refresh")
        if UUID(payload["sub"]) == user_id:
            return UUID(payload["sid"])
    except (InvalidTokenError, KeyError, TypeError, ValueError):
        pass
    return None


def _oauth_error_redirect(path: str, error: str) -> RedirectResponse:
    """Return OAuth failures to the UI instead of exposing an API JSON page."""
    separator = "&" if "?" in path else "?"
    redirect = RedirectResponse(
        f"{settings.frontend_url}{path}{separator}oauth_error={error}",
        status_code=status.HTTP_302_FOUND,
    )
    clear_oauth_state_cookie(redirect)
    return redirect


def _password_capacity_exceeded(exc: PasswordWorkCapacityError) -> HTTPException:
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        "Password verification is busy; try again shortly",
        headers={"Retry-After": str(max(1, int(settings.password_work_queue_timeout_seconds)))},
    )


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    db: DBSession,
    redis: RedisClient,
) -> AuthResponse:
    if not settings.public_registration_enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Public registration is disabled")

    existing = await db.scalar(select(User).where(User.email == payload.email).with_for_update())
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")

    try:
        password_hash = await hash_password_async(payload.password)
    except PasswordWorkCapacityError as exc:
        raise _password_capacity_exceeded(exc) from exc
    accepted_at = datetime.now(UTC)
    user = User(
        email=payload.email,
        name=payload.name,
        password_hash=password_hash,
        terms_accepted_at=accepted_at,
        privacy_accepted_at=accepted_at,
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "An account with this email already exists",
        ) from exc

    # Count only valid, unique account creations. Trying addresses that are
    # already registered must not consume another person's registration quota.
    try:
        await enforce_rate_limit(
            redis,
            scope="register",
            identifier=client_rate_limit_id(request),
            limit=settings.register_rate_limit_attempts,
            window_seconds=settings.register_rate_limit_window_seconds,
        )
    except HTTPException:
        await db.rollback()
        raise

    tokens = await issue_tokens(db, user, **_session_device(request))
    await accept_matching_invitations(db, user)
    await db.commit()
    set_auth_cookies(
        response,
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        csrf_token=tokens.csrf_token,
    )
    return AuthResponse(user=user_to_schema(user))


@router.post("/send-verification-email", response_model=Message)
async def send_verification_email(
    current_user: CurrentUser,
    db: DBSession,
    redis: RedisClient,
    _: CSRF,
) -> Message:
    if current_user.email_verified_at is not None:
        return Message(message="Email is already verified")
    if not settings.resend_api_key.get_secret_value():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Email delivery is unavailable",
        )

    await enforce_mail_recipient_rate_limit(
        redis,
        recipient=current_user.email,
        purpose="email-verification",
        silent=False,
    )
    record, raw_token = await issue_one_time_token(
        db,
        user_id=current_user.id,
        purpose="verify_email",
        ttl=timedelta(hours=settings.email_verification_ttl_hours),
    )
    await db.commit()
    try:
        await asyncio.to_thread(
            send_mail,
            recipient=current_user.email,
            kind="verify_email",
            context={
                "name": current_user.name,
                "action_url": f"{settings.frontend_url}/verify-email?token={raw_token}",
            },
            idempotency_key=f"verify-email/{record.id}",
        )
    except Exception as exc:
        logger.exception(
            "verification_mail_failed user_id=%s token_id=%s",
            current_user.id,
            record.id,
        )
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Verification email could not be sent; try again later",
        ) from exc
    return Message(message="Verification email sent")


@router.post("/verify-email", response_model=AuthResponse | Message)
async def verify_email(
    payload: TokenRequest, response: Response, db: DBSession
) -> AuthResponse | Message:
    now = datetime.now(UTC)
    token = await db.scalar(
        select(OneTimeToken)
        .where(
            OneTimeToken.token_hash == hash_token(payload.token),
            OneTimeToken.purpose == "verify_email",
            OneTimeToken.consumed_at.is_(None),
            OneTimeToken.expires_at > now,
        )
        .with_for_update()
    )
    if token is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Verification link is invalid or expired")
    user = await db.scalar(select(User).where(User.id == token.user_id).with_for_update())
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Verification link is invalid or expired")
    token.consumed_at = now
    user.email_verified_at = user.email_verified_at or now
    await accept_matching_invitations(db, user)
    if user.totp_secret:
        await db.commit()
        return Message(message="Email verified; sign in with your second factor")
    tokens = await issue_tokens(db, user)
    await db.commit()
    set_auth_cookies(
        response,
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        csrf_token=tokens.csrf_token,
    )
    return AuthResponse(user=user_to_schema(user))


@router.post("/forgot-password", response_model=Message)
async def forgot_password(
    payload: EmailRequest, request: Request, db: DBSession, redis: RedisClient
) -> Message:
    await enforce_rate_limit(
        redis,
        scope="password-reset-ip",
        identifier=client_rate_limit_id(request),
        limit=settings.password_change_rate_limit_attempts,
        window_seconds=settings.password_change_rate_limit_window_seconds,
    )
    if not settings.resend_api_key.get_secret_value():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Password reset email is temporarily unavailable",
        )
    await enforce_mail_recipient_rate_limit(
        redis,
        recipient=payload.email,
        purpose="password-reset",
        silent=False,
    )
    user = await db.scalar(select(User).where(User.email == payload.email).with_for_update())
    if user is not None and user.is_active:
        record, raw_token = await issue_one_time_token(
            db,
            user_id=user.id,
            purpose="reset_password",
            ttl=timedelta(minutes=settings.password_reset_ttl_minutes),
        )
        await db.commit()
        try:
            await asyncio.to_thread(
                send_mail,
                recipient=user.email,
                kind="reset_password",
                context={
                    "name": user.name,
                    "action_url": f"{settings.frontend_url}/reset-password?token={raw_token}",
                },
                idempotency_key=f"reset-password/{record.id}",
            )
        except Exception as exc:
            logger.exception(
                "password_reset_mail_failed user_id=%s token_id=%s",
                user.id,
                record.id,
            )
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Password reset email is temporarily unavailable",
            ) from exc
        logger.info(
            "password_reset_mail_sent user_id=%s token_id=%s",
            user.id,
            record.id,
        )
    else:
        await db.rollback()
        logger.info("password_reset_mail_skipped reason=account_unavailable")
    return Message(message="If the account exists, a password reset email was sent")


@router.post("/reset-password", response_model=Message)
async def reset_password(
    payload: ResetPasswordRequest, response: Response, db: DBSession
) -> Message:
    now = datetime.now(UTC)
    token = await db.scalar(
        select(OneTimeToken)
        .where(
            OneTimeToken.token_hash == hash_token(payload.token),
            OneTimeToken.purpose == "reset_password",
            OneTimeToken.consumed_at.is_(None),
            OneTimeToken.expires_at > now,
        )
        .with_for_update()
    )
    if token is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Reset link is invalid or expired")
    user = await db.scalar(select(User).where(User.id == token.user_id).with_for_update())
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Reset link is invalid or expired")
    try:
        user.password_hash = await hash_password_async(payload.new_password)
    except PasswordWorkCapacityError as exc:
        raise _password_capacity_exceeded(exc) from exc
    token.consumed_at = now
    user.auth_version += 1
    await db.execute(
        update(UserSession)
        .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    await db.commit()
    clear_auth_cookies(response)
    return Message(message="Password changed; sign in again")


@router.post("/login", response_model=AuthResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: DBSession,
    redis: RedisClient,
) -> AuthResponse:
    client_id = client_rate_limit_id(request)
    ip_limit = settings.login_rate_limit_attempts * 5
    await enforce_rate_limit(
        redis,
        scope="login-ip",
        identifier=client_id,
        limit=ip_limit,
        window_seconds=settings.login_rate_limit_window_seconds,
    )
    # Count every attempt for the normalized account identifier before doing
    # expensive password work. This closes distributed brute-force attacks and
    # prevents a burst from racing past a post-verification failure counter.
    await enforce_rate_limit(
        redis,
        scope="login-account",
        identifier=str(payload.email),
        limit=settings.login_rate_limit_attempts,
        window_seconds=settings.login_rate_limit_window_seconds,
    )

    user = await db.scalar(select(User).where(User.email == payload.email))
    user_id = user.id if user is not None else None
    stored_password_hash = user.password_hash if user is not None else None
    password_hash = (
        stored_password_hash if stored_password_hash is not None else DUMMY_PASSWORD_HASH
    )
    # Release the connection before entering the bounded Argon2 queue. A burst
    # must not consume the SQL pool while waiting for CPU/memory capacity.
    await db.rollback()
    try:
        password_valid = await verify_password_async(payload.password, password_hash)
    except PasswordWorkCapacityError as exc:
        raise _password_capacity_exceeded(exc) from exc
    if user_id is None or stored_password_hash is None or not password_valid:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")

    user = await db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None or user.password_hash is None or user.password_hash != stored_password_hash:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is disabled")
    if user.totp_secret:
        if not payload.mfa_code:
            raise HTTPException(status.HTTP_428_PRECONDITION_REQUIRED, "Second factor required")
        if not verify_second_factor(user, payload.mfa_code):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid second factor")

    await clear_rate_limit(
        redis,
        scope="login-account",
        identifier=str(payload.email),
    )

    if password_needs_rehash(user.password_hash):
        try:
            user.password_hash = await hash_password_async(payload.password)
        except PasswordWorkCapacityError as exc:
            raise _password_capacity_exceeded(exc) from exc

    tokens = await issue_tokens(db, user, **_session_device(request))
    await accept_matching_invitations(db, user)
    await db.commit()
    set_auth_cookies(
        response,
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        csrf_token=tokens.csrf_token,
    )
    if await enforce_mail_recipient_rate_limit(
        redis,
        recipient=user.email,
        purpose="new-login",
        silent=True,
    ):
        enqueue_mail(
            recipient=user.email,
            kind="new_login",
            context={
                "name": user.name,
                "when": datetime.now(UTC).isoformat(),
                "ip": client_rate_limit_id(request),
                "device": _session_device(request)["user_agent"] or "Неизвестное устройство",
                "action_url": f"{settings.frontend_url}/app/settings",
            },
            idempotency_key=f"new-login/{tokens.refresh_jti}",
        )
    return AuthResponse(user=user_to_schema(user))


@router.post("/refresh", response_model=AuthResponse)
async def refresh_session(
    request: Request,
    response: Response,
    db: DBSession,
    redis: RedisClient,
    _: AuthCSRF,
    refresh_token: str | None = Cookie(default=None, alias=settings.refresh_cookie_name),
) -> AuthResponse:
    client_id = client_rate_limit_id(request)
    await enforce_rate_limit(
        redis,
        scope="refresh-ip",
        identifier=client_id,
        limit=settings.refresh_rate_limit_attempts * 2,
        window_seconds=settings.refresh_rate_limit_window_seconds,
    )
    await enforce_rate_limit(
        redis,
        scope="refresh-session",
        identifier=refresh_token or "missing",
        limit=settings.refresh_rate_limit_attempts,
        window_seconds=settings.refresh_rate_limit_window_seconds,
    )
    if not refresh_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token is missing")

    try:
        payload = decode_token(refresh_token, "refresh")
        jti = UUID(payload["jti"])
        session_id = UUID(payload["sid"])
        user_id = UUID(payload["sub"])
    except (InvalidTokenError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token") from exc

    user = await db.scalar(select(User).where(User.id == user_id).with_for_update())
    now = datetime.now(UTC)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User is unavailable")
    if payload["ver"] != user.auth_version:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token has been revoked")

    stored_session = await db.scalar(
        select(UserSession).where(UserSession.id == session_id).with_for_update()
    )
    if (
        stored_session is None
        or stored_session.revoked_at is not None
        or stored_session.expires_at <= now
        or stored_session.user_id != user_id
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh session is unavailable")

    if stored_session.refresh_jti != jti:
        # A valid but non-current token proves that this family was replayed.
        # Delete its sole row so the attacker's current branch can no longer
        # refresh. Its access token remains bounded by ACCESS_TOKEN_MINUTES.
        await db.delete(stored_session)
        await db.commit()
        clear_auth_cookies(response)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Refresh token reuse detected; sign in again",
        )

    tokens = await issue_tokens(db, user, session=stored_session)
    await db.commit()
    set_auth_cookies(
        response,
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        csrf_token=tokens.csrf_token,
    )
    return AuthResponse(user=user_to_schema(user))


@router.post("/totp/setup", response_model=TotpSetupOut)
async def setup_totp(
    payload: TotpSetupRequest,
    response: Response,
    current_user: CurrentUser,
    db: DBSession,
    redis: RedisClient,
    _: CSRF,
) -> TotpSetupOut:
    await enforce_rate_limit(
        redis,
        scope="totp-setup",
        identifier=str(current_user.id),
        limit=settings.password_change_rate_limit_attempts,
        window_seconds=settings.password_change_rate_limit_window_seconds,
    )
    user = await db.scalar(select(User).where(User.id == current_user.id).with_for_update())
    if user is None or user.totp_secret is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Second factor is already enabled")
    try:
        password_valid = user.password_hash is not None and await verify_password_async(
            payload.password, user.password_hash
        )
    except PasswordWorkCapacityError as exc:
        raise _password_capacity_exceeded(exc) from exc
    if not password_valid:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Current password is incorrect")
    secret = create_totp_secret()
    user.totp_pending_secret = seal_secret(user, secret)
    user.totp_pending_created_at = datetime.now(UTC)
    await db.commit()
    response.headers["Cache-Control"] = "no-store"
    return TotpSetupOut(secret=secret, otpauth_uri=totp_uri(user.email, secret))


@router.post("/totp/confirm", response_model=TotpConfirmOut)
async def confirm_totp(
    payload: TotpCodeRequest,
    request: Request,
    response: Response,
    current_user: CurrentUser,
    db: DBSession,
    redis: RedisClient,
    _: CSRF,
) -> TotpConfirmOut:
    await enforce_rate_limit(
        redis,
        scope="totp-confirm",
        identifier=str(current_user.id),
        limit=settings.login_rate_limit_attempts,
        window_seconds=settings.login_rate_limit_window_seconds,
    )
    user = await db.scalar(select(User).where(User.id == current_user.id).with_for_update())
    if (
        user is None
        or user.totp_secret is not None
        or not user.totp_pending_secret
        or user.totp_pending_created_at is None
        or user.totp_pending_created_at <= datetime.now(UTC) - timedelta(minutes=10)
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No pending second factor setup")
    user.totp_secret = user.totp_pending_secret
    user.totp_last_counter = -1
    if not check_totp(user, payload.code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid authentication code")
    codes, hashes = create_recovery_codes()
    user.totp_recovery_hashes = hashes
    user.totp_pending_secret = None
    user.totp_pending_created_at = None
    user.auth_version += 1
    await db.execute(
        update(UserSession)
        .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    tokens = await issue_tokens(db, user, **_session_device(request))
    await db.commit()
    set_auth_cookies(
        response,
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        csrf_token=tokens.csrf_token,
    )
    response.headers["Cache-Control"] = "no-store"
    return TotpConfirmOut(recovery_codes=codes)


@router.post("/totp/disable", response_model=Message)
async def disable_totp(
    payload: TotpCodeRequest,
    response: Response,
    current_user: CurrentUser,
    db: DBSession,
    redis: RedisClient,
    _: CSRF,
) -> Message:
    await enforce_rate_limit(
        redis,
        scope="totp-disable",
        identifier=str(current_user.id),
        limit=settings.login_rate_limit_attempts,
        window_seconds=settings.login_rate_limit_window_seconds,
    )
    user = await db.scalar(select(User).where(User.id == current_user.id).with_for_update())
    if user is None or not user.totp_secret:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Second factor is not enabled")
    if not verify_second_factor(user, payload.code):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid second factor")
    user.totp_secret = None
    user.totp_recovery_hashes = None
    user.totp_last_counter = -1
    user.auth_version += 1
    await db.execute(
        update(UserSession)
        .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    await db.commit()
    clear_auth_cookies(response)
    return Message(message="Second factor disabled; sign in again")


@router.post("/totp/complete-google", response_model=AuthResponse)
async def complete_google_totp(
    payload: TotpCodeRequest,
    request: Request,
    response: Response,
    db: DBSession,
    redis: RedisClient,
    pending: str | None = Cookie(default=None, alias=MFA_PENDING_COOKIE_NAME),
) -> AuthResponse:
    if not pending:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign-in challenge expired")
    try:
        claims = decode_token(pending, "mfa_pending")
        user_id = UUID(claims["sub"])
    except (InvalidTokenError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign-in challenge expired") from exc
    await enforce_rate_limit(
        redis,
        scope="totp-google",
        identifier=str(user_id),
        limit=settings.login_rate_limit_attempts,
        window_seconds=settings.login_rate_limit_window_seconds,
    )
    user = await db.scalar(select(User).where(User.id == user_id).with_for_update())
    if (
        user is None
        or not user.is_active
        or not user.totp_secret
        or user.auth_version != claims["ver"]
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign-in challenge expired")
    if not verify_second_factor(user, payload.code):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid second factor")
    google_sub = await redis.getdel(f"mfa:google:{claims['jti']}")
    if isinstance(google_sub, bytes):
        google_sub = google_sub.decode("utf-8")
    if not google_sub or user.google_sub not in {None, google_sub}:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign-in challenge expired")
    user.google_sub = google_sub
    await accept_matching_invitations(db, user)
    tokens = await issue_tokens(db, user, **_session_device(request))
    await db.commit()
    set_auth_cookies(
        response,
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        csrf_token=tokens.csrf_token,
    )
    clear_mfa_pending_cookie(response)
    if await enforce_mail_recipient_rate_limit(
        redis, recipient=user.email, purpose="new-login", silent=True
    ):
        enqueue_mail(
            recipient=user.email,
            kind="new_login",
            context={
                "name": user.name,
                "when": datetime.now(UTC).isoformat(),
                "ip": client_rate_limit_id(request),
                "device": _session_device(request)["user_agent"] or "Неизвестное устройство",
                "action_url": f"{settings.frontend_url}/app/settings",
            },
            idempotency_key=f"new-login/{tokens.refresh_jti}",
        )
    return AuthResponse(user=user_to_schema(user))


@router.get("/sessions", response_model=list[SessionOut])
async def list_sessions(
    request: Request, current_user: CurrentUser, db: DBSession
) -> list[SessionOut]:
    now = datetime.now(UTC)
    current_id = _current_session_id(request, current_user.id)
    rows = (
        await db.scalars(
            select(UserSession)
            .where(
                UserSession.user_id == current_user.id,
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > now,
            )
            .order_by(UserSession.created_at.desc())
        )
    ).all()
    return [
        SessionOut(
            id=row.id,
            user_agent=row.user_agent,
            ip_address=row.ip_address,
            created_at=row.created_at,
            last_seen_at=row.last_seen_at,
            expires_at=row.expires_at,
            current=row.id == current_id,
        )
        for row in rows
    ]


@router.delete("/sessions/{session_id}", response_model=Message)
async def revoke_session(
    session_id: UUID,
    request: Request,
    response: Response,
    current_user: CurrentUser,
    db: DBSession,
    _: CSRF,
) -> Message:
    row = await db.scalar(
        select(UserSession)
        .where(
            UserSession.id == session_id,
            UserSession.user_id == current_user.id,
            UserSession.revoked_at.is_(None),
        )
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    row.revoked_at = datetime.now(UTC)
    await db.commit()
    if _current_session_id(request, current_user.id) == session_id:
        clear_auth_cookies(response)
    return Message(message="Session revoked")


@router.post("/logout", response_model=Message)
async def logout(
    response: Response,
    db: DBSession,
    _: AuthCSRF,
    refresh_token: str | None = Cookie(default=None, alias=settings.refresh_cookie_name),
) -> Message:
    if refresh_token:
        try:
            payload = decode_token(refresh_token, "refresh")
            session_id = UUID(payload["sid"])
            user_id = UUID(payload["sub"])
            stored_session = await db.scalar(
                select(UserSession).where(
                    UserSession.id == session_id,
                    UserSession.user_id == user_id,
                )
            )
            if stored_session is not None:
                await db.delete(stored_session)
                await db.commit()
        except (InvalidTokenError, KeyError, TypeError, ValueError):
            pass

    clear_auth_cookies(response)
    clear_google_reauth_cookie(response)
    return Message(message="Logged out")


@router.get("/google")
async def google_login(
    request: Request,
    redis: RedisClient,
    action: Annotated[Literal["set_password"] | None, Query()] = None,
    consent: Annotated[bool, Query()] = False,
) -> RedirectResponse:
    if not settings.google_oauth_enabled:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Google OAuth is not configured",
        )
    await enforce_rate_limit(
        redis,
        scope="oauth-start",
        identifier=client_rate_limit_id(request),
        limit=settings.oauth_rate_limit_attempts,
        window_seconds=settings.oauth_rate_limit_window_seconds,
    )
    state = secrets.token_urlsafe(32)
    await redis.setex(f"oauth:google:{state}", 300, action or ("consent" if consent else "1"))
    redirect = RedirectResponse(build_google_authorization_url(state), status_code=302)
    set_oauth_state_cookie(redirect, state)
    return redirect


@router.get("/google/callback")
async def google_callback(
    request: Request,
    db: DBSession,
    redis: RedisClient,
    code: str = Query(min_length=1, max_length=4096),
    state: str = Query(min_length=16, max_length=128),
    oauth_state: str | None = Cookie(
        default=None,
        min_length=16,
        max_length=128,
        alias=settings.oauth_state_cookie_name,
    ),
) -> RedirectResponse:
    await enforce_rate_limit(
        redis,
        scope="oauth-callback",
        identifier=client_rate_limit_id(request),
        limit=settings.oauth_rate_limit_attempts,
        window_seconds=settings.oauth_rate_limit_window_seconds,
    )
    if not safe_compare_ascii(oauth_state, state, max_chars=128):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "OAuth state is invalid or expired")
    state_exists = await redis.getdel(f"oauth:google:{state}")
    if not state_exists:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "OAuth state is invalid or expired")

    try:
        identity = await fetch_google_identity(code)
    except GoogleOAuthUnavailableError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Google sign-in is temporarily unavailable",
        ) from exc
    except GoogleOAuthError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    user = await db.scalar(select(User).where(User.google_sub == identity.sub).with_for_update())
    if user is None:
        email_account = await db.scalar(
            select(User).where(User.email == identity.email).with_for_update()
        )
        if email_account is not None:
            if not isinstance(email_account, User):
                return _oauth_error_redirect("/login", "account_exists")
            if not email_account.is_active:
                return _oauth_error_redirect("/login", "account_disabled")
            if email_account.google_sub not in {None, identity.sub}:
                return _oauth_error_redirect("/login", "google_identity_conflict")
            user = email_account
            user.google_sub = identity.sub
            if user.email_verified_at is None:
                user.email_verified_at = datetime.now(UTC)
                user.name = identity.name or user.name
        else:
            if state_exists != "consent":
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "Accept the Terms and Privacy Policy before creating an account",
                )
            user = User(
                email=identity.email,
                name=identity.name,
                google_sub=identity.sub,
                password_hash=None,
                email_verified_at=datetime.now(UTC),
                terms_accepted_at=datetime.now(UTC),
                privacy_accepted_at=datetime.now(UTC),
            )
            db.add(user)
            try:
                await db.flush()
            except IntegrityError as exc:
                await db.rollback()
                logger.info(
                    "Google sign-in collided with an account created concurrently",
                    exc_info=exc,
                )
                return _oauth_error_redirect("/login", "account_exists")
    elif not user.is_active:
        return _oauth_error_redirect("/login", "account_disabled")

    avatar_request = (
        plan_google_avatar_import(user, identity.picture_url)
        if settings.avatar_storage_enabled
        else None
    )
    if user.totp_secret:
        redirect = RedirectResponse(f"{settings.frontend_url}/login/2fa", status_code=302)
        clear_oauth_state_cookie(redirect)
        challenge = create_mfa_pending_token(user.id, user.auth_version)
        challenge_id = decode_token(challenge, "mfa_pending")["jti"]
        await redis.setex(f"mfa:google:{challenge_id}", 300, identity.sub)
        set_mfa_pending_cookie(redirect, challenge)
        return redirect

    await accept_matching_invitations(db, user)
    tokens = await issue_tokens(db, user, **_session_device(request))
    await db.commit()

    if (
        avatar_request is not None
        and avatar_request.should_enqueue
        and avatar_request.picture_url is not None
    ):
        try:
            from app.worker.tasks import import_google_avatar_task

            import_google_avatar_task.apply_async(
                args=(
                    str(user.id),
                    avatar_request.picture_url,
                    avatar_request.generation,
                ),
                retry=False,
            )
        except Exception:
            # S3, ClamAV, Google image delivery and the worker are auxiliary to
            # authentication. The UI safely falls back to initials.
            logger.exception("Could not enqueue Google avatar import for user %s", user.id)

    if getattr(tokens, "refresh_jti", None) and await enforce_mail_recipient_rate_limit(
        redis,
        recipient=user.email,
        purpose="new-login",
        silent=True,
    ):
        enqueue_mail(
            recipient=user.email,
            kind="new_login",
            context={
                "name": user.name,
                "when": datetime.now(UTC).isoformat(),
                "ip": client_rate_limit_id(request),
                "device": _session_device(request)["user_agent"] or "Неизвестное устройство",
                "action_url": f"{settings.frontend_url}/app/settings",
            },
            idempotency_key=f"new-login/{tokens.refresh_jti}",
        )

    oauth_action = state_exists if isinstance(state_exists, str) else None
    redirect = RedirectResponse(
        (
            f"{settings.frontend_url}/app/settings?password_setup=ready"
            if oauth_action == "set_password"
            else f"{settings.frontend_url}/app"
        ),
        status_code=302,
    )
    clear_oauth_state_cookie(redirect)
    set_auth_cookies(
        redirect,
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        csrf_token=tokens.csrf_token,
    )
    if oauth_action == "set_password":
        set_google_reauth_cookie(
            redirect,
            create_google_reauth_token(user.id, user.auth_version),
        )
    else:
        clear_google_reauth_cookie(redirect)
    return redirect
