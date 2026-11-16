from __future__ import annotations

import asyncio
import logging
import re
import shutil
import tempfile
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select, text
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.router import api_router
from app.api.routes.public_api import router as public_api_router
from app.core.config import settings
from app.core.encryption import DataDecryptionError, get_data_cipher
from app.core.middleware import (
    RequestBodyLimitMiddleware,
    RequestContextMiddleware,
    RequestTimeoutMiddleware,
    SecurityHeadersMiddleware,
)
from app.db.session import async_session_factory, dispose_engine
from app.models import Page, Task, Upload
from app.services.content_encryption import (
    get_page_content,
    get_page_markdown,
    get_page_title,
    get_task_description,
    get_task_title,
    get_upload_original_name,
)

logger = logging.getLogger("noki")
SMALL_REQUEST_BODY_BYTES = 128 * 1024
MAX_VALIDATION_ERRORS = 25
MAX_VALIDATION_LOCATION_DEPTH = 8
MAX_VALIDATION_TEXT_CHARS = 200


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    redis: Redis | None = None
    try:
        get_data_cipher()
        settings.upload_dir.mkdir(parents=True, exist_ok=True)
        settings.export_dir.mkdir(parents=True, exist_ok=True)
        if settings.environment == "production":
            database_status = await _database_readiness()
            if not all(database_status.values()):
                raise RuntimeError("Database is not ready for this application revision")

        redis = Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_timeout=settings.redis_socket_timeout,
            socket_connect_timeout=settings.redis_connect_timeout,
            socket_keepalive=True,
            health_check_interval=30,
            max_connections=settings.redis_max_connections,
        )
        app.state.redis = redis
        app.state.readiness_lock = asyncio.Lock()
        app.state.readiness_cache = (0.0, None)
        yield
    finally:
        if redis is not None:
            await redis.aclose()
        await dispose_engine()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Noki MVP API: Spaces, Teams, Kanban issue boards and Pages.",
    lifespan=lifespan,
    docs_url=None if settings.environment == "production" else "/docs",
    redoc_url=None if settings.environment == "production" else "/redoc",
    openapi_url=None if settings.environment == "production" else "/openapi.json",
)

app.add_middleware(
    RequestBodyLimitMiddleware,
    default_limit=min(settings.max_request_bytes, SMALL_REQUEST_BODY_BYTES),
    upload_limit=settings.max_image_bytes + 1024 * 1024,
    large_body_limit=settings.max_request_bytes,
    large_body_path_prefixes=(f"{settings.api_v1_prefix}/pages/",),
    body_timeout_seconds=settings.request_timeout_seconds,
    public_api_prefix=settings.public_api_v1_prefix,
)
app.add_middleware(
    RequestTimeoutMiddleware,
    timeout_seconds=settings.request_timeout_seconds,
    # Pillow work runs in a native worker thread and cannot be safely cancelled:
    # cancelling it could leave a completed file without its database row.
    excluded_method_paths=(("POST", f"{settings.api_v1_prefix}/uploads/images"),),
    public_api_prefix=settings.public_api_v1_prefix,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
    max_age=600,
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_host_list)
app.add_middleware(
    SecurityHeadersMiddleware,
    production=settings.environment == "production",
    no_store_path_prefixes=(
        settings.api_v1_prefix,
        settings.public_api_v1_prefix,
        "/health",
    ),
)
app.add_middleware(RequestContextMiddleware)

NAVIGATION_STRUCTURE_PATH = re.compile(
    rf"^{re.escape(settings.api_v1_prefix)}/(?:spaces|teams|boards|pages)(?:/|$)"
)


@app.middleware("http")
async def invalidate_navigation_cache(request: Request, call_next):
    response = await call_next(request)
    if (
        request.method in {"POST", "PUT", "PATCH", "DELETE"}
        and response.status_code < 400
        and NAVIGATION_STRUCTURE_PATH.match(request.url.path)
    ):
        redis = getattr(request.app.state, "redis", None)
        if redis is not None:
            with suppress(RedisError):
                await redis.incr("navigation:structure-version")
    return response


app.include_router(api_router, prefix=settings.api_v1_prefix)
app.include_router(public_api_router)


def _is_public_api_request(request: Request) -> bool:
    path = request.url.path
    prefix = settings.public_api_v1_prefix
    return path == prefix or path.startswith(f"{prefix}/")


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: StarletteHTTPException):
    if not _is_public_api_request(request):
        return await http_exception_handler(request, exc)

    codes = {
        status.HTTP_400_BAD_REQUEST: "bad_request",
        status.HTTP_401_UNAUTHORIZED: "invalid_token",
        status.HTTP_403_FORBIDDEN: "forbidden",
        status.HTTP_404_NOT_FOUND: "not_found",
        status.HTTP_405_METHOD_NOT_ALLOWED: "method_not_allowed",
        status.HTTP_408_REQUEST_TIMEOUT: "request_timeout",
        status.HTTP_409_CONFLICT: "conflict",
        status.HTTP_413_REQUEST_ENTITY_TOO_LARGE: "payload_too_large",
        status.HTTP_422_UNPROCESSABLE_ENTITY: "validation_error",
        status.HTTP_429_TOO_MANY_REQUESTS: "rate_limit_exceeded",
        status.HTTP_500_INTERNAL_SERVER_ERROR: "internal_error",
        status.HTTP_504_GATEWAY_TIMEOUT: "request_timeout",
    }
    message = exc.detail if isinstance(exc.detail, str) else "Request failed"
    headers = dict(exc.headers or {})
    headers["Cache-Control"] = "no-store"
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": codes.get(exc.status_code, "http_error"),
                "message": message,
                "request_id": getattr(request.state, "request_id", None),
            }
        },
        headers=headers,
    )


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    # Pydantic includes rejected input values by default. Never echo passwords,
    # OAuth codes, oversized strings, or other request data in an error body.
    # Bound both error count and individual fields to prevent a small invalid
    # request from being amplified into a very large JSON response.
    raw_errors = exc.errors()
    errors: list[dict[str, object]] = []
    for error in raw_errors[:MAX_VALIDATION_ERRORS]:
        raw_location = error.get("loc", ())
        location: list[str | int] = []
        if isinstance(raw_location, (list, tuple)):
            for segment in raw_location[:MAX_VALIDATION_LOCATION_DEPTH]:
                if isinstance(segment, int):
                    location.append(segment)
                elif isinstance(segment, str):
                    location.append(segment[:MAX_VALIDATION_TEXT_CHARS])
                else:
                    location.append(type(segment).__name__[:MAX_VALIDATION_TEXT_CHARS])
        errors.append(
            {
                "type": str(error.get("type", "validation_error"))[:MAX_VALIDATION_TEXT_CHARS],
                "loc": location,
                "msg": str(error.get("msg", "Invalid request"))[:MAX_VALIDATION_TEXT_CHARS],
            }
        )
    if len(raw_errors) > MAX_VALIDATION_ERRORS:
        errors.append(
            {
                "type": "too_many_validation_errors",
                "loc": ["body"],
                "msg": "Additional validation errors were omitted",
            }
        )
    if _is_public_api_request(request):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed",
                    "details": errors,
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
            headers={"Cache-Control": "no-store"},
        )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": errors},
        headers={"Cache-Control": "no-store"},
    )


@app.exception_handler(DataDecryptionError)
async def encrypted_data_error_handler(
    request: Request,
    exc: DataDecryptionError,
) -> JSONResponse:
    logger.exception(
        "encrypted_data_unavailable request_id=%s path=%r",
        getattr(request.state, "request_id", "-"),
        request.url.path[:512],
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    if _is_public_api_request(request):
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "Encrypted data is unavailable",
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
            headers={"Cache-Control": "no-store"},
        )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Encrypted data is unavailable or failed integrity verification"},
        headers={"Cache-Control": "no-store"},
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    if not _is_public_api_request(request):
        # Match Starlette's default production response for existing routes.
        return PlainTextResponse(
            "Internal Server Error",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    request_id = getattr(request.state, "request_id", None)
    logger.exception(
        "public_api_unhandled_error request_id=%s path=%r",
        request_id or "-",
        request.url.path[:512],
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    headers = {"Cache-Control": "no-store"}
    if request_id:
        headers["X-Request-ID"] = request_id
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": "internal_error",
                "message": "Internal server error",
                "request_id": request_id,
            }
        },
        headers=headers,
    )


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    payload = {"name": settings.app_name, "status": "ok"}
    if settings.environment != "production":
        payload["docs"] = "/docs"
    return payload


@app.get("/live", include_in_schema=False)
async def live() -> dict[str, str]:
    return {"status": "ok"}


def _database_revision_is_ready(revisions: list[str]) -> bool:
    return revisions == [settings.expected_db_revision]


async def _database_readiness() -> dict[str, bool]:
    result = {
        "database": False,
        "migrations": False,
        "encryption": False,
    }
    try:
        async with async_session_factory() as db:
            await db.execute(text("SELECT 1"))
            result["database"] = True
            revisions = sorted(
                str(revision)
                for revision in (
                    await db.scalars(text("SELECT version_num FROM alembic_version"))
                ).all()
            )
            result["migrations"] = _database_revision_is_ready(revisions)
            if not result["migrations"]:
                return result

            encrypted_samples: tuple[tuple[Any, tuple[Any, ...]], ...] = (
                (
                    await db.scalar(select(Page).limit(1)),
                    (get_page_title, get_page_content, get_page_markdown),
                ),
                (
                    await db.scalar(select(Task).limit(1)),
                    (get_task_title, get_task_description),
                ),
                (
                    await db.scalar(select(Upload).limit(1)),
                    (get_upload_original_name,),
                ),
            )
            for record, decryptors in encrypted_samples:
                if record is not None:
                    for decrypt in decryptors:
                        decrypt(record)
            result["encryption"] = True
    except Exception as exc:
        logger.warning("database_readiness_failed error_type=%s", type(exc).__name__)
    return result


async def _redis_readiness(redis: Redis) -> bool:
    try:
        return bool(await redis.ping())
    except Exception as exc:
        logger.warning("redis_readiness_failed error_type=%s", type(exc).__name__)
        return False


def _storage_readiness() -> bool:
    probe_path: Path | None = None
    try:
        upload_dir = settings.upload_dir
        if not upload_dir.is_dir():
            return False
        if shutil.disk_usage(upload_dir).free < settings.min_upload_free_bytes:
            return False
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=".noki-health-",
            dir=upload_dir,
            delete=False,
        ) as probe:
            probe.write(b"ok")
            probe.flush()
            probe_path = Path(probe.name)
        return True
    except OSError as exc:
        logger.warning("storage_readiness_failed error_type=%s", type(exc).__name__)
        return False
    finally:
        if probe_path is not None:
            try:
                probe_path.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning(
                    "storage_probe_cleanup_failed error_type=%s",
                    type(exc).__name__,
                )


@app.get("/health", tags=["System"], response_model=None)
async def health(request: Request) -> dict[str, object] | JSONResponse:
    async with request.app.state.readiness_lock:
        checked_at, cached_payload = request.app.state.readiness_cache
        if cached_payload is not None and time.monotonic() - checked_at < 5:
            payload = cached_payload
        else:
            database_result, redis_ok, storage_ok = await asyncio.gather(
                _database_readiness(),
                _redis_readiness(request.app.state.redis),
                asyncio.to_thread(_storage_readiness),
            )
            checks = {
                **database_result,
                "redis": redis_ok,
                "storage": storage_ok,
            }
            payload = {
                "status": "ok" if all(checks.values()) else "degraded",
                "checks": checks,
            }
            request.app.state.readiness_cache = (time.monotonic(), payload)

    ready = payload["status"] == "ok"
    if not ready:
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=payload)
    return payload
