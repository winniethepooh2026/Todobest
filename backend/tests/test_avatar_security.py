from __future__ import annotations

import base64
import hashlib
import io
import struct
import sys
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from botocore.exceptions import ClientError
from fastapi import HTTPException
from PIL import Image, PngImagePlugin
from pydantic import SecretStr, ValidationError
from starlette.requests import Request

from app.api.routes import auth as auth_routes
from app.api.routes import avatars as avatar_routes
from app.core.config import Settings, settings
from app.services import antivirus, avatar_processing, avatars, oauth, object_storage
from app.services.antivirus import MalwareDetectedError, MalwareScannerUnavailableError
from app.services.avatar_processing import InvalidAvatarError
from app.services.object_storage import (
    AVATAR_CACHE_CONTROL,
    AvatarObjectNotFoundError,
    AvatarStorageError,
    OpenedAvatarObject,
)

_REAL_ASYNC_CLIENT = httpx.AsyncClient


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
        "clamav_unix_socket": Path("/run/clamav/clamd.ctl"),
    }
    values.update(overrides)
    return Settings(**values)


def _enable_avatar_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "aws_access_key_id", "test-access-key")
    monkeypatch.setattr(settings, "aws_secret_access_key", SecretStr("test-secret-key"))
    monkeypatch.setattr(settings, "aws_storage_bucket_name", "noki-private-avatars")
    monkeypatch.setattr(settings, "aws_s3_endpoint_url", "https://s3.example.com")
    monkeypatch.setattr(settings, "aws_s3_region_name", "us-east-1")


def _image_bytes(
    image_format: str,
    *,
    size: tuple[int, int] = (48, 32),
    color: str = "#315efb",
) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, image_format)
    return output.getvalue()


def _request(headers: dict[str, str] | None = None) -> Request:
    raw_headers = [
        (name.lower().encode("ascii"), value.encode("latin-1"))
        for name, value in (headers or {}).items()
    ]
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "https",
            "path": "/api/v1/media/avatars/test",
            "raw_path": b"/api/v1/media/avatars/test",
            "query_string": b"",
            "headers": raw_headers,
            "client": ("203.0.113.10", 54321),
            "server": ("api.example.com", 443),
        }
    )


@pytest.fixture(autouse=True)
def _reset_avatar_memory_cache() -> Iterator[None]:
    object_storage.clear_avatar_memory_cache()
    yield
    object_storage.clear_avatar_memory_cache()


@pytest.mark.parametrize(
    "missing_key",
    [
        "aws_access_key_id",
        "aws_secret_access_key",
        "aws_storage_bucket_name",
        "aws_s3_endpoint_url",
    ],
)
def test_s3_settings_are_all_or_none(missing_key: str) -> None:
    values: dict[str, object] = {
        "_env_file": None,
        "aws_access_key_id": "access-key",
        "aws_secret_access_key": "secret-key",
        "aws_storage_bucket_name": "noki-private-avatars",
        "aws_s3_endpoint_url": "https://s3.example.com",
    }
    values.pop(missing_key)

    with pytest.raises(ValidationError, match="must be configured together"):
        Settings(**values)


def test_s3_secret_is_secretstr_and_never_leaks_from_validation_errors() -> None:
    sentinel = "S3_SECRET_SENTINEL_DO_NOT_LOG"
    configured = Settings(
        _env_file=None,
        aws_access_key_id="access-key",
        aws_secret_access_key=sentinel,
        aws_storage_bucket_name="noki-private-avatars",
        aws_s3_endpoint_url="https://s3.example.com",
    )

    assert isinstance(configured.aws_secret_access_key, SecretStr)
    assert configured.aws_secret_access_key.get_secret_value() == sentinel
    assert sentinel not in repr(configured)

    with pytest.raises(ValidationError) as captured:
        _production_settings(
            aws_access_key_id="access-key",
            aws_secret_access_key=sentinel,
            aws_storage_bucket_name="INVALID_BUCKET",
            aws_s3_endpoint_url="https://s3.example.com",
        )
    assert sentinel not in str(captured.value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("aws_access_key_id", "access key"),
        ("aws_access_key_id", "access-кey"),
        ("aws_secret_access_key", "secret key"),
        ("aws_secret_access_key", "secret\tkey"),
    ],
)
def test_s3_credentials_reject_whitespace_and_non_ascii(
    field: str,
    value: str,
) -> None:
    values: dict[str, object] = {
        "_env_file": None,
        "aws_access_key_id": "access-key",
        "aws_secret_access_key": "secret-key",
        "aws_storage_bucket_name": "noki-private-avatars",
        "aws_s3_endpoint_url": "https://s3.example.com",
    }
    values[field] = value

    with pytest.raises(ValidationError, match="invalid characters"):
        Settings(**values)


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://s3.example.com",
        "https://user:password@s3.example.com",
        "https://s3.example.com/path",
        "https://s3.example.com?tls=false",
        "https://127.0.0.1",
    ],
)
def test_production_s3_endpoint_is_strict_https_origin(endpoint: str) -> None:
    with pytest.raises(ValidationError, match="AWS_S3_ENDPOINT_URL"):
        _production_settings(
            aws_access_key_id="access-key",
            aws_secret_access_key="secret-key",  # noqa: S106 - test credential
            aws_storage_bucket_name="noki-private-avatars",
            aws_s3_endpoint_url=endpoint,
        )


@pytest.mark.parametrize(
    "bucket",
    ["INVALID_BUCKET", "ab", "192.0.2.1", "noki..avatars", "noki.-avatars"],
)
def test_s3_bucket_name_is_validated(bucket: str) -> None:
    with pytest.raises(ValidationError, match="AWS_STORAGE_BUCKET_NAME"):
        Settings(
            _env_file=None,
            aws_access_key_id="access-key",
            aws_secret_access_key="secret-key",  # noqa: S106 - test credential
            aws_storage_bucket_name=bucket,
            aws_s3_endpoint_url="https://s3.example.com",
        )


def test_pm2_does_not_route_s3_secrets_to_frontend() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    source = (repository_root / "ecosystem.config.cjs").read_text(encoding="utf-8")
    frontend_block = source[source.index("const frontendEnv") : source.index("function defaults")]

    assert "AWS_SECRET_ACCESS_KEY" not in frontend_block
    assert "POSTGRES_PASSWORD" not in frontend_block
    assert 'defaults("noki-worker", "512M")' in source
    assert 'defaults("noki-beat", "256M")' in source


def test_avatar_malware_scan_mode_rejects_implicit_bypass() -> None:
    with pytest.raises(ValidationError, match="avatar_malware_scan_mode"):
        Settings(_env_file=None, avatar_malware_scan_mode="disabled")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (
            "https://lh4.googleusercontent.com/a-/photo=s256-c",
            "https://lh4.googleusercontent.com/a-/photo=s256-c",
        ),
        (
            "https://images.googleusercontent.com/avatar?id=1",
            "https://images.googleusercontent.com/avatar?id=1",
        ),
    ],
)
def test_google_picture_url_accepts_only_optional_google_https_urls(
    value: object,
    expected: str | None,
) -> None:
    assert avatar_processing.validate_google_picture_url(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        123,
        "",
        " http://lh4.googleusercontent.com/photo",
        "http://lh4.googleusercontent.com/photo",
        "https://googleusercontent.com/photo",
        "https://lh4.googleusercontent.com.evil.example/photo",
        "https://user@lh4.googleusercontent.com/photo",
        "https://lh4.googleusercontent.com:8443/photo",
        "https://lh4.googleusercontent.com/photo#fragment",
        "https://lh4.googleusercontent.com/photo\n",
        "https://lh4.googleusercontent.com/фото",
    ],
)
def test_google_picture_url_rejects_ssrf_and_ambiguous_values(value: object) -> None:
    with pytest.raises(InvalidAvatarError):
        avatar_processing.validate_google_picture_url(value)


def _install_google_oauth_transport(
    monkeypatch: pytest.MonkeyPatch,
    *,
    picture: object = None,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == oauth.GOOGLE_TOKEN_URL:
            return httpx.Response(200, json={"access_token": "access-token"}, request=request)
        if str(request.url) == oauth.GOOGLE_USERINFO_URL:
            profile: dict[str, object] = {
                "sub": "google-subject",
                "email": "member@example.com",
                "email_verified": True,
                "name": "Team Member",
            }
            if picture is not None:
                profile["picture"] = picture
            return httpx.Response(200, json=profile, request=request)
        raise AssertionError(f"Unexpected Google request: {request.url}")

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        oauth.httpx,
        "AsyncClient",
        lambda **kwargs: _REAL_ASYNC_CLIENT(transport=transport, **kwargs),
    )


async def test_google_identity_preserves_a_valid_picture_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    picture_url = "https://lh3.googleusercontent.com/a/profile=s256-c"
    _install_google_oauth_transport(monkeypatch, picture=picture_url)

    identity = await oauth.fetch_google_identity("authorization-code")

    assert identity.picture_url == picture_url


@pytest.mark.parametrize(
    "picture",
    ["https://evil.example/avatar.png", "http://lh3.googleusercontent.com/avatar", 42],
)
async def test_invalid_optional_google_picture_never_breaks_authentication(
    monkeypatch: pytest.MonkeyPatch,
    picture: object,
) -> None:
    _install_google_oauth_transport(monkeypatch, picture=picture)

    identity = await oauth.fetch_google_identity("authorization-code")

    assert identity.email == "member@example.com"
    assert identity.picture_url is None


class _OAuthRedis:
    async def getdel(self, _key: str) -> str:
        return "1"


class _GoogleCallbackDB:
    def __init__(self, user: object) -> None:
        self.user = user
        self.committed = False

    async def scalar(self, _statement: object) -> object:
        return self.user

    async def commit(self) -> None:
        self.committed = True


async def _callback_identity(_code: str) -> oauth.GoogleIdentity:
    return oauth.GoogleIdentity(
        sub="google-subject",
        email="member@example.com",
        name="Team Member",
        picture_url="https://lh3.googleusercontent.com/avatar",
    )


async def _callback_tokens(
    _db: object, _user: object, **_device: object
) -> object:
    return SimpleNamespace(
        access_token="access-token",  # noqa: S106 - non-secret test token
        refresh_token="refresh-token",  # noqa: S106 - non-secret test token
        csrf_token="csrf-token",  # noqa: S106 - non-secret test token
    )


async def test_google_callback_enqueues_one_avatar_import_only_after_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_avatar_storage(monkeypatch)
    user = SimpleNamespace(id=uuid4(), is_active=True, auth_version=0, totp_secret=None)
    db = _GoogleCallbackDB(user)
    calls: list[dict[str, object]] = []

    class FakeTask:
        @staticmethod
        def apply_async(**kwargs: object) -> None:
            assert db.committed
            calls.append(kwargs)

    fake_tasks = ModuleType("app.worker.tasks")
    fake_tasks.import_google_avatar_task = FakeTask  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.worker.tasks", fake_tasks)
    monkeypatch.setattr(auth_routes, "enforce_rate_limit", _ignore_rate_limit)
    monkeypatch.setattr(auth_routes, "fetch_google_identity", _callback_identity)
    monkeypatch.setattr(auth_routes, "issue_tokens", _callback_tokens)
    state = "s" * 32

    response = await auth_routes.google_callback(
        request=_request(),
        db=db,  # type: ignore[arg-type]
        redis=_OAuthRedis(),  # type: ignore[arg-type]
        code="authorization-code",
        state=state,
        oauth_state=state,
    )

    assert response.status_code == 302
    assert calls == [
        {
            "args": (str(user.id), "https://lh3.googleusercontent.com/avatar", 1),
            "retry": False,
        }
    ]


async def test_avatar_enqueue_failure_never_breaks_google_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_avatar_storage(monkeypatch)
    user = SimpleNamespace(id=uuid4(), is_active=True, auth_version=0, totp_secret=None)
    db = _GoogleCallbackDB(user)

    class FailingTask:
        @staticmethod
        def apply_async(**_kwargs: object) -> None:
            raise RuntimeError("broker unavailable")

    fake_tasks = ModuleType("app.worker.tasks")
    fake_tasks.import_google_avatar_task = FailingTask  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.worker.tasks", fake_tasks)
    monkeypatch.setattr(auth_routes, "enforce_rate_limit", _ignore_rate_limit)
    monkeypatch.setattr(auth_routes, "fetch_google_identity", _callback_identity)
    monkeypatch.setattr(auth_routes, "issue_tokens", _callback_tokens)
    state = "s" * 32

    response = await auth_routes.google_callback(
        request=_request(),
        db=db,  # type: ignore[arg-type]
        redis=_OAuthRedis(),  # type: ignore[arg-type]
        code="authorization-code",
        state=state,
        oauth_state=state,
    )

    assert db.committed
    assert response.status_code == 302
    assert response.headers["location"].endswith("/app")


def _install_avatar_download_transport(
    monkeypatch: pytest.MonkeyPatch,
    *,
    status_code: int = 200,
    content: bytes,
    content_type: str = "image/png",
    content_length: str | None = None,
    headers: dict[str, str] | None = None,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        response_headers = {"Content-Type": content_type, **(headers or {})}
        if content_length is not None:
            response_headers["Content-Length"] = content_length
        return httpx.Response(
            status_code,
            content=content,
            headers=response_headers,
            request=request,
        )

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        avatar_processing.httpx,
        "AsyncClient",
        lambda **kwargs: _REAL_ASYNC_CLIENT(transport=transport, **kwargs),
    )


async def test_avatar_download_accepts_only_bounded_declared_image_mime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _image_bytes("PNG")
    _install_avatar_download_transport(
        monkeypatch,
        content=raw,
        content_type="image/png; charset=binary",
        content_length=str(len(raw)),
    )

    downloaded = await avatar_processing.download_google_avatar(
        "https://lh3.googleusercontent.com/avatar"
    )

    assert downloaded == raw


@pytest.mark.parametrize("content_type", ["image/gif", "image/svg+xml", "text/html", ""])
async def test_avatar_download_rejects_unapproved_mime_before_decode(
    monkeypatch: pytest.MonkeyPatch,
    content_type: str,
) -> None:
    _install_avatar_download_transport(
        monkeypatch,
        content=_image_bytes("PNG"),
        content_type=content_type,
    )

    with pytest.raises(InvalidAvatarError, match="unsupported type"):
        await avatar_processing.download_google_avatar("https://lh3.googleusercontent.com/avatar")


async def test_avatar_download_rejects_declared_and_streamed_oversize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "avatar_source_max_bytes", 1024)
    _install_avatar_download_transport(
        monkeypatch,
        content=b"x",
        content_length="1025",
    )
    with pytest.raises(InvalidAvatarError, match="size limit"):
        await avatar_processing.download_google_avatar("https://lh3.googleusercontent.com/avatar")

    _install_avatar_download_transport(monkeypatch, content=b"x" * 1025)
    with pytest.raises(InvalidAvatarError, match="size limit"):
        await avatar_processing.download_google_avatar("https://lh3.googleusercontent.com/avatar")


async def test_avatar_download_rejects_redirects_without_following_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_avatar_download_transport(
        monkeypatch,
        status_code=302,
        content=b"",
        headers={"Location": "http://127.0.0.1/private"},
    )

    with pytest.raises(InvalidAvatarError, match="could not be downloaded"):
        await avatar_processing.download_google_avatar("https://lh3.googleusercontent.com/avatar")


@pytest.mark.parametrize("image_format", ["GIF", "TIFF", "BMP"])
def test_avatar_processing_rejects_non_allowlisted_actual_formats(image_format: str) -> None:
    with pytest.raises(InvalidAvatarError, match="static JPEG, PNG and WebP"):
        avatar_processing.process_avatar(_image_bytes(image_format))


def test_avatar_processing_rejects_animated_webp() -> None:
    output = io.BytesIO()
    frames = [Image.new("RGB", (16, 16), color) for color in ("red", "blue")]
    try:
        frames[0].save(
            output,
            "WEBP",
            save_all=True,
            append_images=frames[1:],
            duration=100,
            loop=0,
        )
    except OSError:
        pytest.skip("Animated WebP is unavailable in this Pillow build")
    finally:
        for frame in frames:
            frame.close()

    with pytest.raises(InvalidAvatarError, match="Animated avatars"):
        avatar_processing.process_avatar(output.getvalue())


def test_avatar_processing_rejects_excessive_dimensions_and_pixels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "avatar_source_max_dimension", 16)
    with pytest.raises(InvalidAvatarError, match="dimensions"):
        avatar_processing.process_avatar(_image_bytes("PNG", size=(17, 1)))

    monkeypatch.setattr(settings, "avatar_source_max_dimension", 4096)
    monkeypatch.setattr(settings, "avatar_source_max_pixels", 100)
    with pytest.raises(InvalidAvatarError, match="pixel count"):
        avatar_processing.process_avatar(_image_bytes("PNG", size=(11, 10)))


def test_avatar_processing_rejects_truncated_and_empty_inputs() -> None:
    with pytest.raises(InvalidAvatarError):
        avatar_processing.process_avatar(b"")
    with pytest.raises(InvalidAvatarError):
        avatar_processing.process_avatar(_image_bytes("PNG")[:20])


def _jpeg_with_metadata() -> bytes:
    output = io.BytesIO()
    image = Image.new("RGB", (80, 40), "#22a06b")
    exif = Image.Exif()
    exif[0x010E] = "private description"
    exif[0x0112] = 6
    image.save(
        output,
        "JPEG",
        quality=90,
        exif=exif,
        icc_profile=b"private-icc-profile",
    )
    image.close()
    return output.getvalue()


def _png_with_metadata() -> bytes:
    output = io.BytesIO()
    image = Image.new("RGBA", (40, 80), (255, 0, 0, 128))
    pnginfo = PngImagePlugin.PngInfo()
    pnginfo.add_text("Comment", "private comment")
    pnginfo.add_text("XML:com.adobe.xmp", "<private>xmp</private>")
    image.save(output, "PNG", pnginfo=pnginfo)
    image.close()
    return output.getvalue()


@pytest.mark.parametrize("raw", [_jpeg_with_metadata(), _png_with_metadata()])
def test_avatar_processing_strips_metadata_and_emits_small_static_square_webp(
    raw: bytes,
) -> None:
    processed = avatar_processing.process_avatar(raw)

    assert processed.width == settings.avatar_output_size
    assert processed.height == settings.avatar_output_size
    assert processed.size_bytes == len(processed.data)
    assert processed.size_bytes <= settings.avatar_output_max_bytes
    assert processed.content_hash == hashlib.sha256(processed.data).hexdigest()
    with Image.open(io.BytesIO(processed.data)) as result:
        assert result.format == "WEBP"
        assert result.size == (settings.avatar_output_size, settings.avatar_output_size)
        assert getattr(result, "n_frames", 1) == 1
        assert not result.getexif()
        for key in avatar_processing.METADATA_KEYS:
            assert not result.info.get(key)


def test_avatar_processing_fails_when_normalized_output_cannot_meet_size_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "avatar_output_max_bytes", 1)

    with pytest.raises(InvalidAvatarError, match="storage size limit"):
        avatar_processing.process_avatar(_image_bytes("PNG"))


class _FakeClamdSocket:
    def __init__(self, response: bytes) -> None:
        self.response = response
        self.sent: list[bytes] = []
        self.recv_count = 0

    def __enter__(self) -> _FakeClamdSocket:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def sendall(self, payload: bytes | memoryview) -> None:
        self.sent.append(bytes(payload))

    def recv(self, _size: int) -> bytes:
        if self.recv_count:
            return b""
        self.recv_count += 1
        return self.response


def test_clamav_clean_protocol_streams_bounded_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _FakeClamdSocket(b"stream: OK\0")
    monkeypatch.setattr(antivirus, "_connect", lambda: connection)
    payload = b"x" * (antivirus.CLAMD_CHUNK_BYTES + 7)

    antivirus.scan_avatar_bytes(payload)

    assert connection.sent[0] == b"zINSTREAM\0"
    assert connection.sent[-1] == struct.pack("!I", 0)
    framed_chunks = connection.sent[1:-1]
    assert len(framed_chunks) == 4
    assert struct.unpack("!I", framed_chunks[0])[0] == antivirus.CLAMD_CHUNK_BYTES
    assert framed_chunks[1] == payload[: antivirus.CLAMD_CHUNK_BYTES]
    assert struct.unpack("!I", framed_chunks[2])[0] == 7
    assert framed_chunks[3] == payload[antivirus.CLAMD_CHUNK_BYTES :]


def test_clamav_explicit_test_bypass_does_not_connect(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(settings, "avatar_malware_scan_mode", "disabled-for-testing")

    def unexpected_connect() -> None:
        raise AssertionError("ClamAV connection must be bypassed in explicit test mode")

    monkeypatch.setattr(antivirus, "_connect", unexpected_connect)

    with caplog.at_level("WARNING", logger=antivirus.__name__):
        antivirus.scan_avatar_bytes(b"trusted test avatar")

    assert "SECURITY WARNING" in caplog.text


def test_clamav_test_bypass_keeps_payload_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "avatar_malware_scan_mode", "disabled-for-testing")

    with pytest.raises(MalwareScannerUnavailableError, match="configured limit"):
        antivirus.scan_avatar_bytes(b"")


def test_clamav_found_is_a_permanent_malware_result(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _FakeClamdSocket(b"stream: Win.Test.EICAR_HDB-1 FOUND\0")
    monkeypatch.setattr(antivirus, "_connect", lambda: connection)

    with pytest.raises(MalwareDetectedError):
        antivirus.scan_avatar_bytes(b"EICAR fixture")


@pytest.mark.parametrize(
    "response",
    [b"stream: size limit exceeded ERROR\0", b"unexpected\0", b""],
)
def test_clamav_error_or_ambiguous_result_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    response: bytes,
) -> None:
    connection = _FakeClamdSocket(response)
    monkeypatch.setattr(antivirus, "_connect", lambda: connection)

    with pytest.raises(MalwareScannerUnavailableError):
        antivirus.scan_avatar_bytes(b"benign image bytes")


class _FakeS3Client:
    def __init__(self) -> None:
        self.put_calls: list[dict[str, object]] = []
        self.get_calls: list[dict[str, object]] = []
        self.get_response: dict[str, object] | None = None
        self.get_error: Exception | None = None

    def put_object(self, **kwargs: object) -> dict[str, object]:
        self.put_calls.append(kwargs)
        return {"ETag": '"etag"'}

    def get_object(self, **kwargs: object) -> dict[str, object]:
        self.get_calls.append(kwargs)
        if self.get_error is not None:
            raise self.get_error
        assert self.get_response is not None
        return self.get_response


def test_s3_put_has_exact_private_validated_avatar_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_avatar_storage(monkeypatch)
    client = _FakeS3Client()
    monkeypatch.setattr(object_storage, "get_s3_client", lambda: client)
    user_id = uuid4()
    processed = avatar_processing.process_avatar(_image_bytes("PNG"))

    key = object_storage.store_avatar(user_id, processed)

    assert key == f"avatars/{user_id.hex}/{processed.content_hash}.webp"
    assert len(client.put_calls) == 1
    assert client.put_calls[0] == {
        "Bucket": "noki-private-avatars",
        "Key": key,
        "Body": processed.data,
        "ContentType": "image/webp",
        "ContentLength": processed.size_bytes,
        "ContentMD5": base64.b64encode(
            hashlib.md5(processed.data, usedforsecurity=False).digest()
        ).decode("ascii"),
        "CacheControl": AVATAR_CACHE_CONTROL,
        "Metadata": {"sha256": processed.content_hash},
        "ServerSideEncryption": "AES256",
    }
    assert "ACL" not in client.put_calls[0]


def test_s3_put_is_never_called_for_tampered_normalized_avatar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_avatar_storage(monkeypatch)
    client = _FakeS3Client()
    monkeypatch.setattr(object_storage, "get_s3_client", lambda: client)
    processed = avatar_processing.process_avatar(_image_bytes("PNG"))
    tampered = replace(processed, content_hash="0" * 64)

    with pytest.raises(InvalidAvatarError, match="checksum"):
        object_storage.store_avatar(uuid4(), tampered)

    assert client.put_calls == []


def test_s3_get_uses_validated_key_and_verifies_object_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_avatar_storage(monkeypatch)
    client = _FakeS3Client()
    monkeypatch.setattr(object_storage, "get_s3_client", lambda: client)
    processed = avatar_processing.process_avatar(_image_bytes("PNG"))
    user_id = uuid4()
    key = object_storage.avatar_object_key(user_id, processed.content_hash)
    body = io.BytesIO(processed.data)
    client.get_response = {
        "Body": body,
        "ContentLength": processed.size_bytes,
        "ContentType": "image/webp",
        "Metadata": {"sha256": processed.content_hash},
    }

    opened = object_storage.open_avatar(key, processed.content_hash)

    assert client.get_calls == [{"Bucket": "noki-private-avatars", "Key": key}]
    assert opened.size_bytes == processed.size_bytes
    assert opened.body.read() == processed.data
    opened.body.close()


def test_s3_get_rejects_bad_metadata_and_closes_body(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_avatar_storage(monkeypatch)
    client = _FakeS3Client()
    monkeypatch.setattr(object_storage, "get_s3_client", lambda: client)
    content_hash = "a" * 64
    key = object_storage.avatar_object_key(uuid4(), content_hash)
    body = io.BytesIO(b"not-an-avatar")
    client.get_response = {
        "Body": body,
        "ContentLength": len(body.getvalue()),
        "ContentType": "text/html",
        "Metadata": {"sha256": content_hash},
    }

    with pytest.raises(AvatarStorageError, match="metadata"):
        object_storage.open_avatar(key, content_hash)

    assert body.closed


def test_s3_missing_object_is_mapped_without_leaking_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_avatar_storage(monkeypatch)
    client = _FakeS3Client()
    monkeypatch.setattr(object_storage, "get_s3_client", lambda: client)
    client.get_error = ClientError(
        {"Error": {"Code": "NoSuchKey", "Message": "provider detail"}},
        "GetObject",
    )
    content_hash = "a" * 64
    key = object_storage.avatar_object_key(uuid4(), content_hash)

    with pytest.raises(AvatarObjectNotFoundError, match="not found"):
        object_storage.open_avatar(key, content_hash)


def test_s3_get_hashes_exact_body_instead_of_trusting_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_avatar_storage(monkeypatch)
    client = _FakeS3Client()
    monkeypatch.setattr(object_storage, "get_s3_client", lambda: client)
    expected_payload = b"expected normalized avatar"
    tampered_payload = b"tampered normalized avatar"
    content_hash = hashlib.sha256(expected_payload).hexdigest()
    key = object_storage.avatar_object_key(uuid4(), content_hash)
    body = io.BytesIO(tampered_payload)
    client.get_response = {
        "Body": body,
        "ContentLength": len(tampered_payload),
        "ContentType": "image/webp",
        "Metadata": {"sha256": content_hash},
    }

    with pytest.raises(AvatarStorageError, match="content failed verification"):
        object_storage.open_avatar(key, content_hash)

    assert body.closed
    assert len(client.get_calls) == 1


def test_verified_avatar_memory_cache_avoids_repeated_s3_gets_by_content_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_avatar_storage(monkeypatch)
    client = _FakeS3Client()
    monkeypatch.setattr(object_storage, "get_s3_client", lambda: client)
    payload = b"verified normalized avatar"
    content_hash = hashlib.sha256(payload).hexdigest()
    first_key = object_storage.avatar_object_key(uuid4(), content_hash)
    second_key = object_storage.avatar_object_key(uuid4(), content_hash)
    provider_body = io.BytesIO(payload)
    client.get_response = {
        "Body": provider_body,
        "ContentLength": len(payload),
        "ContentType": "image/webp",
        "Metadata": {"sha256": content_hash},
    }

    first = object_storage.open_avatar(first_key, content_hash)
    second = object_storage.open_avatar(second_key, content_hash)

    assert first.body.read() == payload
    assert second.body.read() == payload
    first.body.close()
    second.body.close()
    assert provider_body.closed
    assert client.get_calls == [{"Bucket": "noki-private-avatars", "Key": first_key}]


def test_avatar_memory_cache_evicts_lru_bytes_at_the_global_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_avatar_storage(monkeypatch)
    monkeypatch.setattr(object_storage, "AVATAR_MEMORY_CACHE_MAX_BYTES", 5)
    client = _FakeS3Client()
    monkeypatch.setattr(object_storage, "get_s3_client", lambda: client)

    def open_payload(payload: bytes, key: str, content_hash: str) -> None:
        client.get_response = {
            "Body": io.BytesIO(payload),
            "ContentLength": len(payload),
            "ContentType": "image/webp",
            "Metadata": {"sha256": content_hash},
        }
        opened = object_storage.open_avatar(key, content_hash)
        assert opened.body.read() == payload
        opened.body.close()

    first_payload = b"one"
    second_payload = b"two"
    first_hash = hashlib.sha256(first_payload).hexdigest()
    second_hash = hashlib.sha256(second_payload).hexdigest()
    first_key = object_storage.avatar_object_key(uuid4(), first_hash)
    second_key = object_storage.avatar_object_key(uuid4(), second_hash)

    open_payload(first_payload, first_key, first_hash)
    open_payload(second_payload, second_key, second_hash)
    open_payload(first_payload, first_key, first_hash)

    assert [call["Key"] for call in client.get_calls] == [
        first_key,
        second_key,
        first_key,
    ]


class _FakeListingS3Client:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = responses
        self.list_calls: list[dict[str, object]] = []

    def list_objects_v2(self, **kwargs: object) -> dict[str, object]:
        self.list_calls.append(kwargs)
        return self.responses[len(self.list_calls) - 1]


def test_s3_avatar_listing_paginates_past_the_old_ten_thousand_object_cutoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_avatar_storage(monkeypatch)
    listed_at = datetime(2026, 8, 3, tzinfo=UTC)
    total_objects = 10_001
    entries = [
        {
            "Key": f"avatars/{uuid4().hex}/{index:064x}.webp",
            "LastModified": listed_at,
        }
        for index in range(total_objects)
    ]
    responses: list[dict[str, object]] = []
    for page_index, start in enumerate(range(0, total_objects, 1_000)):
        end = min(start + 1_000, total_objects)
        truncated = end < total_objects
        response: dict[str, object] = {
            "Contents": entries[start:end],
            "IsTruncated": truncated,
        }
        if truncated:
            response["NextContinuationToken"] = f"page-{page_index + 1}"
        responses.append(response)
    client = _FakeListingS3Client(responses)
    monkeypatch.setattr(object_storage, "get_s3_client", lambda: client)

    objects = object_storage.list_avatar_objects()

    assert len(objects) == total_objects
    assert len(client.list_calls) == 11
    assert all(call["MaxKeys"] == 1_000 for call in client.list_calls)
    assert "ContinuationToken" not in client.list_calls[0]
    assert client.list_calls[-1]["ContinuationToken"] == "page-10"


def test_s3_avatar_listing_hard_fails_loudly_at_the_page_safety_bound(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _enable_avatar_storage(monkeypatch)
    monkeypatch.setattr(object_storage, "MAX_AVATAR_LIST_PAGES", 2)
    client = _FakeListingS3Client(
        [
            {"Contents": [], "IsTruncated": True, "NextContinuationToken": "page-1"},
            {"Contents": [], "IsTruncated": True, "NextContinuationToken": "page-2"},
        ]
    )
    monkeypatch.setattr(object_storage, "get_s3_client", lambda: client)

    with (
        caplog.at_level("ERROR", logger=object_storage.__name__),
        pytest.raises(AvatarStorageError, match="safety page limit"),
    ):
        object_storage.list_avatar_objects()

    assert len(client.list_calls) == 2
    assert "exceeded its safety limit" in caplog.text


def test_s3_avatar_listing_rejects_a_repeated_continuation_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_avatar_storage(monkeypatch)
    client = _FakeListingS3Client(
        [
            {"Contents": [], "IsTruncated": True, "NextContinuationToken": "same"},
            {"Contents": [], "IsTruncated": True, "NextContinuationToken": "same"},
        ]
    )
    monkeypatch.setattr(object_storage, "get_s3_client", lambda: client)

    with pytest.raises(AvatarStorageError, match="continue safely"):
        object_storage.list_avatar_objects()

    assert len(client.list_calls) == 2


@pytest.mark.parametrize(
    "response",
    [
        {"Contents": [{}] * 1_001, "IsTruncated": False},
        {"Contents": [], "IsTruncated": "false"},
    ],
)
def test_s3_avatar_listing_rejects_malformed_or_oversized_pages(
    monkeypatch: pytest.MonkeyPatch,
    response: dict[str, object],
) -> None:
    _enable_avatar_storage(monkeypatch)
    client = _FakeListingS3Client([response])
    monkeypatch.setattr(object_storage, "get_s3_client", lambda: client)

    with pytest.raises(AvatarStorageError, match="invalid page"):
        object_storage.list_avatar_objects()

    assert len(client.list_calls) == 1


class _AvatarResult:
    def __init__(self, row: object | None) -> None:
        self.row = row

    def one_or_none(self) -> object | None:
        return self.row


class _AvatarRouteDB:
    def __init__(self, row: object | None) -> None:
        self.row = row

    async def execute(self, _statement: object) -> _AvatarResult:
        return _AvatarResult(self.row)


async def _allow_avatar(*_args: object) -> bool:
    return True


async def _deny_avatar(*_args: object) -> bool:
    return False


async def _ignore_rate_limit(*_args: object, **_kwargs: object) -> None:
    return None


async def test_media_avatar_route_is_private_cacheable_and_streams_verified_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_avatar_storage(monkeypatch)
    monkeypatch.setattr(avatar_routes, "enforce_rate_limit", _ignore_rate_limit)
    monkeypatch.setattr(avatar_routes, "_can_view_avatar", _allow_avatar)
    user_id = uuid4()
    viewer_id = uuid4()
    content_hash = "b" * 64
    key = object_storage.avatar_object_key(user_id, content_hash)
    payload = b"normalized-webp"
    opened_body = io.BytesIO(payload)
    monkeypatch.setattr(
        avatar_routes,
        "open_avatar",
        lambda *_args: OpenedAvatarObject(body=opened_body, size_bytes=len(payload)),
    )
    db = _AvatarRouteDB(SimpleNamespace(avatar_object_key=key, avatar_content_hash=content_hash))

    response = await avatar_routes.get_avatar(
        user_id,
        content_hash,
        _request({"If-None-Match": '"not-this-avatar", W/"also-not-this-avatar"'}),
        SimpleNamespace(id=viewer_id),
        db,  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == AVATAR_CACHE_CONTROL
    assert response.headers["cache-control"].startswith("private,")
    assert response.headers["etag"] == f'"{content_hash}"'
    assert "vary" not in response.headers
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cross-origin-resource-policy"] == "same-origin"
    assert response.headers["content-type"].startswith("image/webp")
    assert response.headers["content-length"] == str(len(payload))
    body = b"".join([chunk async for chunk in response.body_iterator])
    assert body == payload
    assert opened_body.closed


async def test_media_avatar_route_checks_access_before_s3_get(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_avatar_storage(monkeypatch)
    monkeypatch.setattr(avatar_routes, "enforce_rate_limit", _ignore_rate_limit)
    monkeypatch.setattr(avatar_routes, "_can_view_avatar", _deny_avatar)
    storage_called = False

    def unexpected_open(*_args: object) -> None:
        nonlocal storage_called
        storage_called = True

    monkeypatch.setattr(avatar_routes, "open_avatar", unexpected_open)
    user_id = uuid4()
    content_hash = "c" * 64
    key = object_storage.avatar_object_key(user_id, content_hash)
    db = _AvatarRouteDB(SimpleNamespace(avatar_object_key=key, avatar_content_hash=content_hash))

    with pytest.raises(HTTPException) as captured:
        await avatar_routes.get_avatar(
            user_id,
            content_hash,
            _request({"If-None-Match": "*"}),
            SimpleNamespace(id=uuid4()),
            db,  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
        )

    assert captured.value.status_code == 404
    assert not storage_called


async def test_media_avatar_route_rechecks_rbac_on_every_in_process_cache_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_avatar_storage(monkeypatch)
    monkeypatch.setattr(avatar_routes, "enforce_rate_limit", _ignore_rate_limit)
    access_results = iter([True, False])
    access_checks = 0

    async def changing_access(*_args: object) -> bool:
        nonlocal access_checks
        access_checks += 1
        return next(access_results)

    user_id = uuid4()
    content_hash = "9" * 64
    key = object_storage.avatar_object_key(user_id, content_hash)
    payload = b"cached-avatar"
    storage_reads = 0

    def cached_open(*_args: object) -> OpenedAvatarObject:
        nonlocal storage_reads
        storage_reads += 1
        return OpenedAvatarObject(body=io.BytesIO(payload), size_bytes=len(payload))

    monkeypatch.setattr(avatar_routes, "_can_view_avatar", changing_access)
    monkeypatch.setattr(avatar_routes, "open_avatar", cached_open)
    db = _AvatarRouteDB(SimpleNamespace(avatar_object_key=key, avatar_content_hash=content_hash))
    current_user = SimpleNamespace(id=uuid4())

    first = await avatar_routes.get_avatar(
        user_id,
        content_hash,
        _request(),
        current_user,
        db,  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
    )
    assert b"".join([chunk async for chunk in first.body_iterator]) == payload

    with pytest.raises(HTTPException) as captured:
        await avatar_routes.get_avatar(
            user_id,
            content_hash,
            _request(),
            current_user,
            db,  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
        )

    assert captured.value.status_code == 404
    assert access_checks == 2
    assert storage_reads == 1


@pytest.mark.parametrize(
    "header_template",
    [
        '"{content_hash}"',
        'W/"{content_hash}"',
        '"other,opaque-tag", W/"{content_hash}", "another"',
        "*",
        '"other", *',
    ],
)
async def test_media_avatar_conditional_get_variants_return_304_without_s3_charge(
    monkeypatch: pytest.MonkeyPatch,
    header_template: str,
) -> None:
    _enable_avatar_storage(monkeypatch)
    monkeypatch.setattr(avatar_routes, "enforce_rate_limit", _ignore_rate_limit)
    monkeypatch.setattr(avatar_routes, "_can_view_avatar", _allow_avatar)

    def unexpected_open(*_args: object) -> None:
        raise AssertionError("A matching If-None-Match must not perform an S3 GET")

    monkeypatch.setattr(avatar_routes, "open_avatar", unexpected_open)
    user_id = uuid4()
    content_hash = "d" * 64
    key = object_storage.avatar_object_key(user_id, content_hash)
    db = _AvatarRouteDB(SimpleNamespace(avatar_object_key=key, avatar_content_hash=content_hash))

    response = await avatar_routes.get_avatar(
        user_id,
        content_hash,
        _request({"If-None-Match": header_template.format(content_hash=content_hash)}),
        SimpleNamespace(id=uuid4()),
        db,  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
    )

    assert response.status_code == 304
    assert response.headers["cache-control"] == AVATAR_CACHE_CONTROL
    assert response.headers["cache-control"].startswith("private,")
    assert "vary" not in response.headers


async def test_avatar_access_allows_self_without_membership_query() -> None:
    user_id = uuid4()

    class NoQueryDB:
        async def scalar(self, _statement: object) -> object:
            raise AssertionError("Self avatar access needs no membership query")

    assert await avatar_routes._can_view_avatar(NoQueryDB(), user_id, user_id)  # type: ignore[arg-type]


@pytest.mark.parametrize("shared", [True, False])
async def test_avatar_access_requires_a_shared_space(shared: bool) -> None:
    class SharedSpaceDB:
        async def scalar(self, _statement: object) -> UUID | None:
            return uuid4() if shared else None

    allowed = await avatar_routes._can_view_avatar(  # type: ignore[arg-type]
        SharedSpaceDB(),
        uuid4(),
        uuid4(),
    )

    assert allowed is shared


def test_avatar_refresh_helper_handles_source_changes_and_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "avatar_refresh_days", 7)
    now = datetime(2026, 8, 3, tzinfo=UTC)

    assert avatars.avatar_import_is_due("new", "old", now, now=now)
    assert avatars.avatar_import_is_due("same", "same", None, now=now)
    assert not avatars.avatar_import_is_due(
        "same",
        "same",
        now - timedelta(days=6, hours=23),
        now=now,
    )
    assert avatars.avatar_import_is_due(
        "same",
        "same",
        now - timedelta(days=7),
        now=now,
    )
    assert not avatars.avatar_import_is_due(
        "same",
        "same",
        (now - timedelta(days=1)).replace(tzinfo=None),
        now=now,
    )


class _SessionContext:
    def __init__(self, db: object) -> None:
        self.db = db

    async def __aenter__(self) -> object:
        return self.db

    async def __aexit__(self, *_args: object) -> None:
        return None


async def test_fresh_google_avatar_skips_download_scan_and_paid_put(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_avatar_storage(monkeypatch)
    picture_url = "https://lh3.googleusercontent.com/avatar"
    source_hash = avatar_processing.avatar_source_hash(picture_url)
    generation = 1
    user = SimpleNamespace(
        google_sub="google-subject",
        is_active=True,
        avatar_import_generation=generation,
        avatar_requested_source_hash=source_hash,
        avatar_source_url_hash=source_hash,
        avatar_synced_at=datetime.now(UTC),
    )

    class FreshDB:
        async def get(self, _model: object, _user_id: UUID) -> object:
            return user

    monkeypatch.setattr(avatars, "async_session_factory", lambda: _SessionContext(FreshDB()))

    async def unexpected_download(_url: str) -> bytes:
        raise AssertionError("Fresh avatar must not be downloaded")

    monkeypatch.setattr(avatars, "download_google_avatar", unexpected_download)
    monkeypatch.setattr(
        avatars,
        "store_avatar",
        lambda *_args: (_ for _ in ()).throw(AssertionError("Fresh avatar must not be PUT")),
    )

    result = await avatars.import_google_avatar(uuid4(), picture_url, generation)

    assert result.status == "fresh"
    assert not result.uploaded


async def test_unchanged_avatar_bytes_are_rescanned_but_not_put_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_avatar_storage(monkeypatch)
    picture_url = "https://lh3.googleusercontent.com/avatar-v2"
    source_hash = avatar_processing.avatar_source_hash(picture_url)
    generation = 1
    processed = avatar_processing.process_avatar(_image_bytes("PNG"))
    user = SimpleNamespace(
        google_sub="google-subject",
        is_active=True,
        avatar_import_generation=generation,
        avatar_requested_source_hash=source_hash,
        avatar_source_url_hash="old-source-hash",
        avatar_synced_at=datetime.now(UTC),
        avatar_content_hash=processed.content_hash,
    )
    sessions_created = 0

    class InitialDB:
        async def get(self, _model: object, _user_id: UUID) -> object:
            return user

    class LockedDB:
        committed = False

        async def scalar(self, _statement: object) -> object:
            return user

        async def commit(self) -> None:
            self.committed = True

    locked_db = LockedDB()

    def session_factory() -> _SessionContext:
        nonlocal sessions_created
        sessions_created += 1
        return _SessionContext(InitialDB() if sessions_created == 1 else locked_db)

    monkeypatch.setattr(avatars, "async_session_factory", session_factory)

    async def download(_url: str) -> bytes:
        return b"raw-image"

    scans: list[bytes] = []
    monkeypatch.setattr(avatars, "download_google_avatar", download)
    monkeypatch.setattr(avatars, "scan_avatar_bytes", scans.append)
    monkeypatch.setattr(avatars, "process_avatar", lambda _raw: processed)
    monkeypatch.setattr(
        avatars,
        "store_avatar",
        lambda *_args: (_ for _ in ()).throw(AssertionError("Unchanged bytes must not be PUT")),
    )

    result = await avatars.import_google_avatar(uuid4(), picture_url, generation)

    assert result.status == "unchanged"
    assert not result.uploaded
    assert scans == [b"raw-image", processed.data]
    assert locked_db.committed
    assert user.avatar_source_url_hash == source_hash


def test_avatar_media_url_requires_consistent_key_hash_and_enabled_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_avatar_storage(monkeypatch)
    user_id = uuid4()
    content_hash = "e" * 64
    key = object_storage.avatar_object_key(user_id, content_hash)

    assert object_storage.avatar_media_url(user_id, key, content_hash) == (
        f"/media/avatars/{user_id}/{content_hash}.webp"
    )
    assert object_storage.avatar_media_url(user_id, key, "f" * 64) is None
    assert object_storage.avatar_media_url(user_id, "avatars/unsafe.webp", content_hash) is None
