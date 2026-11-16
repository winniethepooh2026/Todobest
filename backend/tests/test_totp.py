from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response
from starlette.requests import Request

from app.api.routes import auth
from app.core.encryption import DataCipher
from app.core.security import create_mfa_pending_token, decode_token
from app.models import User
from app.schemas import LoginRequest, TokenRequest, TotpCodeRequest
from app.services import mfa


def test_totp_rfc_vector_and_replay_protection(monkeypatch) -> None:
    key = base64.urlsafe_b64encode(bytes(range(32))).decode()
    monkeypatch.setattr(mfa, "get_data_cipher", lambda: DataCipher(key))
    user = User(id=uuid4(), email="member@example.com", name="Member", totp_last_counter=-1)
    # RFC 6238 SHA-1 test secret, truncated to the six digits used by authenticator apps.
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # noqa: S105 - public RFC test vector
    user.totp_secret = mfa.seal_secret(user, secret)
    assert mfa.open_secret(user, user.totp_secret) == secret
    assert mfa.check_totp(user, "287082", now=59)
    assert not mfa.check_totp(user, "287082", now=59)
    assert not mfa.check_totp(user, "000000", now=59)


def test_recovery_codes_are_one_use() -> None:
    user = User(id=uuid4(), email="member@example.com", name="Member")
    codes, user.totp_recovery_hashes = mfa.create_recovery_codes()
    assert len(codes) == 8
    assert all(code not in user.totp_recovery_hashes for code in codes)
    assert mfa.check_recovery_code(user, codes[0])
    assert not mfa.check_recovery_code(user, codes[0])
    assert len(json.loads(user.totp_recovery_hashes)) == 7


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/login",
            "headers": [(b"user-agent", b"Firefox")],
            "query_string": b"",
            "client": ("203.0.113.10", 1234),
        }
    )


@pytest.mark.asyncio
async def test_password_login_never_issues_session_before_second_factor(monkeypatch) -> None:
    user = User(
        id=uuid4(),
        email="member@example.com",
        name="Member",
        password_hash="test-hash",  # noqa: S106 - non-secret test marker
        is_active=True,
        totp_secret="encrypted",  # noqa: S106 - non-secret test marker
    )

    class DB:
        async def scalar(self, _query):
            return user

        async def rollback(self):
            pass

    async def noop(*_args, **_kwargs):
        return None

    async def valid_password(*_args):
        return True

    async def forbidden_issue(*_args, **_kwargs):
        raise AssertionError("session must not be issued")

    monkeypatch.setattr(auth, "enforce_rate_limit", noop)
    monkeypatch.setattr(auth, "clear_rate_limit", noop)
    monkeypatch.setattr(auth, "verify_password_async", valid_password)
    monkeypatch.setattr(auth, "issue_tokens", forbidden_issue)
    monkeypatch.setattr(auth, "verify_second_factor", lambda *_args: False)
    missing = LoginRequest(email=user.email, password="test-password")  # noqa: S106
    with pytest.raises(HTTPException) as exc:
        await auth.login(missing, _request(), Response(), DB(), object())  # type: ignore[arg-type]
    assert exc.value.status_code == 428
    invalid = LoginRequest(email=user.email, password="test-password", mfa_code="000000")  # noqa: S106
    with pytest.raises(HTTPException) as exc:
        await auth.login(invalid, _request(), Response(), DB(), object())  # type: ignore[arg-type]
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_google_challenge_is_one_use(monkeypatch) -> None:
    user = User(
        id=uuid4(),
        email="member@example.com",
        name="Member",
        is_active=True,
        auth_version=0,
        totp_secret="encrypted",  # noqa: S106 - non-secret test marker
        google_sub="google-123",
        timezone="UTC",
        is_platform_admin=False,
        created_at=datetime.now(UTC),
    )
    pending = create_mfa_pending_token(user.id)
    challenge_id = decode_token(pending, "mfa_pending")["jti"]

    class DB:
        async def scalar(self, _query):
            return user

        async def commit(self):
            pass

    class Redis:
        ticket: str | None = "google-123"

        async def getdel(self, key: str) -> str | None:
            assert key == f"mfa:google:{challenge_id}"
            value, self.ticket = self.ticket, None
            return value

    async def noop(*_args, **_kwargs):
        return None

    async def no_mail(*_args, **_kwargs):
        return False

    async def fake_issue(*_args, **_kwargs):
        return SimpleNamespace(
            access_token="access",  # noqa: S106 - non-secret test value
            refresh_token="refresh",  # noqa: S106 - non-secret test value
            csrf_token="csrf",  # noqa: S106 - non-secret test value
        )

    monkeypatch.setattr(auth, "enforce_rate_limit", noop)
    monkeypatch.setattr(auth, "enforce_mail_recipient_rate_limit", no_mail)
    monkeypatch.setattr(auth, "accept_matching_invitations", noop)
    monkeypatch.setattr(auth, "issue_tokens", fake_issue)
    monkeypatch.setattr(auth, "verify_second_factor", lambda *_args: True)
    redis = Redis()
    response = Response()
    await auth.complete_google_totp(
        TotpCodeRequest(code="123456"), _request(), response, DB(), redis, pending
    )  # type: ignore[arg-type]
    assert redis.ticket is None
    assert "noki_access" in response.headers["set-cookie"]
    with pytest.raises(HTTPException) as exc:
        await auth.complete_google_totp(
            TotpCodeRequest(code="123456"), _request(), Response(), DB(), redis, pending
        )  # type: ignore[arg-type]
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_email_verification_cannot_bypass_second_factor(monkeypatch) -> None:
    user = User(
        id=uuid4(),
        email="member@example.com",
        name="Member",
        is_active=True,
        totp_secret="encrypted",  # noqa: S106 - non-secret test marker
    )
    token = SimpleNamespace(user_id=user.id, consumed_at=None)

    class DB:
        results = iter((token, user))
        committed = False

        async def scalar(self, _query):
            return next(self.results)

        async def commit(self):
            self.committed = True

    async def noop(*_args, **_kwargs):
        return None

    async def forbidden_issue(*_args, **_kwargs):
        raise AssertionError("email verification must not issue a session")

    monkeypatch.setattr(auth, "accept_matching_invitations", noop)
    monkeypatch.setattr(auth, "issue_tokens", forbidden_issue)
    db = DB()
    result = await auth.verify_email(TokenRequest(token="x" * 43), Response(), db)  # type: ignore[arg-type]
    assert db.committed
    assert result.message.startswith("Email verified")
    assert token.consumed_at is not None


@pytest.mark.asyncio
async def test_enabling_totp_replaces_old_sessions_and_returns_recovery_codes(monkeypatch) -> None:
    user = User(
        id=uuid4(),
        email="member@example.com",
        name="Member",
        auth_version=0,
        totp_pending_secret="sealed",  # noqa: S106 - non-secret test marker
        totp_pending_created_at=datetime.now(UTC),
    )

    class DB:
        committed = False
        revoked = False

        async def scalar(self, _query):
            return user

        async def execute(self, _query):
            self.revoked = True

        async def commit(self):
            self.committed = True

    async def noop(*_args, **_kwargs):
        return None

    async def fake_issue(*_args, **_kwargs):
        return SimpleNamespace(
            access_token="access",  # noqa: S106 - non-secret test value
            refresh_token="refresh",  # noqa: S106 - non-secret test value
            csrf_token="csrf",  # noqa: S106 - non-secret test value
        )

    monkeypatch.setattr(auth, "enforce_rate_limit", noop)
    monkeypatch.setattr(auth, "check_totp", lambda *_args: True)
    monkeypatch.setattr(auth, "issue_tokens", fake_issue)
    db = DB()
    response = Response()
    result = await auth.confirm_totp(
        TotpCodeRequest(code="123456"),
        _request(),
        response,
        user,
        db,
        object(),
        None,
    )  # type: ignore[arg-type]
    assert len(result.recovery_codes) == 8
    assert user.auth_version == 1
    assert user.totp_secret == "sealed"  # noqa: S105 - non-secret test marker
    assert db.revoked and db.committed
    assert "noki_access" in response.headers["set-cookie"]
