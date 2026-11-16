from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import (
    DBSession,
    RedisClient,
    client_rate_limit_id,
    enforce_rate_limit,
)
from app.core.config import settings
from app.models import ApiToken, User
from app.services.api_tokens import hash_api_token, is_api_token, parse_api_token_scopes

ApiScope = Literal["read", "write"]
api_token_scheme = HTTPBearer(
    scheme_name="NokiApiToken",
    bearerFormat="noki_pat_...",
    description="Personal Noki API token",
    auto_error=False,
)


@dataclass(frozen=True, slots=True)
class ApiPrincipal:
    user: User
    token_id: UUID
    scopes: frozenset[str]


def _invalid_api_token() -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Invalid or expired API token",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_api_principal(
    request: Request,
    db: DBSession,
    redis: RedisClient,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(api_token_scheme),
    ] = None,
) -> ApiPrincipal:
    await enforce_rate_limit(
        redis,
        scope="public-api-ip",
        identifier=client_rate_limit_id(request),
        limit=settings.public_api_ip_rate_limit_requests,
        window_seconds=settings.public_api_rate_limit_window_seconds,
    )

    token_value = credentials.credentials if credentials is not None else ""
    if (
        credentials is None
        or credentials.scheme.casefold() != "bearer"
        or not is_api_token(token_value)
    ):
        raise _invalid_api_token()

    now = datetime.now(UTC)
    token = await db.scalar(
        select(ApiToken)
        .where(
            ApiToken.token_hash == hash_api_token(token_value),
            ApiToken.revoked_at.is_(None),
            ApiToken.expires_at > now,
        )
        .options(selectinload(ApiToken.user))
    )
    if token is None or not token.user.is_active or token.auth_version != token.user.auth_version:
        raise _invalid_api_token()

    await enforce_rate_limit(
        redis,
        scope="public-api-token",
        identifier=str(token.id),
        limit=settings.public_api_token_rate_limit_requests,
        window_seconds=settings.public_api_rate_limit_window_seconds,
    )

    last_used_at = token.last_used_at
    if last_used_at is not None and last_used_at.tzinfo is None:
        last_used_at = last_used_at.replace(tzinfo=UTC)
    if last_used_at is None or last_used_at < now - timedelta(minutes=5):
        token.last_used_at = now
        await db.commit()
    return ApiPrincipal(
        user=token.user,
        token_id=token.id,
        scopes=parse_api_token_scopes(token.scopes),
    )


ApiTokenPrincipal = Annotated[ApiPrincipal, Depends(get_api_principal)]


def require_api_scope(scope: ApiScope):
    async def dependency(
        principal: ApiTokenPrincipal,
    ) -> ApiPrincipal:
        if scope not in principal.scopes:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"API token requires the '{scope}' scope",
            )
        return principal

    return dependency


ReadApiPrincipal = Annotated[ApiPrincipal, Depends(require_api_scope("read"))]
WriteApiPrincipal = Annotated[ApiPrincipal, Depends(require_api_scope("write"))]
