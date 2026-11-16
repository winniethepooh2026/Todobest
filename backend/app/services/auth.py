from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    new_csrf_token,
)
from app.models import User, UserSession
from app.schemas import UserOut
from app.services.avatars import user_avatar_url


@dataclass(slots=True)
class AuthTokens:
    access_token: str
    refresh_token: str
    csrf_token: str
    refresh_jti: UUID


def user_to_schema(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        name=user.name,
        bio=user.bio,
        avatar_url=user_avatar_url(user),
        timezone=user.timezone,
        has_password=user.password_hash is not None,
        google_connected=user.google_sub is not None,
        is_platform_admin=user.is_platform_admin,
        email_verified=user.email_verified_at is not None,
        totp_enabled=user.totp_secret is not None,
        created_at=user.created_at,
    )


async def issue_tokens(
    db: AsyncSession,
    user: User,
    *,
    session: UserSession | None = None,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> AuthTokens:
    # Serialize issuers per user and keep the session table bounded even if a
    # valid client loops on login. Existing refresh tokens beyond the cap are
    # intentionally invalidated.
    await db.flush()
    await db.execute(select(User.id).where(User.id == user.id).with_for_update())
    now = datetime.now(UTC)
    # A family is one row and rotates its current JTI in place. Revoked/expired
    # rows can therefore be removed without losing replay protection for any
    # active branch.
    await db.execute(
        delete(UserSession).where(
            UserSession.user_id == user.id,
            (UserSession.revoked_at.is_not(None) | (UserSession.expires_at <= now)),
        )
    )
    jti = uuid4()
    if session is None:
        existing_session_ids = list(
            (
                await db.scalars(
                    select(UserSession.id)
                    .where(
                        UserSession.user_id == user.id,
                        UserSession.revoked_at.is_(None),
                        UserSession.expires_at > now,
                    )
                    .order_by(UserSession.created_at, UserSession.id)
                )
            ).all()
        )
        overflow = len(existing_session_ids) - settings.max_sessions_per_user + 1
        if overflow > 0:
            await db.execute(
                delete(UserSession).where(UserSession.id.in_(existing_session_ids[:overflow]))
            )
        session = UserSession(
            id=uuid4(),
            user_id=user.id,
            refresh_jti=jti,
            expires_at=now + timedelta(days=settings.refresh_token_days),
            user_agent=user_agent,
            ip_address=ip_address,
            last_seen_at=now,
        )
        db.add(session)
    else:
        if (
            session.user_id != user.id
            or session.revoked_at is not None
            or session.expires_at <= now
        ):
            raise ValueError("Cannot rotate an unavailable refresh session")
        session.refresh_jti = jti
        session.last_seen_at = now
    await db.flush()

    return AuthTokens(
        access_token=create_access_token(user.id, user.auth_version, session_id=session.id),
        refresh_token=create_refresh_token(
            user.id,
            jti,
            session.id,
            user.auth_version,
            expires_at=session.expires_at,
        ),
        csrf_token=new_csrf_token(),
        refresh_jti=jti,
    )
