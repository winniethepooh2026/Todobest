from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from app.core.middleware import (
    REQUEST_ID_PATTERN,
    RequestBodyLimitMiddleware,
    RequestContextMiddleware,
    RequestTimeoutMiddleware,
    SecurityHeadersMiddleware,
)

ASGIApp = Callable[
    [dict[str, Any], Callable[..., Awaitable[Any]], Callable[..., Awaitable[Any]]], Awaitable[None]
]


def _scope(headers: list[tuple[bytes, bytes]] | None = None) -> dict[str, Any]:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/api/v1/test",
        "raw_path": b"/api/v1/test",
        "query_string": b"",
        "headers": headers or [],
        "client": ("127.0.0.1", 12345),
        "server": ("example.test", 443),
    }


async def _invoke(
    app: ASGIApp,
    *,
    scope: dict[str, Any] | None = None,
    request_messages: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    messages = iter(request_messages or [{"type": "http.request", "body": b"", "more_body": False}])
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return next(messages, {"type": "http.disconnect"})

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await app(scope or _scope(), receive, send)
    return sent


async def _consume_body(scope: dict[str, Any], receive, send) -> None:
    while True:
        message = await receive()
        if message["type"] != "http.request" or not message.get("more_body", False):
            break
    await send({"type": "http.response.start", "status": 204, "headers": []})
    await send({"type": "http.response.body", "body": b""})


@pytest.mark.asyncio
async def test_body_limit_rejects_declared_and_streamed_oversize_requests() -> None:
    middleware = RequestBodyLimitMiddleware(
        _consume_body,
        default_limit=5,
        upload_limit=10,
    )

    declared = await _invoke(
        middleware,
        scope=_scope([(b"content-length", b"6")]),
    )
    streamed = await _invoke(
        middleware,
        request_messages=[
            {"type": "http.request", "body": b"123", "more_body": True},
            {"type": "http.request", "body": b"456", "more_body": False},
        ],
    )

    assert declared[0]["status"] == 413
    assert streamed[0]["status"] == 413
    assert json.loads(streamed[1]["body"]) == {"detail": "Request body is too large"}


@pytest.mark.asyncio
async def test_body_limit_rejects_ambiguous_request_framing() -> None:
    middleware = RequestBodyLimitMiddleware(
        _consume_body,
        default_limit=5,
        upload_limit=10,
    )
    sent = await _invoke(
        middleware,
        scope=_scope(
            [
                (b"content-length", b"3"),
                (b"transfer-encoding", b"chunked"),
            ]
        ),
    )
    assert sent[0]["status"] == 400


@pytest.mark.asyncio
async def test_body_stream_has_an_independent_deadline() -> None:
    middleware = RequestBodyLimitMiddleware(
        _consume_body,
        default_limit=5,
        upload_limit=10,
        body_timeout_seconds=0.001,
    )
    sent: list[dict[str, Any]] = []

    async def slow_receive() -> dict[str, Any]:
        await asyncio.sleep(0.05)
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await middleware(_scope(), slow_receive, send)

    assert sent[0]["status"] == 408
    assert json.loads(sent[1]["body"]) == {"detail": "Request body timed out"}


@pytest.mark.asyncio
async def test_request_context_replaces_invalid_id_and_sets_security_headers() -> None:
    async def responder(scope, receive, send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app = RequestContextMiddleware(
        SecurityHeadersMiddleware(
            responder,
            production=True,
            no_store_path_prefixes=("/api/",),
        )
    )
    sent = await _invoke(
        app,
        scope=_scope([(b"x-request-id", b" invalid request id ")]),
    )
    headers = dict(sent[0]["headers"])

    request_id = headers[b"x-request-id"].decode()
    assert REQUEST_ID_PATTERN.fullmatch(request_id)
    assert request_id != " invalid request id "
    assert headers[b"x-content-type-options"] == b"nosniff"
    assert headers[b"x-frame-options"] == b"DENY"
    assert headers[b"cache-control"] == b"no-store"
    assert headers[b"strict-transport-security"].startswith(b"max-age=")
    assert b"default-src 'none'" in headers[b"content-security-policy"]


@pytest.mark.asyncio
async def test_request_context_escapes_and_bounds_logged_path(caplog) -> None:
    async def responder(scope, receive, send) -> None:
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    scope = _scope()
    scope["path"] = "/safe\nforged-log-line" + ("x" * 1000)
    caplog.set_level(logging.INFO, logger="noki.http")

    await _invoke(RequestContextMiddleware(responder), scope=scope)

    message = caplog.records[-1].getMessage()
    assert "\n" not in message
    assert "\\nforged-log-line" in message
    assert len(message) < 800


@pytest.mark.asyncio
async def test_request_timeout_returns_gateway_timeout_before_response_start() -> None:
    async def slow_app(scope, receive, send) -> None:
        await asyncio.sleep(0.05)

    middleware = RequestTimeoutMiddleware(slow_app, timeout_seconds=0.001)
    sent = await _invoke(middleware)

    assert sent[0]["status"] == 504
    assert json.loads(sent[1]["body"]) == {"detail": "Request timed out"}


@pytest.mark.asyncio
async def test_request_timeout_exclusion_requires_exact_method_and_path() -> None:
    async def slow_app(scope, receive, send) -> None:
        await asyncio.sleep(0.02)
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = RequestTimeoutMiddleware(
        slow_app,
        timeout_seconds=0.001,
        excluded_method_paths=(("POST", "/api/v1/uploads/images"),),
    )
    exact_scope = _scope()
    exact_scope["path"] = "/api/v1/uploads/images"
    exact = await _invoke(middleware, scope=exact_scope)

    get_scope = _scope()
    get_scope["method"] = "GET"
    get_scope["path"] = "/api/v1/uploads/images/file.webp"
    get_result = await _invoke(middleware, scope=get_scope)

    suffix_scope = _scope()
    suffix_scope["path"] = "/api/v1/uploads/images-extra"
    suffix_result = await _invoke(middleware, scope=suffix_scope)

    assert exact[0]["status"] == 204
    assert get_result[0]["status"] == 504
    assert suffix_result[0]["status"] == 504
