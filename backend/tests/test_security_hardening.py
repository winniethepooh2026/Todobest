from __future__ import annotations

import asyncio
import base64
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import httpx
import jwt
import pytest
from fastapi import HTTPException, Response
from jwt import InvalidTokenError
from pydantic import ValidationError
from sqlalchemy import CheckConstraint
from sqlalchemy.engine import make_url
from starlette.requests import Request

from app.api import deps
from app.api.routes import auth, users
from app.core import security
from app.core.config import INSECURE_JWT_SECRET, Settings, get_settings, settings
from app.models import OneTimeToken, User, UserSession
from app.schemas import (
    ChangePasswordRequest,
    EmailRequest,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    UpdateProfileRequest,
)
from app.services import oauth
from app.services.auth import issue_tokens
from app.services.oauth import GoogleIdentity


def _request(
    headers: dict[str, str] | None = None,
    *,
    client_host: str = "203.0.113.10",
) -> Request:
    raw_headers = [
        (name.lower().encode("latin-1"), value.encode("latin-1"))
        for name, value in (headers or {}).items()
    ]
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "https",
            "path": "/api/v1/auth/test",
            "raw_path": b"/api/v1/auth/test",
            "query_string": b"",
            "headers": raw_headers,
            "client": (client_host, 54321),
            "server": ("api.example.com", 443),
        }
    )


def _production_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "environment": "production",
        "database_url": "postgresql+asyncpg://noki:production-password@db:5432/noki",
        "redis_url": "redis://:production-redis-password@redis:6379/0",
        "jwt_secret": "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz!@",
        "data_encryption_key": base64.urlsafe_b64encode(bytes(range(32))).decode(),
        "backend_url": "https://api.example.com",
        "frontend_url": "https://app.example.com",
        "cors_origins": "https://app.example.com",
        "trusted_hosts": "api.example.com",
        "cookie_secure": True,
        "cookie_samesite": "lax",
        "google_client_id": "",
        "google_client_secret": "",
        "google_redirect_uri": "https://api.example.com/api/v1/auth/google/callback",
        "upload_dir": Path.cwd().resolve() / "storage",
    }
    values.update(overrides)
    return Settings(**values)


def test_safe_production_settings_are_accepted_and_registration_defaults_open() -> None:
    configured = _production_settings()

    assert configured.public_registration_enabled is True
    assert configured.mail_from == "Noki <no-reply@noki.click>"
    assert configured.trusted_host_list == ["api.example.com"]
    assert configured.trusted_request_origins == [
        "https://api.example.com",
        "https://app.example.com",
    ]
    assert configured.expected_db_revision == "0026_totp"


def test_production_mail_sender_must_use_noki_domain() -> None:
    configured = _production_settings(mail_from="Noki <no-reply@mail.noki.click>")
    assert configured.mail_from == "Noki <no-reply@mail.noki.click>"

    with pytest.raises(ValidationError, match="MAIL_FROM must use the noki.click domain"):
        _production_settings(mail_from="Noki <onboarding@resend.dev>")


def test_production_accepts_the_internal_postgres_service_hostname() -> None:
    configured = _production_settings(
        database_url="",
        postgres_host="postgres",
        postgres_port=5432,
        postgres_db="noki",
        postgres_user="noki",
        postgres_password="production-password",  # noqa: S106 - test credential
    )

    assert configured.database_url.endswith("@postgres:5432/noki")


def test_postgres_components_build_url_and_keep_password_secret() -> None:
    password = "DATABASE_COMPONENT_SECRET:/@% with spaces"  # noqa: S105 - test sentinel
    configured = Settings(
        _env_file=None,
        postgres_host="db.example.test",
        postgres_port=5544,
        postgres_db="noki_app",
        postgres_user="noki_runtime",
        postgres_password=password,
    )

    parsed = make_url(configured.database_url)

    assert parsed.drivername == "postgresql+asyncpg"
    assert parsed.host == "db.example.test"
    assert parsed.port == 5544
    assert parsed.database == "noki_app"
    assert parsed.username == "noki_runtime"
    assert parsed.password == password
    assert password not in repr(configured)
    assert password not in str(configured.model_dump())


def test_production_requires_complete_exclusive_postgres_env() -> None:
    component_values = {
        "postgres_host": "127.0.0.1",
        "postgres_port": 5432,
        "postgres_db": "noki",
        "postgres_user": "noki",
        "postgres_password": "production-component-password",
    }
    configured = _production_settings(database_url="", **component_values)
    assert make_url(configured.database_url).password == "production-component-password"  # noqa: S105

    with pytest.raises(ValidationError, match="set every POSTGRES"):
        _production_settings(
            database_url="",
            postgres_password="production-password",  # noqa: S106 - test credential
        )

    with pytest.raises(ValidationError, match="must not be configured together"):
        _production_settings(**component_values)


def test_postgres_host_normalizes_bracketed_ipv6_once() -> None:
    configured = Settings(_env_file=None, postgres_host="[::1]")

    assert configured.postgres_host == "::1"
    assert make_url(configured.database_url).host == "::1"


def test_unsafe_production_settings_fail_fast() -> None:
    with pytest.raises(ValidationError) as captured:
        _production_settings(
            database_url=("postgresql+asyncpg://noki:noki_dev_password@localhost:5432/noki"),
            jwt_secret=INSECURE_JWT_SECRET,
            data_encryption_key="not-a-key",
            backend_url="http://localhost:8000",
            frontend_url="http://localhost:3000",
            cors_origins="*",
            trusted_hosts="*",
            cookie_secure=False,
            upload_dir=Path("relative/uploads"),
        )

    message = str(captured.value)
    assert "JWT_SECRET" in message
    assert "DATA_ENCRYPTION_KEY" in message
    assert "COOKIE_SECURE" in message
    assert "UPLOAD_DIR" in message
    assert "TRUSTED_HOSTS" in message
    assert "CORS_ORIGINS" in message
    assert "must use https" in message


def test_production_validation_errors_never_echo_secret_inputs() -> None:
    sentinels = {
        "jwt": "JWT_SECRET_SENTINEL_DO_NOT_LOG",
        "data": "DATA_KEY_SENTINEL_DO_NOT_LOG",
        "database": "DATABASE_PASSWORD_SENTINEL_DO_NOT_LOG",
        "redis": "REDIS_PASSWORD_SENTINEL_DO_NOT_LOG",
        "google": "GOOGLE_SECRET_SENTINEL_DO_NOT_LOG",
    }
    with pytest.raises(ValidationError) as captured:
        _production_settings(
            jwt_secret=sentinels["jwt"],
            data_encryption_key=sentinels["data"],
            database_url=(f"postgresql+asyncpg://noki:{sentinels['database']}@db:5432/noki"),
            redis_url=f"redis://:{sentinels['redis']}@redis:6379/0",
            google_client_id="client-id",
            google_client_secret=sentinels["google"],
        )

    message = str(captured.value)
    assert "input_value" not in message
    for sentinel in sentinels.values():
        assert sentinel not in message


def test_google_redirect_must_match_backend_callback() -> None:
    with pytest.raises(ValidationError, match="GOOGLE_REDIRECT_URI"):
        _production_settings(
            google_client_id="client-id",
            google_client_secret="client-secret",  # noqa: S106 - non-secret test value
            google_redirect_uri="https://api.example.com/oauth/callback",
        )


def test_production_auth_cookies_must_remain_host_only() -> None:
    with pytest.raises(ValidationError, match="COOKIE_DOMAIN must be unset"):
        _production_settings(cookie_domain=".example.com")


@pytest.mark.parametrize(
    ("schema", "payload"),
    [
        (
            RegisterRequest,
            {
                "name": "Team Member",
                "email": "member@example.com",
                "password": "correct horse battery staple",
                "is_admin": True,
            },
        ),
        (
            LoginRequest,
            {
                "email": "member@example.com",
                "password": "password",
                "role": "owner",
            },
        ),
        (
            ChangePasswordRequest,
            {
                "old_password": "old password",
                "new_password": "correct horse battery staple",
                "new_password_confirm": "correct horse battery staple",
                "auth_version": 0,
            },
        ),
        (
            UpdateProfileRequest,
            {
                "timezone": "UTC",
                "is_active": True,
            },
        ),
    ],
)
def test_auth_request_schemas_reject_unknown_fields(
    schema: type,
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        schema.model_validate(payload)


def test_new_password_requires_content_and_must_differ_from_email() -> None:
    with pytest.raises(ValidationError, match="visible character"):
        RegisterRequest(
            name="Team Member",
            email="member@example.com",
            password=" \t\n\r\u0000\u0001" * 2,
            accept_terms=True,
            accept_privacy=True,
        )

    with pytest.raises(ValidationError, match="must not match email"):
        RegisterRequest(
            name="Team Member",
            email="member@example.com",
            password="MEMBER@EXAMPLE.COM",  # noqa: S106 - non-secret test value
            accept_terms=True,
            accept_privacy=True,
        )

    with pytest.raises(ValidationError, match="visible character"):
        ChangePasswordRequest(
            old_password="old password",  # noqa: S106 - non-secret test value
            new_password="\u0000" * 12,
            new_password_confirm="\u0000" * 12,
        )


def test_remote_data_services_require_identity_verified_transport(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="DATABASE_SSL_CA_FILE"):
        _production_settings(
            database_url=("postgresql+asyncpg://noki:production-password@db.example.com:5432/noki")
        )
    with pytest.raises(ValidationError, match="must not configure TLS"):
        _production_settings(
            database_url=(
                "postgresql+asyncpg://noki:production-password@db.example.com:5432/noki?ssl=require"
            )
        )

    with pytest.raises(ValidationError, match="remote REDIS_URL must use rediss"):
        _production_settings(
            redis_url="redis://:production-redis-password@cache.example.com:6379/0"
        )
    with pytest.raises(ValidationError, match="must not override TLS verification"):
        _production_settings(
            redis_url=(
                "rediss://:production-redis-password@cache.example.com:6380/0?ssl_cert_reqs=none"
            )
        )

    ca_file = tmp_path / "postgres-ca.pem"
    ca_file.write_text("test fixture; TLS parsing occurs when the engine starts")
    configured = _production_settings(
        database_url=("postgresql+asyncpg://noki:production-password@db.example.com:5432/noki"),
        database_ssl_ca_file=ca_file,
        redis_url="rediss://:production-redis-password@cache.example.com:6380/0",
    )
    assert configured.environment == "production"


def test_production_settings_never_fall_back_to_repository_dotenv(
    monkeypatch,
    tmp_path: Path,
) -> None:
    (tmp_path / ".env").write_text(
        "PUBLIC_REGISTRATION_ENABLED=true\nACCESS_TOKEN_MINUTES=60\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    production_environment = {
        "ENVIRONMENT": "production",
        "POSTGRES_HOST": "127.0.0.1",
        "POSTGRES_PORT": "5432",
        "POSTGRES_DB": "noki",
        "POSTGRES_USER": "noki",
        "POSTGRES_PASSWORD": "production-password",
        "REDIS_URL": "redis://:production-redis-password@127.0.0.1:6379/0",
        "JWT_SECRET": "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz!@",
        "DATA_ENCRYPTION_KEY": base64.urlsafe_b64encode(bytes(range(32))).decode(),
        "BACKEND_URL": "https://api.example.com",
        "FRONTEND_URL": "https://app.example.com",
        "CORS_ORIGINS": "https://app.example.com",
        "TRUSTED_HOSTS": "api.example.com",
        "COOKIE_SECURE": "true",
        "UPLOAD_DIR": str((tmp_path / "uploads").resolve()),
    }
    for name, value in production_environment.items():
        monkeypatch.setenv(name, value)

    get_settings.cache_clear()
    try:
        configured = get_settings()
    finally:
        get_settings.cache_clear()

    assert configured.environment == "production"
    assert make_url(configured.database_url).password == "production-password"  # noqa: S105
    assert configured.public_registration_enabled is True
    assert configured.access_token_minutes == 15


def test_pm2_routes_postgres_components_only_to_backend_processes() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    source = (repository_root / "ecosystem.config.cjs").read_text(encoding="utf-8")
    frontend_block = source[source.index("const frontendEnv") : source.index("function defaults")]

    for key in (
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
    ):
        assert key not in frontend_block
    assert "...env" in source[source.index("const sharedEnv") : source.index("const frontendEnv")]


def test_jwt_has_bound_issuer_audience_and_authentication_version() -> None:
    user_id = uuid4()
    token = security.create_access_token(user_id, auth_version=7)

    payload = security.decode_token(token, "access")

    assert payload["sub"] == str(user_id)
    assert payload["iss"] == settings.jwt_issuer
    assert payload["aud"] == settings.jwt_audience
    assert payload["ver"] == 7


def test_legacy_or_oversized_jwt_is_rejected() -> None:
    now = datetime.now(UTC)
    legacy = jwt.encode(
        {
            "sub": str(uuid4()),
            "typ": "access",
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "jti": str(uuid4()),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )

    with pytest.raises(InvalidTokenError):
        security.decode_token(legacy, "access")
    with pytest.raises(InvalidTokenError, match="too large"):
        security.decode_token("x" * (settings.max_jwt_bytes + 1), "access")


def test_refresh_token_is_bound_to_a_stable_session_family() -> None:
    user_id = uuid4()
    session_id = uuid4()
    jti = uuid4()
    token = security.create_refresh_token(user_id, jti, session_id, auth_version=2)

    payload = security.decode_token(token, "refresh")

    assert payload["sub"] == str(user_id)
    assert payload["jti"] == str(jti)
    assert payload["sid"] == str(session_id)
    assert payload["ver"] == 2


@pytest.mark.asyncio
async def test_argon2_work_is_bounded_and_queue_times_out(monkeypatch) -> None:
    release_workers = threading.Event()
    started_workers = 0
    counter_lock = threading.Lock()
    workers_ready = asyncio.Event()
    loop = asyncio.get_running_loop()

    def blocking_hash(password: str) -> str:
        nonlocal started_workers
        with counter_lock:
            started_workers += 1
            if started_workers == security.PASSWORD_WORK_CONCURRENCY:
                loop.call_soon_threadsafe(workers_ready.set)
        assert release_workers.wait(timeout=1)
        return f"hashed:{password}"

    monkeypatch.setattr(security, "hash_password", blocking_hash)
    monkeypatch.setattr(
        security,
        "password_work_semaphore",
        asyncio.Semaphore(security.PASSWORD_WORK_CONCURRENCY),
    )
    monkeypatch.setattr(settings, "password_work_queue_timeout_seconds", 0.02)

    active = [
        asyncio.create_task(security.hash_password_async("first")),
        asyncio.create_task(security.hash_password_async("second")),
    ]
    try:
        async with asyncio.timeout(1):
            await workers_ready.wait()

        with pytest.raises(security.PasswordWorkCapacityError):
            await security.hash_password_async("third")
    finally:
        release_workers.set()
        await asyncio.gather(*active)


@pytest.mark.asyncio
async def test_auth_csrf_accepts_double_submit_or_trusted_origin_only() -> None:
    csrf_token = "csrf-token-value"  # noqa: S105 - non-secret test value
    await deps.verify_auth_csrf(
        _request(
            {
                "Cookie": f"{settings.csrf_cookie_name}={csrf_token}",
                "X-CSRF-Token": csrf_token,
            }
        )
    )

    trusted_origin = settings.trusted_request_origins[0]
    await deps.verify_auth_csrf(_request({"Origin": trusted_origin}))

    with pytest.raises(HTTPException) as evil_origin:
        await deps.verify_auth_csrf(_request({"Origin": "https://evil.example"}))
    assert evil_origin.value.status_code == 403

    with pytest.raises(HTTPException) as missing_proof:
        await deps.verify_auth_csrf(_request())
    assert missing_proof.value.status_code == 403


@pytest.mark.asyncio
async def test_non_ascii_csrf_tokens_are_rejected_without_type_error() -> None:
    assert deps.safe_compare_ascii("é", "é") is False
    assert deps.safe_compare_ascii("", "") is False
    request = _request(
        {
            "Cookie": f"{settings.csrf_cookie_name}=é",
            "X-CSRF-Token": "é",
        }
    )

    with pytest.raises(HTTPException) as captured:
        await deps.verify_auth_csrf(request)
    assert captured.value.status_code == 403


class _RateLimitRedis:
    def __init__(self, count: int, ttl: int = 60) -> None:
        self.result = [count, ttl]
        self.arguments: tuple[object, ...] | None = None

    async def eval(self, *arguments: object) -> list[int]:
        self.arguments = arguments
        return self.result


@pytest.mark.asyncio
async def test_forgot_password_reports_unavailable_mail_delivery(monkeypatch) -> None:
    monkeypatch.setattr(
        settings,
        "resend_api_key",
        type(settings.resend_api_key)(""),
    )

    with pytest.raises(HTTPException) as captured:
        await auth.forgot_password(
            payload=EmailRequest(email="member@example.com"),
            request=_request(),
            db=object(),  # type: ignore[arg-type]
            redis=_RateLimitRedis(1),  # type: ignore[arg-type]
        )

    assert captured.value.status_code == 503
    assert captured.value.detail == "Password reset email is temporarily unavailable"


@pytest.mark.asyncio
async def test_forgot_password_can_create_a_password_for_google_only_account(
    monkeypatch,
) -> None:
    user = User(
        id=uuid4(),
        email="member@example.com",
        name="Google Member",
        google_sub="google-subject",
        password_hash=None,
        email_verified_at=datetime.now(UTC),
        is_active=True,
    )

    class ForgotPasswordDB:
        committed = False

        async def scalar(self, statement: object) -> User:
            return user

        async def commit(self) -> None:
            self.committed = True

    token_id = uuid4()

    async def fake_issue_token(*args, **kwargs):
        return SimpleNamespace(id=token_id), "r" * 48

    sent_mail: list[dict[str, object]] = []
    monkeypatch.setattr(
        settings,
        "resend_api_key",
        type(settings.resend_api_key)("configured-test-key"),
    )
    monkeypatch.setattr(auth, "issue_one_time_token", fake_issue_token)

    def fake_send_mail(**kwargs) -> str:
        sent_mail.append(kwargs)
        return "resend-message-id"

    monkeypatch.setattr(auth, "send_mail", fake_send_mail)
    db = ForgotPasswordDB()

    response = await auth.forgot_password(
        payload=EmailRequest(email=user.email),
        request=_request(),
        db=db,  # type: ignore[arg-type]
        redis=_RateLimitRedis(1),  # type: ignore[arg-type]
    )

    assert db.committed is True
    assert response.message == "If the account exists, a password reset email was sent"
    assert sent_mail == [
        {
            "recipient": user.email,
            "kind": "reset_password",
            "context": {
                "name": user.name,
                "action_url": f"{settings.frontend_url}/reset-password?token={'r' * 48}",
            },
            "idempotency_key": f"reset-password/{token_id}",
        }
    ]


@pytest.mark.asyncio
async def test_reset_password_consumes_token_updates_password_and_revokes_sessions(
    monkeypatch,
) -> None:
    user = User(
        id=uuid4(),
        email="member@example.com",
        name="Member",
        password_hash="old-password-hash",
        email_verified_at=datetime.now(UTC),
        is_active=True,
        auth_version=4,
    )
    token = OneTimeToken(
        id=uuid4(),
        user_id=user.id,
        purpose="reset_password",
        token_hash="a" * 64,
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
    )

    class ResetPasswordDB:
        def __init__(self) -> None:
            self.scalar_results = [token, user]
            self.executed: list[object] = []
            self.committed = False

        async def scalar(self, statement: object) -> object:
            return self.scalar_results.pop(0)

        async def execute(self, statement: object) -> None:
            self.executed.append(statement)

        async def commit(self) -> None:
            self.committed = True

    async def fake_hash_password(password: str) -> str:
        assert password == "a-new-secure-password"
        return "new-password-hash"

    monkeypatch.setattr(auth, "hash_password_async", fake_hash_password)
    db = ResetPasswordDB()
    response = Response()

    result = await auth.reset_password(
        payload=ResetPasswordRequest(
            token="r" * 43,
            new_password="a-new-secure-password",
            new_password_confirm="a-new-secure-password",
        ),
        response=response,
        db=db,  # type: ignore[arg-type]
    )

    assert result.message == "Password changed; sign in again"
    assert token.consumed_at is not None
    assert user.password_hash == "new-password-hash"
    assert user.auth_version == 5
    assert len(db.executed) == 1
    assert db.committed is True
    assert response.headers.getlist("set-cookie")


@pytest.mark.asyncio
async def test_reset_password_rejects_invalid_token_before_hashing(monkeypatch) -> None:
    class InvalidTokenDB:
        async def scalar(self, statement: object) -> None:
            return None

    async def unexpected_hash_password(password: str) -> str:
        pytest.fail("an invalid token must not trigger password hashing")

    monkeypatch.setattr(auth, "hash_password_async", unexpected_hash_password)

    with pytest.raises(HTTPException) as captured:
        await auth.reset_password(
            payload=ResetPasswordRequest(
                token="x" * 43,
                new_password="a-new-secure-password",
                new_password_confirm="a-new-secure-password",
            ),
            response=Response(),
            db=InvalidTokenDB(),  # type: ignore[arg-type]
        )

    assert captured.value.status_code == 400
    assert captured.value.detail == "Reset link is invalid or expired"


class _LeaseRedis:
    def __init__(self, acquired: bool) -> None:
        self.acquired = acquired
        self.set_arguments: tuple[object, ...] | None = None
        self.eval_arguments: tuple[object, ...] | None = None

    async def set(self, *arguments: object, **kwargs: object) -> bool:
        self.set_arguments = (*arguments, kwargs)
        return self.acquired

    async def eval(self, *arguments: object) -> int:
        self.eval_arguments = arguments
        return 1


@pytest.mark.asyncio
async def test_rate_limit_is_atomic_hides_identifier_and_sets_retry_after() -> None:
    identifier = "person@example.com"
    allowed = _RateLimitRedis(2)
    await deps.enforce_rate_limit(
        allowed,
        scope="login-account",
        identifier=identifier,
        limit=2,
        window_seconds=300,
    )

    assert allowed.arguments is not None
    assert allowed.arguments[1] == 1
    assert identifier not in str(allowed.arguments[2])

    blocked = _RateLimitRedis(3, ttl=42)
    with pytest.raises(HTTPException) as captured:
        await deps.enforce_rate_limit(
            blocked,
            scope="login-account",
            identifier=identifier,
            limit=2,
            window_seconds=300,
        )
    assert captured.value.status_code == 429
    assert captured.value.headers == {"Retry-After": "42"}


@pytest.mark.asyncio
async def test_distributed_lease_is_hashed_bounded_and_owner_safe() -> None:
    identifier = "private-user-id"
    redis = _LeaseRedis(acquired=True)
    token = await deps.acquire_distributed_lease(
        redis,  # type: ignore[arg-type]
        scope="upload-user",
        identifier=identifier,
        ttl_seconds=1.2,
    )
    await deps.release_distributed_lease(
        redis,  # type: ignore[arg-type]
        scope="upload-user",
        identifier=identifier,
        token=token,
    )

    assert redis.set_arguments is not None
    assert identifier not in str(redis.set_arguments[0])
    assert redis.set_arguments[-1] == {"ex": 2, "nx": True}
    assert redis.eval_arguments is not None
    assert redis.eval_arguments[-1] == token
    assert 'redis.call("GET"' in str(redis.eval_arguments[0])


@pytest.mark.asyncio
async def test_distributed_lease_rejects_concurrent_owner() -> None:
    redis = _LeaseRedis(acquired=False)
    with pytest.raises(HTTPException) as captured:
        await deps.acquire_distributed_lease(
            redis,  # type: ignore[arg-type]
            scope="upload-user",
            identifier="private-user-id",
            ttl_seconds=30,
        )
    assert captured.value.status_code == 429
    assert captured.value.headers == {"Retry-After": "30"}


def test_rate_limit_client_id_does_not_trust_spoofed_forwarded_header() -> None:
    request = _request(
        {"X-Forwarded-For": "198.51.100.44"},
        client_host="203.0.113.20",
    )
    assert deps.client_rate_limit_id(request) == "203.0.113.20"


class _LoginRedis:
    def __init__(self, account_failure_count: int = 0) -> None:
        self.account_failure_count = account_failure_count
        self.keys: list[str] = []
        self.deleted: list[str] = []

    async def eval(
        self,
        script: str,
        key_count: int,
        key: str,
        *arguments: object,
    ) -> list[int]:
        assert key_count == 1
        self.keys.append(key)
        if ":login-account:" in key:
            return [self.account_failure_count, 300]
        return [1, 300]

    async def delete(self, key: str) -> None:
        self.deleted.append(key)


class _LoginDB:
    def __init__(self, user: User | None, locked_user: User | None = None) -> None:
        self.user = user
        self.locked_user = locked_user if locked_user is not None else user
        self.scalar_calls = 0
        self.committed = False
        self.rolled_back = False

    async def scalar(self, statement: object) -> User | None:
        self.scalar_calls += 1
        return self.user if self.scalar_calls == 1 else self.locked_user

    async def rollback(self) -> None:
        self.rolled_back = True

    async def commit(self) -> None:
        self.committed = True


@pytest.mark.asyncio
async def test_login_account_limit_blocks_before_password_verification(
    monkeypatch,
) -> None:
    user = User(
        id=uuid4(),
        email="member@example.com",
        name="Team Member",
        password_hash="argon-hash",  # noqa: S106 - non-secret test value
        google_sub=None,
        is_active=True,
        auth_version=0,
        timezone="UTC",
        created_at=datetime.now(UTC),
    )

    password_checked = False

    async def password_is_valid(password: str, password_hash: str) -> bool:
        nonlocal password_checked
        password_checked = True
        return True

    async def fake_issue_tokens(db: object, token_user: User) -> SimpleNamespace:
        assert token_user is user
        return SimpleNamespace(
            access_token="access-token",  # noqa: S106 - non-secret test value
            refresh_token="refresh-token",  # noqa: S106 - non-secret test value
            csrf_token="csrf-token",  # noqa: S106 - non-secret test value
        )

    monkeypatch.setattr(auth, "verify_password_async", password_is_valid)
    monkeypatch.setattr(auth, "password_needs_rehash", lambda password_hash: False)
    monkeypatch.setattr(auth, "issue_tokens", fake_issue_tokens)
    redis = _LoginRedis(account_failure_count=settings.login_rate_limit_attempts + 1)
    db = _LoginDB(user)

    with pytest.raises(HTTPException) as captured:
        await auth.login(
            payload=LoginRequest(
                email="member@example.com",
                password="correct horse battery staple",  # noqa: S106 - test value
            ),
            request=_request(),
            response=Response(),
            db=db,  # type: ignore[arg-type]
            redis=redis,  # type: ignore[arg-type]
        )

    assert captured.value.status_code == 429
    assert password_checked is False
    assert db.scalar_calls == 0
    assert any(":login-account:" in key for key in redis.keys)


@pytest.mark.asyncio
async def test_failed_login_increments_ip_and_account_limits(monkeypatch) -> None:
    async def password_is_invalid(password: str, password_hash: str) -> bool:
        return False

    monkeypatch.setattr(auth, "verify_password_async", password_is_invalid)
    redis = _LoginRedis(account_failure_count=settings.login_rate_limit_attempts)

    with pytest.raises(HTTPException) as captured:
        await auth.login(
            payload=LoginRequest(
                email="missing@example.com",
                password="wrong password",  # noqa: S106 - non-secret test value
            ),
            request=_request(),
            response=Response(),
            db=_LoginDB(None),  # type: ignore[arg-type]
            redis=redis,  # type: ignore[arg-type]
        )

    assert captured.value.status_code == 401
    assert any(":login-ip:" in key for key in redis.keys)
    assert any(":login-account:" in key for key in redis.keys)


@pytest.mark.asyncio
async def test_login_rejects_password_changed_during_verification(monkeypatch) -> None:
    user_id = uuid4()
    snapshot = User(
        id=user_id,
        email="member@example.com",
        name="Team Member",
        password_hash="old-argon-hash",  # noqa: S106 - non-secret test value
        google_sub=None,
        is_active=True,
        auth_version=0,
    )
    locked = User(
        id=user_id,
        email="member@example.com",
        name="Team Member",
        password_hash="new-argon-hash",  # noqa: S106 - non-secret test value
        google_sub=None,
        is_active=True,
        auth_version=1,
    )

    async def old_password_was_valid(password: str, password_hash: str) -> bool:
        return True

    monkeypatch.setattr(auth, "verify_password_async", old_password_was_valid)
    db = _LoginDB(snapshot, locked)

    with pytest.raises(HTTPException) as captured:
        await auth.login(
            payload=LoginRequest(
                email="member@example.com",
                password="old valid password",  # noqa: S106 - non-secret test value
            ),
            request=_request(),
            response=Response(),
            db=db,  # type: ignore[arg-type]
            redis=_LoginRedis(),  # type: ignore[arg-type]
        )

    assert captured.value.status_code == 401
    assert db.rolled_back is True
    assert db.committed is False


class _OAuthRedis(_RateLimitRedis):
    def __init__(self) -> None:
        super().__init__(1)
        self.state_key: str | None = None
        self.state_value: str | None = None

    async def setex(self, key: str, ttl: int, value: str) -> None:
        assert ttl == 300
        self.state_key = key
        self.state_value = value

    async def getdel(self, key: str) -> str:
        self.state_key = key
        return "1"


@pytest.mark.asyncio
async def test_google_start_binds_state_to_http_only_browser_cookie(monkeypatch) -> None:
    monkeypatch.setattr(settings, "google_client_id", "client-id")
    monkeypatch.setattr(settings, "google_client_secret", "client-secret")
    redis = _OAuthRedis()

    response = await auth.google_login(_request(), redis)  # type: ignore[arg-type]

    query = parse_qs(urlsplit(response.headers["location"]).query)
    state = query["state"][0]
    set_cookie = response.headers["set-cookie"]
    assert redis.state_key == f"oauth:google:{state}"
    assert redis.state_value == "1"
    assert f"{settings.oauth_state_cookie_name}={state}" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert f"Path={settings.api_v1_prefix}/auth/google/callback" in set_cookie


@pytest.mark.asyncio
async def test_google_password_setup_start_preserves_the_validated_action(monkeypatch) -> None:
    monkeypatch.setattr(settings, "google_client_id", "client-id")
    monkeypatch.setattr(settings, "google_client_secret", "client-secret")
    redis = _OAuthRedis()

    await auth.google_login(  # type: ignore[arg-type]
        _request(),
        redis,
        action="set_password",
    )

    assert redis.state_value == "set_password"


def test_google_reauthentication_cookie_is_signed_bound_and_http_only() -> None:
    user_id = uuid4()
    token = security.create_google_reauth_token(user_id, auth_version=7)
    payload = security.decode_token(token, "google_reauth")
    response = Response()

    security.set_google_reauth_cookie(response, token)

    assert payload["sub"] == str(user_id)
    assert payload["ver"] == 7
    set_cookie = response.headers["set-cookie"]
    assert f"{security.GOOGLE_REAUTH_COOKIE_NAME}={token}" in set_cookie
    assert "HttpOnly" in set_cookie
    assert f"Max-Age={security.GOOGLE_REAUTH_TTL_SECONDS}" in set_cookie
    assert "SameSite=lax" in set_cookie


@pytest.mark.asyncio
async def test_google_network_and_oversized_responses_fail_safely(monkeypatch) -> None:
    real_async_client = httpx.AsyncClient

    def unavailable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("upstream offline", request=request)

    unavailable_transport = httpx.MockTransport(unavailable)
    monkeypatch.setattr(
        oauth.httpx,
        "AsyncClient",
        lambda **kwargs: real_async_client(
            transport=unavailable_transport,
            timeout=kwargs["timeout"],
            limits=kwargs["limits"],
        ),
    )
    with pytest.raises(
        oauth.GoogleOAuthUnavailableError,
        match="temporarily unavailable",
    ):
        await oauth.fetch_google_identity("authorization-code")

    def oversized(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"x" * (oauth.GOOGLE_RESPONSE_MAX_BYTES + 1),
            request=request,
        )

    oversized_transport = httpx.MockTransport(oversized)
    monkeypatch.setattr(
        oauth.httpx,
        "AsyncClient",
        lambda **kwargs: real_async_client(
            transport=oversized_transport,
            timeout=kwargs["timeout"],
            limits=kwargs["limits"],
        ),
    )
    with pytest.raises(oauth.GoogleOAuthUnavailableError, match="oversized"):
        await oauth.fetch_google_identity("authorization-code")


class _ExistingEmailDB:
    def __init__(self, existing_user: object) -> None:
        self.results = iter((None, existing_user))
        self.added: list[object] = []
        self.committed = False

    async def scalar(self, statement: object) -> object:
        return next(self.results)

    def add(self, value: object) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        self.committed = True


@pytest.mark.asyncio
async def test_google_callback_links_existing_password_account(monkeypatch) -> None:
    async def fake_identity(code: str) -> GoogleIdentity:
        assert code == "authorization-code"
        return GoogleIdentity(
            sub="google-subject",
            email="member@example.com",
            name="Team Member",
        )

    async def ignore_invitations(*args, **kwargs) -> int:
        return 0

    async def fake_tokens(*args, **kwargs) -> object:
        return SimpleNamespace(
            access_token="access-token",  # noqa: S106 - non-secret test token
            refresh_token="refresh-token",  # noqa: S106 - non-secret test token
            csrf_token="csrf-token",  # noqa: S106 - non-secret test token
        )

    monkeypatch.setattr(auth, "fetch_google_identity", fake_identity)
    monkeypatch.setattr(auth, "accept_matching_invitations", ignore_invitations)
    monkeypatch.setattr(auth, "issue_tokens", fake_tokens)
    state = "s" * 32
    existing_user = User(
        id=uuid4(),
        email="member@example.com",
        name="Existing Member",
        password_hash="existing-password-hash",  # noqa: S106 - non-secret test value
        email_verified_at=datetime.now(UTC),
        is_active=True,
    )
    db = _ExistingEmailDB(existing_user)
    original_password_hash = existing_user.password_hash

    response = await auth.google_callback(
        request=_request(),
        db=db,  # type: ignore[arg-type]
        redis=_OAuthRedis(),  # type: ignore[arg-type]
        code="authorization-code",
        state=state,
        oauth_state=state,
    )

    assert response.status_code == 302
    assert response.headers["location"] == f"{settings.frontend_url}/app"
    assert settings.oauth_state_cookie_name in response.headers["set-cookie"]
    assert existing_user.google_sub == "google-subject"
    assert existing_user.password_hash == original_password_hash
    assert db.committed is True
    assert db.added == []


@pytest.mark.asyncio
async def test_google_callback_rejects_a_different_linked_google_identity(monkeypatch) -> None:
    async def fake_identity(code: str) -> GoogleIdentity:
        return GoogleIdentity(
            sub="new-google-subject",
            email="member@example.com",
            name="Team Member",
        )

    monkeypatch.setattr(auth, "fetch_google_identity", fake_identity)
    existing_user = User(
        id=uuid4(),
        email="member@example.com",
        name="Existing Member",
        google_sub="original-google-subject",
        password_hash="existing-password-hash",  # noqa: S106 - non-secret test value
        email_verified_at=datetime.now(UTC),
        is_active=True,
    )
    db = _ExistingEmailDB(existing_user)
    state = "s" * 32

    response = await auth.google_callback(
        request=_request(),
        db=db,  # type: ignore[arg-type]
        redis=_OAuthRedis(),  # type: ignore[arg-type]
        code="authorization-code",
        state=state,
        oauth_state=state,
    )

    assert response.status_code == 302
    assert response.headers["location"] == (
        f"{settings.frontend_url}/login?oauth_error=google_identity_conflict"
    )
    assert existing_user.google_sub == "original-google-subject"
    assert db.committed is False


@pytest.mark.asyncio
async def test_non_ascii_oauth_state_is_rejected_without_type_error() -> None:
    state = "é" * 16
    with pytest.raises(HTTPException) as captured:
        await auth.google_callback(
            request=_request(),
            db=object(),  # type: ignore[arg-type]
            redis=_OAuthRedis(),  # type: ignore[arg-type]
            code="authorization-code",
            state=state,
            oauth_state=state,
        )
    assert captured.value.status_code == 400


class _UserDB:
    def __init__(self, user: User) -> None:
        self.user = user

    async def get(self, model: type[User], user_id: UUID) -> User:
        assert model is User
        assert user_id == self.user.id
        return self.user


@pytest.mark.asyncio
async def test_auth_version_immediately_revokes_stateless_access_token() -> None:
    user_id = uuid4()
    token = security.create_access_token(user_id, auth_version=4)
    user = User(
        id=user_id,
        email="member@example.com",
        name="Team Member",
        password_hash=None,
        google_sub="google-subject",
        is_active=True,
        auth_version=5,
    )
    request = _request({"Cookie": f"{settings.access_cookie_name}={token}"})

    with pytest.raises(HTTPException) as captured:
        await deps.get_current_user(request, _UserDB(user))  # type: ignore[arg-type]
    assert captured.value.status_code == 401
    assert "revoked" in captured.value.detail


def test_user_metadata_contains_auth_version_integrity_constraint() -> None:
    constraint_names = {
        constraint.name
        for constraint in User.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "ck_users_auth_version_nonnegative" in constraint_names


class _ScalarRows:
    def __init__(self, values: list[UUID]) -> None:
        self.values = values

    def all(self) -> list[UUID]:
        return self.values


class _TokenDB:
    def __init__(self, session_ids: list[UUID]) -> None:
        self.session_ids = session_ids
        self.executed: list[object] = []
        self.added: list[object] = []
        self.flush_count = 0

    async def flush(self) -> None:
        self.flush_count += 1

    async def execute(self, statement: object) -> None:
        self.executed.append(statement)

    async def scalars(self, statement: object) -> _ScalarRows:
        return _ScalarRows(self.session_ids)

    def add(self, value: object) -> None:
        self.added.append(value)


@pytest.mark.asyncio
async def test_token_issuance_keeps_per_user_session_rows_bounded(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_sessions_per_user", 2)
    user = User(
        id=uuid4(),
        email="member@example.com",
        name="Team Member",
        password_hash="argon-hash",  # noqa: S106 - non-secret test value
        google_sub=None,
        is_active=True,
        auth_version=3,
    )
    db = _TokenDB([uuid4(), uuid4()])

    tokens = await issue_tokens(db, user)  # type: ignore[arg-type]

    assert db.flush_count == 2
    assert any("DELETE FROM user_sessions" in str(statement) for statement in db.executed)
    assert len(db.added) == 1
    assert isinstance(db.added[0], UserSession)
    assert security.decode_token(tokens.access_token, "access")["ver"] == 3
    refresh_payload = security.decode_token(tokens.refresh_token, "refresh")
    assert refresh_payload["sid"] == str(db.added[0].id)


@pytest.mark.asyncio
async def test_token_rotation_reuses_family_row_with_an_absolute_expiration() -> None:
    user = User(
        id=uuid4(),
        email="member@example.com",
        name="Team Member",
        password_hash="argon-hash",  # noqa: S106 - non-secret test value
        google_sub=None,
        is_active=True,
        auth_version=3,
    )
    old_jti = uuid4()
    session = UserSession(
        id=uuid4(),
        user_id=user.id,
        refresh_jti=old_jti,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    absolute_expiration = session.expires_at
    db = _TokenDB([])

    tokens = await issue_tokens(db, user, session=session)  # type: ignore[arg-type]

    assert db.added == []
    assert session.refresh_jti != old_jti
    assert session.expires_at == absolute_expiration
    payload = security.decode_token(tokens.refresh_token, "refresh")
    assert payload["sid"] == str(session.id)
    assert payload["jti"] == str(session.refresh_jti)
    token_expiration = datetime.fromtimestamp(payload["exp"], UTC)
    assert abs((token_expiration - absolute_expiration).total_seconds()) < 1


class _RefreshDB:
    def __init__(self, user: User, session: UserSession) -> None:
        self.user = user
        self.session = session
        self.scalar_calls = 0
        self.deleted: list[object] = []
        self.committed = False

    async def scalar(self, statement: object) -> object:
        self.scalar_calls += 1
        return self.user if self.scalar_calls == 1 else self.session

    async def delete(self, value: object) -> None:
        self.deleted.append(value)

    async def commit(self) -> None:
        self.committed = True


def _refresh_family(
    *,
    session_user_id: UUID | None = None,
) -> tuple[User, UserSession, UUID]:
    user = User(
        id=uuid4(),
        email="member@example.com",
        name="Team Member",
        password_hash="argon-hash",  # noqa: S106 - non-secret test value
        google_sub=None,
        is_active=True,
        auth_version=3,
    )
    previous_jti = uuid4()
    session = UserSession(
        id=uuid4(),
        user_id=session_user_id or user.id,
        refresh_jti=uuid4(),
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    return user, session, previous_jti


@pytest.mark.asyncio
async def test_stale_refresh_replay_revokes_attackers_current_family() -> None:
    user, session, stolen_jti = _refresh_family()
    db = _RefreshDB(user, session)
    token = security.create_refresh_token(
        user.id,
        stolen_jti,
        session.id,
        auth_version=user.auth_version,
    )
    response = Response()

    with pytest.raises(HTTPException) as captured:
        await auth.refresh_session(
            request=_request(),
            response=response,
            db=db,  # type: ignore[arg-type]
            redis=_LoginRedis(),  # type: ignore[arg-type]
            _=None,
            refresh_token=token,
        )

    assert captured.value.status_code == 401
    assert "reuse" in captured.value.detail
    assert db.deleted == [session]
    assert db.committed is True
    assert any(
        header == b"set-cookie" and b"Max-Age=0" in value for header, value in response.raw_headers
    )


@pytest.mark.asyncio
async def test_refresh_family_cannot_cross_user_boundary() -> None:
    user, session, previous_jti = _refresh_family(session_user_id=uuid4())
    db = _RefreshDB(user, session)
    token = security.create_refresh_token(
        user.id,
        previous_jti,
        session.id,
        auth_version=user.auth_version,
    )

    with pytest.raises(HTTPException) as captured:
        await auth.refresh_session(
            request=_request(),
            response=Response(),
            db=db,  # type: ignore[arg-type]
            redis=_LoginRedis(),  # type: ignore[arg-type]
            _=None,
            refresh_token=token,
        )

    assert captured.value.status_code == 401
    assert db.deleted == []
    assert db.committed is False


class _PasswordChangeDB:
    def __init__(self, user: User) -> None:
        self.user = user
        self.executed: list[object] = []
        self.committed = False

    async def scalar(self, statement: object) -> User:
        return self.user

    async def execute(self, statement: object) -> None:
        self.executed.append(statement)

    async def commit(self) -> None:
        self.committed = True


def _google_only_user() -> User:
    return User(
        id=uuid4(),
        email="member@example.com",
        name="Team Member",
        password_hash=None,
        google_sub="google-subject",
        is_active=True,
        auth_version=0,
        timezone="UTC",
        created_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_google_only_password_setup_rejects_forgeable_marker_cookie() -> None:
    user = _google_only_user()
    db = _PasswordChangeDB(user)

    with pytest.raises(HTTPException) as captured:
        await users.change_password(
            payload=ChangePasswordRequest(
                old_password=None,
                new_password="correct horse battery staple",  # noqa: S106 - test value
                new_password_confirm="correct horse battery staple",  # noqa: S106
            ),
            request=_request({"Cookie": f"{security.GOOGLE_REAUTH_COOKIE_NAME}=1"}),
            response=Response(),
            current_user=user,
            db=db,  # type: ignore[arg-type]
            redis=_LoginRedis(),  # type: ignore[arg-type]
            _=None,
        )

    assert captured.value.status_code == 403
    assert user.password_hash is None
    assert db.committed is False


@pytest.mark.asyncio
async def test_google_only_password_setup_accepts_bound_reauthentication(
    monkeypatch,
) -> None:
    user = _google_only_user()
    db = _PasswordChangeDB(user)
    token = security.create_google_reauth_token(user.id, user.auth_version)
    response = Response()

    async def fake_hash(password: str) -> str:
        assert password == "correct horse battery staple"  # noqa: S105 - test value
        return "new-argon-hash"

    monkeypatch.setattr(users, "hash_password_async", fake_hash)

    result = await users.change_password(
        payload=ChangePasswordRequest(
            old_password=None,
            new_password="correct horse battery staple",  # noqa: S106 - test value
            new_password_confirm="correct horse battery staple",  # noqa: S106
        ),
        request=_request({"Cookie": f"{security.GOOGLE_REAUTH_COOKIE_NAME}={token}"}),
        response=response,
        current_user=user,
        db=db,  # type: ignore[arg-type]
        redis=_LoginRedis(),  # type: ignore[arg-type]
        _=None,
    )

    assert result.message == "Password changed"
    assert user.password_hash == "new-argon-hash"  # noqa: S105 - test value
    assert user.auth_version == 1
    assert db.committed is True
    assert db.executed
    assert any(
        header == b"set-cookie"
        and security.GOOGLE_REAUTH_COOKIE_NAME.encode() in value
        and b"Max-Age=0" in value
        for header, value in response.raw_headers
    )
