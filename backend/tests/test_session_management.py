from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response
from starlette.requests import Request

from app.api.deps import get_current_user
from app.api.routes.auth import list_sessions, revoke_session
from app.core.config import settings
from app.core.security import create_access_token, create_refresh_token
from app.models import User, UserSession


def request(*, access: str | None = None, refresh: str | None = None) -> Request:
    headers = []
    if access:
        headers.append((b"authorization", f"Bearer {access}".encode()))
    if refresh:
        headers.append((b"cookie", f"{settings.refresh_cookie_name}={refresh}".encode()))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/auth/sessions",
            "headers": headers,
            "query_string": b"",
            "client": ("203.0.113.10", 1),
        }
    )


class SessionDB:
    def __init__(self, user: User, session: UserSession | None) -> None:
        self.user = user
        self.session = session
        self.committed = False

    async def get(self, model: type, _id: object) -> User | UserSession | None:
        return self.user if model is User else self.session

    async def scalar(self, _statement: object) -> UserSession | None:
        return self.session

    async def scalars(self, _statement: object) -> object:
        class Rows:
            def __init__(self, session: UserSession | None) -> None:
                self.session = session

            def all(self) -> list[UserSession]:
                return [self.session] if self.session is not None else []

        return Rows(self.session)

    async def commit(self) -> None:
        self.committed = True


def fixtures() -> tuple[User, UserSession, str, str]:
    user = User(
        id=uuid4(), email="member@example.com", name="Member", is_active=True, auth_version=0
    )
    session = UserSession(
        id=uuid4(),
        user_id=user.id,
        refresh_jti=uuid4(),
        expires_at=datetime.now(UTC) + timedelta(days=1),
        user_agent="Firefox",
        ip_address="203.0.113.10",
        created_at=datetime.now(UTC),
    )
    access = create_access_token(user.id, session_id=session.id)
    refresh = create_refresh_token(user.id, session.refresh_jti, session.id)
    return user, session, access, refresh


@pytest.mark.asyncio
async def test_revoke_one_session_blocks_its_access_token_immediately() -> None:
    user, session, access, refresh = fixtures()
    db = SessionDB(user, session)
    current = await get_current_user(request(access=access), db)  # type: ignore[arg-type]
    assert current.id == user.id
    response = Response()
    await revoke_session(session.id, request(refresh=refresh), response, user, db, None)  # type: ignore[arg-type]
    assert db.committed
    assert session.revoked_at is not None
    with pytest.raises(HTTPException) as exc:
        await get_current_user(request(access=access), db)  # type: ignore[arg-type]
    assert exc.value.status_code == 401
    assert settings.access_cookie_name in response.headers["set-cookie"]


@pytest.mark.asyncio
async def test_sessions_identify_current_device() -> None:
    user, session, _access, refresh = fixtures()
    rows = await list_sessions(request(refresh=refresh), user, SessionDB(user, session))  # type: ignore[arg-type]
    assert len(rows) == 1
    assert rows[0].current
    assert rows[0].ip_address == "203.0.113.10"
