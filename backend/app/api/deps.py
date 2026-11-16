from __future__ import annotations

import hashlib
import hmac
import math
import secrets
from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from jwt import InvalidTokenError
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import decode_token
from app.db.session import get_db
from app.models import User, UserSession

DBSession = Annotated[AsyncSession, Depends(get_db)]


def get_redis(request: Request) -> Redis:
    return request.app.state.redis


RedisClient = Annotated[Redis, Depends(get_redis)]
MAX_COMPARISON_TOKEN_CHARS = 256

RATE_LIMIT_SCRIPT = """
local current = redis.call("INCR", KEYS[1])
if current == 1 then
    redis.call("EXPIRE", KEYS[1], ARGV[1])
end
local ttl = redis.call("TTL", KEYS[1])
return {current, ttl}
"""
LEASE_RELEASE_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
end
return 0
"""


def client_rate_limit_id(request: Request) -> str:
    if request.client is None or not request.client.host:
        return "unknown"
    return request.client.host


def safe_compare_ascii(
    left: str | None,
    right: str | None,
    *,
    max_chars: int = MAX_COMPARISON_TOKEN_CHARS,
) -> bool:
    if (
        not isinstance(left, str)
        or not isinstance(right, str)
        or not left
        or not right
        or len(left) > max_chars
        or len(right) > max_chars
    ):
        return False
    try:
        left_bytes = left.encode("ascii")
        right_bytes = right.encode("ascii")
    except UnicodeEncodeError:
        return False
    return hmac.compare_digest(left_bytes, right_bytes)


def _rate_limit_key(scope: str, identifier: str) -> str:
    digest = hmac.new(
        settings.jwt_secret.encode(),
        identifier.encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"rate-limit:{scope}:{digest}"


def rate_limit_error(ttl: int, window_seconds: int) -> HTTPException:
    retry_after = max(1, ttl if ttl > 0 else window_seconds)
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        "Too many requests",
        headers={"Retry-After": str(retry_after)},
    )


async def increment_rate_limit(
    redis: Redis,
    *,
    scope: str,
    identifier: str,
    window_seconds: int,
) -> tuple[int, int]:
    key = _rate_limit_key(scope, identifier)
    result = await redis.eval(RATE_LIMIT_SCRIPT, 1, key, window_seconds)
    return int(result[0]), int(result[1])


async def clear_rate_limit(redis: Redis, *, scope: str, identifier: str) -> None:
    await redis.delete(_rate_limit_key(scope, identifier))


async def enforce_rate_limit(
    redis: Redis,
    *,
    scope: str,
    identifier: str,
    limit: int,
    window_seconds: int,
) -> None:
    count, ttl = await increment_rate_limit(
        redis,
        scope=scope,
        identifier=identifier,
        window_seconds=window_seconds,
    )
    if count <= limit:
        return
    raise rate_limit_error(ttl, window_seconds)


async def enforce_mail_recipient_rate_limit(
    redis: Redis,
    *,
    recipient: str,
    purpose: str,
    silent: bool = False,
) -> bool:
    """Limit each kind of transactional mail without storing recipient PII in Redis keys."""
    count, ttl = await increment_rate_limit(
        redis,
        scope=f"mail-recipient:{purpose}",
        identifier=recipient.strip().lower(),
        window_seconds=settings.mail_rate_limit_window_seconds,
    )
    if count <= settings.mail_recipient_rate_limit_attempts:
        return True
    if silent:
        return False
    raise rate_limit_error(ttl, settings.mail_rate_limit_window_seconds)


async def acquire_distributed_lease(
    redis: Redis,
    *,
    scope: str,
    identifier: str,
    ttl_seconds: float,
) -> str:
    """Acquire a short-lived, owner-safe lease without exposing its identifier."""
    token = secrets.token_urlsafe(32)
    key = _rate_limit_key(f"lease:{scope}", identifier)
    ttl = max(1, math.ceil(ttl_seconds))
    acquired = await redis.set(key, token, ex=ttl, nx=True)
    if not acquired:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "A request of this type is already in progress",
            headers={"Retry-After": str(ttl)},
        )
    return token


async def release_distributed_lease(
    redis: Redis,
    *,
    scope: str,
    identifier: str,
    token: str,
) -> None:
    key = _rate_limit_key(f"lease:{scope}", identifier)
    await redis.eval(LEASE_RELEASE_SCRIPT, 1, key, token)


async def get_current_user(request: Request, db: DBSession) -> User:
    token = request.cookies.get(settings.access_cookie_name)
    authorization = request.headers.get("Authorization", "")
    if authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()

    if not token:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_token(token, "access")
        user_id = UUID(payload["sub"])
    except (InvalidTokenError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = await db.get(User, user_id)
    if user is None or not user.is_active or user.deleted_at is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User is unavailable")
    if payload["ver"] != user.auth_version:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Access token has been revoked")
    if "sid" in payload:
        try:
            session_id = UUID(payload["sid"])
        except (TypeError, ValueError) as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid access session") from exc
        session = await db.get(UserSession, session_id)
        if (
            session is None
            or session.user_id != user.id
            or session.revoked_at is not None
            or session.expires_at <= datetime.now(UTC)
        ):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session has been revoked")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_current_admin_user(current_user: CurrentUser) -> User:
    if not current_user.is_platform_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required")
    return current_user


AdminUser = Annotated[User, Depends(get_current_admin_user)]


async def get_admin_step_up(request: Request, current_admin: AdminUser) -> User:
    token = request.headers.get("X-Admin-Step-Up", "")
    try:
        payload = decode_token(token, "admin_step_up")
        if UUID(payload["sub"]) != current_admin.id or payload["ver"] != current_admin.auth_version:
            raise ValueError("Step-up principal mismatch")
    except (InvalidTokenError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Recent admin authentication required"
        ) from exc
    return current_admin


AdminStepUp = Annotated[User, Depends(get_admin_step_up)]


async def verify_csrf(request: Request) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return

    cookie_token = request.cookies.get(settings.csrf_cookie_name)
    header_token = request.headers.get("X-CSRF-Token")
    if not safe_compare_ascii(cookie_token, header_token):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF validation failed")


CSRF = Annotated[None, Depends(verify_csrf)]


def _normalized_origin(value: str) -> str | None:
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            return None
        _ = parsed.port
    except ValueError:
        return None
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}".rstrip("/")


async def verify_auth_csrf(request: Request) -> None:
    cookie_token = request.cookies.get(settings.csrf_cookie_name)
    header_token = request.headers.get("X-CSRF-Token")
    if safe_compare_ascii(cookie_token, header_token):
        return

    candidate = request.headers.get("Origin")
    if candidate is None:
        candidate = request.headers.get("Referer")
    normalized = _normalized_origin(candidate) if candidate else None
    if normalized is not None and normalized in settings.trusted_request_origins:
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF validation failed")


AuthCSRF = Annotated[None, Depends(verify_auth_csrf)]
