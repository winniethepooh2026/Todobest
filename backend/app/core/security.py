from __future__ import annotations

import asyncio
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Response
from jwt import InvalidTokenError

from app.core.config import settings

password_hasher = PasswordHasher()
PASSWORD_WORK_CONCURRENCY = 2
password_work_semaphore = asyncio.Semaphore(PASSWORD_WORK_CONCURRENCY)
# A real Argon2 hash keeps the nonexistent-user login path comparable to a
# normal password verification without exposing whether an email is registered.
DUMMY_PASSWORD_HASH = password_hasher.hash("noki-dummy-password-verification")
GOOGLE_REAUTH_COOKIE_NAME = "google_reauth"
GOOGLE_REAUTH_TTL_SECONDS = 5 * 60
ADMIN_STEP_UP_TTL_SECONDS = 10 * 60


class PasswordWorkCapacityError(RuntimeError):
    pass


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    try:
        return password_hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def _release_password_work_slot(task: asyncio.Task[Any]) -> None:
    password_work_semaphore.release()
    # Retrieve background exceptions after caller cancellation so asyncio does
    # not emit an unhandled-task warning. Normal callers retrieve the same result.
    if not task.cancelled():
        task.exception()


async def _run_password_work(function: Any, *args: str) -> Any:
    try:
        async with asyncio.timeout(settings.password_work_queue_timeout_seconds):
            await password_work_semaphore.acquire()
    except TimeoutError as exc:
        raise PasswordWorkCapacityError("Password verification capacity is busy") from exc

    try:
        task = asyncio.create_task(asyncio.to_thread(function, *args))
    except BaseException:
        password_work_semaphore.release()
        raise
    task.add_done_callback(_release_password_work_slot)
    return await asyncio.shield(task)


async def hash_password_async(password: str) -> str:
    return await _run_password_work(hash_password, password)


async def verify_password_async(password: str, password_hash: str) -> bool:
    return await _run_password_work(verify_password, password, password_hash)


def _create_token(
    *,
    user_id: UUID,
    auth_version: int,
    token_type: str,
    expires_delta: timedelta,
    jti: UUID | None = None,
    session_id: UUID | None = None,
    expires_at: datetime | None = None,
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "typ": token_type,
        "iat": now,
        "exp": expires_at or now + expires_delta,
        "jti": str(jti or uuid4()),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "ver": auth_version,
    }
    if session_id is not None:
        payload["sid"] = str(session_id)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(
    user_id: UUID, auth_version: int = 0, *, session_id: UUID | None = None
) -> str:
    return _create_token(
        user_id=user_id,
        auth_version=auth_version,
        token_type="access",
        expires_delta=timedelta(minutes=settings.access_token_minutes),
        session_id=session_id,
    )


def create_refresh_token(
    user_id: UUID,
    jti: UUID,
    session_id: UUID,
    auth_version: int = 0,
    *,
    expires_at: datetime | None = None,
) -> str:
    if expires_at is None:
        expires_at = datetime.now(UTC) + timedelta(days=settings.refresh_token_days)
    elif expires_at <= datetime.now(UTC):
        raise ValueError("Refresh session expiration must be in the future")
    return _create_token(
        user_id=user_id,
        auth_version=auth_version,
        token_type="refresh",
        expires_delta=timedelta(0),
        jti=jti,
        session_id=session_id,
        expires_at=expires_at,
    )


MFA_PENDING_COOKIE_NAME = "noki_mfa_pending"


def create_mfa_pending_token(user_id: UUID, auth_version: int = 0) -> str:
    return _create_token(
        user_id=user_id,
        auth_version=auth_version,
        token_type="mfa_pending",
        expires_delta=timedelta(minutes=5),
    )


def set_mfa_pending_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        MFA_PENDING_COOKIE_NAME, token, httponly=True,
        secure=settings.cookie_secure, samesite="strict",
        domain=settings.cookie_domain, max_age=300,
        path=f"{settings.api_v1_prefix}/auth",
    )


def clear_mfa_pending_cookie(response: Response) -> None:
    response.delete_cookie(
        MFA_PENDING_COOKIE_NAME,
        domain=settings.cookie_domain,
        path=f"{settings.api_v1_prefix}/auth",
    )


def create_google_reauth_token(user_id: UUID, auth_version: int = 0) -> str:
    return _create_token(
        user_id=user_id,
        auth_version=auth_version,
        token_type="google_reauth",
        expires_delta=timedelta(seconds=GOOGLE_REAUTH_TTL_SECONDS),
    )


def create_admin_step_up_token(user_id: UUID, auth_version: int = 0) -> str:
    return _create_token(
        user_id=user_id,
        auth_version=auth_version,
        token_type="admin_step_up",
        expires_delta=timedelta(seconds=ADMIN_STEP_UP_TTL_SECONDS),
    )


def decode_token(token: str, expected_type: str) -> dict[str, Any]:
    if len(token.encode()) > settings.max_jwt_bytes:
        raise InvalidTokenError("Token is too large")
    required_claims = [
        "sub",
        "typ",
        "exp",
        "iat",
        "jti",
        "iss",
        "aud",
        "ver",
    ]
    if expected_type == "refresh":
        required_claims.append("sid")
    payload = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
        audience=settings.jwt_audience,
        issuer=settings.jwt_issuer,
        options={
            "require": required_claims,
        },
    )
    if payload.get("typ") != expected_type:
        raise InvalidTokenError("Wrong token type")
    try:
        UUID(payload["sub"])
        UUID(payload["jti"])
        if expected_type == "refresh":
            UUID(payload["sid"])
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidTokenError("Invalid token identifiers") from exc
    auth_version = payload.get("ver")
    if isinstance(auth_version, bool) or not isinstance(auth_version, int) or auth_version < 0:
        raise InvalidTokenError("Invalid token authentication version")
    return payload


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def set_auth_cookies(
    response: Response,
    *,
    access_token: str,
    refresh_token: str,
    csrf_token: str,
) -> None:
    common = {
        "secure": settings.cookie_secure,
        "samesite": settings.cookie_samesite,
        "domain": settings.cookie_domain,
    }
    response.set_cookie(
        settings.access_cookie_name,
        access_token,
        httponly=True,
        max_age=settings.access_token_minutes * 60,
        path="/",
        **common,
    )
    response.set_cookie(
        settings.refresh_cookie_name,
        refresh_token,
        httponly=True,
        max_age=settings.refresh_token_days * 24 * 60 * 60,
        path=f"{settings.api_v1_prefix}/auth",
        **common,
    )
    response.set_cookie(
        settings.csrf_cookie_name,
        csrf_token,
        httponly=False,
        max_age=settings.refresh_token_days * 24 * 60 * 60,
        path="/",
        **common,
    )


def clear_auth_cookies(response: Response) -> None:
    common = {
        "secure": settings.cookie_secure,
        "samesite": settings.cookie_samesite,
        "domain": settings.cookie_domain,
    }
    response.delete_cookie(settings.access_cookie_name, path="/", **common)
    response.delete_cookie(
        settings.refresh_cookie_name,
        path=f"{settings.api_v1_prefix}/auth",
        **common,
    )
    response.delete_cookie(settings.csrf_cookie_name, path="/", **common)


def set_oauth_state_cookie(response: Response, state: str) -> None:
    response.set_cookie(
        settings.oauth_state_cookie_name,
        state,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        domain=settings.cookie_domain,
        max_age=300,
        path=f"{settings.api_v1_prefix}/auth/google/callback",
    )


def clear_oauth_state_cookie(response: Response) -> None:
    response.delete_cookie(
        settings.oauth_state_cookie_name,
        secure=settings.cookie_secure,
        samesite="lax",
        domain=settings.cookie_domain,
        path=f"{settings.api_v1_prefix}/auth/google/callback",
    )


def set_google_reauth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        GOOGLE_REAUTH_COOKIE_NAME,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        domain=settings.cookie_domain,
        max_age=GOOGLE_REAUTH_TTL_SECONDS,
        path="/",
    )


def clear_google_reauth_cookie(response: Response) -> None:
    response.delete_cookie(
        GOOGLE_REAUTH_COOKIE_NAME,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        domain=settings.cookie_domain,
        path="/",
    )
