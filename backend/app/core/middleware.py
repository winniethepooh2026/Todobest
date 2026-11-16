from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("noki.http")
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class RequestBodyTooLarge(RuntimeError):
    """Raised as soon as a streamed request exceeds its route-specific limit."""


class RequestBodyTimeout(RuntimeError):
    """Raised when a client does not finish streaming its request body in time."""


class RequestBodyLimitMiddleware:
    """Enforce body limits for both Content-Length and streamed/chunked requests."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        default_limit: int,
        upload_limit: int,
        large_body_limit: int | None = None,
        large_body_path_prefixes: tuple[str, ...] = (),
        body_timeout_seconds: float | None = None,
        upload_path_suffix: str = "/uploads/images",
        public_api_prefix: str | None = None,
    ) -> None:
        self.app = app
        self.default_limit = default_limit
        self.upload_limit = upload_limit
        self.large_body_limit = large_body_limit
        self.large_body_path_prefixes = large_body_path_prefixes
        self.body_timeout_seconds = body_timeout_seconds
        self.upload_path_suffix = upload_path_suffix
        self.public_api_prefix = public_api_prefix

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path", ""))
        if path.endswith(self.upload_path_suffix):
            maximum = self.upload_limit
        elif self.large_body_limit is not None and path.startswith(self.large_body_path_prefixes):
            maximum = self.large_body_limit
        else:
            maximum = self.default_limit
        raw_headers = scope.get("headers", [])
        content_lengths = [value for key, value in raw_headers if key.lower() == b"content-length"]
        transfer_encoding = any(key.lower() == b"transfer-encoding" for key, _ in raw_headers)
        if len(content_lengths) > 1 or (content_lengths and transfer_encoding):
            await self._send_error(
                send,
                400,
                "Ambiguous request framing",
                scope=scope,
                public_api_prefix=self.public_api_prefix,
            )
            return

        content_length = content_lengths[0] if content_lengths else None
        if content_length is not None:
            if not content_length.isdigit():
                await self._send_error(
                    send,
                    400,
                    "Content-Length must be a non-negative integer",
                    scope=scope,
                    public_api_prefix=self.public_api_prefix,
                )
                return
            declared_length = int(content_length)
            if declared_length > maximum:
                await self._send_error(
                    send,
                    413,
                    "Request body is too large",
                    scope=scope,
                    public_api_prefix=self.public_api_prefix,
                )
                return

        received = 0
        response_started = False
        body_deadline = (
            asyncio.get_running_loop().time() + self.body_timeout_seconds
            if self.body_timeout_seconds is not None
            else None
        )

        async def limited_receive() -> Message:
            nonlocal received
            if body_deadline is None:
                message = await receive()
            else:
                remaining = body_deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise RequestBodyTimeout
                try:
                    async with asyncio.timeout(remaining):
                        message = await receive()
                except TimeoutError as exc:
                    raise RequestBodyTimeout from exc
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > maximum:
                    raise RequestBodyTooLarge
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except RequestBodyTooLarge:
            if response_started:
                raise
            await self._send_error(
                send,
                413,
                "Request body is too large",
                scope=scope,
                public_api_prefix=self.public_api_prefix,
            )
        except RequestBodyTimeout:
            if response_started:
                raise
            await self._send_error(
                send,
                408,
                "Request body timed out",
                scope=scope,
                public_api_prefix=self.public_api_prefix,
            )

    @staticmethod
    async def _send_error(
        send: Send,
        status_code: int,
        detail: str,
        *,
        scope: Scope | None = None,
        public_api_prefix: str | None = None,
    ) -> None:
        path = str(scope.get("path", "")) if scope is not None else ""
        is_public_api = bool(public_api_prefix) and (
            path == public_api_prefix or path.startswith(f"{public_api_prefix}/")
        )
        if is_public_api:
            codes = {
                400: "bad_request",
                408: "request_timeout",
                413: "payload_too_large",
                504: "request_timeout",
            }
            state = scope.get("state", {}) if scope is not None else {}
            payload = {
                "error": {
                    "code": codes.get(status_code, "http_error"),
                    "message": detail,
                    "request_id": state.get("request_id"),
                }
            }
        else:
            payload = {"detail": detail}
        body = json.dumps(payload, separators=(",", ":")).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"cache-control", b"no-store"),
                    (b"x-content-type-options", b"nosniff"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


class RequestTimeoutMiddleware:
    """Cancel requests that exceed the application processing deadline."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        timeout_seconds: float,
        excluded_method_paths: tuple[tuple[str, str], ...] = (),
        public_api_prefix: str | None = None,
    ) -> None:
        self.app = app
        self.timeout_seconds = timeout_seconds
        self.excluded_method_paths = {
            (method.upper(), path) for method, path in excluded_method_paths
        }
        self.public_api_prefix = public_api_prefix

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        method_path = (
            str(scope.get("method", "")).upper(),
            str(scope.get("path", "")),
        )
        if method_path in self.excluded_method_paths:
            await self.app(scope, receive, send)
            return

        response_started = False

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            async with asyncio.timeout(self.timeout_seconds):
                await self.app(scope, receive, tracked_send)
        except TimeoutError:
            if response_started:
                raise
            await RequestBodyLimitMiddleware._send_error(
                send,
                504,
                "Request timed out",
                scope=scope,
                public_api_prefix=self.public_api_prefix,
            )


class SecurityHeadersMiddleware:
    """Attach browser hardening headers to every HTTP response."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        production: bool,
        no_store_path_prefixes: tuple[str, ...] = (),
    ) -> None:
        self.app = app
        self.production = production
        self.no_store_path_prefixes = no_store_path_prefixes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                existing = {key.lower() for key, _ in headers}
                additions = [
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"no-referrer"),
                    (
                        b"permissions-policy",
                        b"camera=(), geolocation=(), microphone=(), payment=(), usb=()",
                    ),
                ]
                if str(scope.get("path", "")).startswith(self.no_store_path_prefixes):
                    additions.append((b"cache-control", b"no-store"))
                if self.production:
                    additions.extend(
                        [
                            (
                                b"strict-transport-security",
                                b"max-age=31536000; includeSubDomains",
                            ),
                            (
                                b"content-security-policy",
                                b"default-src 'none'; base-uri 'none'; frame-ancestors 'none'",
                            ),
                        ]
                    )
                headers.extend((key, value) for key, value in additions if key not in existing)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


class RequestContextMiddleware:
    """Provide a bounded request id and one sanitized access-log event per request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_headers = {key.lower(): value for key, value in scope.get("headers", [])}
        try:
            supplied_request_id = request_headers.get(b"x-request-id", b"").decode("ascii")
        except UnicodeDecodeError:
            supplied_request_id = ""
        request_id = (
            supplied_request_id
            if REQUEST_ID_PATTERN.fullmatch(supplied_request_id)
            else str(uuid4())
        )
        scope.setdefault("state", {})["request_id"] = request_id
        started_at = time.perf_counter()
        status_code = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                headers = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() != b"x-request-id"
                ]
                headers.append((b"x-request-id", request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            method = str(scope.get("method", "-"))[:32]
            path = str(scope.get("path", "-"))[:512]
            logger.exception(
                "request_failed request_id=%s method=%r path=%r",
                request_id,
                method,
                path,
            )
            raise
        finally:
            duration_ms = (time.perf_counter() - started_at) * 1000
            method = str(scope.get("method", "-"))[:32]
            path = str(scope.get("path", "-"))[:512]
            logger.info(
                "request_complete request_id=%s method=%r path=%r status=%d duration_ms=%.1f",
                request_id,
                method,
                path,
                status_code,
                duration_ms,
            )
