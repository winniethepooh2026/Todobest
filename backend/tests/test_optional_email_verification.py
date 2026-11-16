from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException, Request, Response
from pydantic import SecretStr

from app.api.routes import auth
from app.core.config import settings
from app.models import User
from app.schemas import LoginRequest, RegisterRequest


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/register",
            "headers": [],
            "client": ("203.0.113.10", 12345),
            "scheme": "https",
            "server": ("noki.example", 443),
        }
    )


class _ExistingUserDB:
    def __init__(self, user: User) -> None:
        self.user = user

    async def scalar(self, _statement: object) -> User:
        return self.user


@pytest.mark.asyncio
async def test_duplicate_registration_neither_counts_nor_sends_mail(monkeypatch) -> None:
    user = User(
        id=uuid4(),
        email="member@example.com",
        name="Team Member",
        password_hash="argon-hash",  # noqa: S106 - non-secret test value
        is_active=True,
        is_platform_admin=False,
        auth_version=0,
        timezone="UTC",
        created_at=datetime.now(UTC),
    )

    async def unexpected_async_call(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("duplicate registration must stop before side effects")

    def unexpected_mail(*_args: object, **_kwargs: object) -> bool:
        raise AssertionError("duplicate registration must not send mail")

    monkeypatch.setattr(auth, "enforce_rate_limit", unexpected_async_call)
    monkeypatch.setattr(auth, "hash_password_async", unexpected_async_call)
    monkeypatch.setattr(auth, "enqueue_mail", unexpected_mail)

    with pytest.raises(HTTPException) as captured:
        await auth.register(
            payload=RegisterRequest(
                name="Another User",
                email="member@example.com",
                password="correct horse battery staple",  # noqa: S106
                accept_terms=True,
                accept_privacy=True,
            ),
            request=_request(),
            response=Response(),
            db=_ExistingUserDB(user),  # type: ignore[arg-type]
            redis=object(),  # type: ignore[arg-type]
        )

    assert captured.value.status_code == 409


class _VerificationDB:
    def __init__(self) -> None:
        self.committed = False

    async def commit(self) -> None:
        self.committed = True


@pytest.mark.asyncio
async def test_unverified_user_can_request_verification_mail(monkeypatch) -> None:
    user = User(
        id=uuid4(),
        email="member@example.com",
        name="Team Member",
        password_hash="argon-hash",  # noqa: S106 - non-secret test value
        is_active=True,
        auth_version=0,
        timezone="UTC",
        created_at=datetime.now(UTC),
        email_verified_at=None,
    )
    db = _VerificationDB()
    captured: dict[str, object] = {}

    async def allow_mail(
        _redis: object,
        *,
        recipient: str,
        purpose: str,
        silent: bool,
    ) -> bool:
        captured["recipient"] = recipient
        captured["purpose"] = purpose
        captured["silent"] = silent
        return True

    async def issue_token(
        _db: object,
        *,
        user_id: object,
        purpose: str,
        ttl: object,
    ) -> tuple[SimpleNamespace, str]:
        captured["user_id"] = user_id
        captured["token_purpose"] = purpose
        captured["ttl"] = ttl
        return SimpleNamespace(id=uuid4()), "verification-token"

    def send_mail(**kwargs: object) -> str:
        captured["mail"] = kwargs
        return "resend-message-id"

    monkeypatch.setattr(settings, "resend_api_key", SecretStr("test-resend-key"))
    monkeypatch.setattr(auth, "enforce_mail_recipient_rate_limit", allow_mail)
    monkeypatch.setattr(auth, "issue_one_time_token", issue_token)
    monkeypatch.setattr(auth, "send_mail", send_mail)

    result = await auth.send_verification_email(
        current_user=user,
        db=db,  # type: ignore[arg-type]
        redis=object(),  # type: ignore[arg-type]
        _=None,
    )

    assert result.message == "Verification email sent"
    assert db.committed is True
    assert captured["purpose"] == "email-verification"
    assert captured["silent"] is False
    assert captured["token_purpose"] == "verify_email"  # noqa: S105 - token category
    mail = captured["mail"]
    assert isinstance(mail, dict)
    assert mail["recipient"] == "member@example.com"
    assert mail["kind"] == "verify_email"


class _LoginRedis:
    async def eval(
        self,
        _script: str,
        _key_count: int,
        _key: str,
        *_arguments: object,
    ) -> list[int]:
        return [1, 300]

    async def delete(self, _key: str) -> None:
        return None


class _LoginDB:
    def __init__(self, user: User) -> None:
        self.user = user
        self.committed = False
        self.scalar_calls = 0

    async def scalar(self, _statement: object) -> User:
        self.scalar_calls += 1
        return self.user

    async def rollback(self) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True


@pytest.mark.asyncio
async def test_unverified_user_can_sign_in(monkeypatch) -> None:
    user = User(
        id=uuid4(),
        email="member@example.com",
        name="Team Member",
        password_hash="argon-hash",  # noqa: S106 - non-secret test value
        is_active=True,
        is_platform_admin=False,
        auth_version=0,
        timezone="UTC",
        created_at=datetime.now(UTC),
        email_verified_at=None,
    )
    db = _LoginDB(user)

    async def password_is_valid(_password: str, _password_hash: str) -> bool:
        return True

    async def issue_tokens(
        _db: object, token_user: User, **_device: object
    ) -> SimpleNamespace:
        assert token_user is user
        return SimpleNamespace(
            access_token="access-token",  # noqa: S106 - non-secret test value
            refresh_token="refresh-token",  # noqa: S106 - non-secret test value
            csrf_token="csrf-token",  # noqa: S106 - non-secret test value
            refresh_jti=uuid4(),
        )

    async def accept_invitations(_db: object, accepted_user: User) -> None:
        assert accepted_user is user

    monkeypatch.setattr(auth, "verify_password_async", password_is_valid)
    monkeypatch.setattr(auth, "password_needs_rehash", lambda _password_hash: False)
    monkeypatch.setattr(auth, "issue_tokens", issue_tokens)
    monkeypatch.setattr(auth, "accept_matching_invitations", accept_invitations)
    monkeypatch.setattr(auth, "enqueue_mail", lambda **_kwargs: True)

    response = Response()
    result = await auth.login(
        payload=LoginRequest(
            email="member@example.com",
            password="correct horse battery staple",  # noqa: S106 - test value
        ),
        request=_request(),
        response=response,
        db=db,  # type: ignore[arg-type]
        redis=_LoginRedis(),  # type: ignore[arg-type]
    )

    assert result.user.email == "member@example.com"
    assert result.user.email_verified is False
    assert db.committed is True
    assert "noki_access=access-token" in response.headers["set-cookie"]
