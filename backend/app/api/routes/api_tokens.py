from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import delete, or_, select

from app.api.deps import CSRF, CurrentUser, DBSession
from app.models import ApiToken, User
from app.schemas import ApiTokenCreate, ApiTokenCreated, ApiTokenOut, Message
from app.services.api_tokens import (
    generate_api_token,
    parse_api_token_scopes,
    serialize_api_token_scopes,
)

router = APIRouter(prefix="/api-tokens", tags=["API tokens"])


def api_token_to_schema(token: ApiToken) -> ApiTokenOut:
    scopes = parse_api_token_scopes(token.scopes)
    return ApiTokenOut(
        id=token.id,
        name=token.name,
        prefix=token.token_prefix,
        scopes=[scope for scope in ("read", "write") if scope in scopes],
        expires_at=token.expires_at,
        last_used_at=token.last_used_at,
        created_at=token.created_at,
    )


@router.get("", response_model=list[ApiTokenOut])
async def list_api_tokens(current_user: CurrentUser, db: DBSession) -> list[ApiTokenOut]:
    tokens = list(
        await db.scalars(
            select(ApiToken)
            .where(
                ApiToken.user_id == current_user.id,
                ApiToken.revoked_at.is_(None),
                ApiToken.expires_at > datetime.now(UTC),
                ApiToken.auth_version == current_user.auth_version,
            )
            .order_by(ApiToken.created_at.desc(), ApiToken.id.desc())
        )
    )
    return [api_token_to_schema(token) for token in tokens]


@router.post("", response_model=ApiTokenCreated, status_code=status.HTTP_201_CREATED)
async def create_api_token(
    payload: ApiTokenCreate,
    current_user: CurrentUser,
    db: DBSession,
    _: CSRF,
) -> ApiTokenCreated:
    now = datetime.now(UTC)
    locked_user = await db.scalar(
        select(User)
        .where(User.id == current_user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked_user is None or not locked_user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User is unavailable")

    await db.execute(
        delete(ApiToken).where(
            ApiToken.user_id == current_user.id,
            or_(
                ApiToken.revoked_at.is_not(None),
                ApiToken.expires_at <= now,
                ApiToken.auth_version != locked_user.auth_version,
            ),
        )
    )
    raw_token, token_hash, token_prefix = generate_api_token()
    token = ApiToken(
        user_id=current_user.id,
        name=payload.name,
        token_hash=token_hash,
        token_prefix=token_prefix,
        scopes=serialize_api_token_scopes(payload.scopes),
        auth_version=locked_user.auth_version,
        expires_at=now + timedelta(days=payload.expires_in_days),
        created_at=now,
    )
    db.add(token)
    await db.commit()
    await db.refresh(token)

    result = api_token_to_schema(token)
    return ApiTokenCreated(**result.model_dump(), token=raw_token)


@router.delete("/{token_id}", response_model=Message)
async def revoke_api_token(
    token_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
    _: CSRF,
) -> Message:
    token = await db.scalar(
        select(ApiToken)
        .where(
            ApiToken.id == token_id,
            ApiToken.user_id == current_user.id,
            ApiToken.revoked_at.is_(None),
        )
        .with_for_update()
    )
    if token is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "API token not found")

    await db.delete(token)
    await db.commit()
    return Message(message="API token revoked")
