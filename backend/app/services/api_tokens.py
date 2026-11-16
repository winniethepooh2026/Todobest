from __future__ import annotations

import hashlib
import hmac
import re
import secrets

from app.core.config import settings

API_TOKEN_PREFIX = "noki_pat_"  # noqa: S105 -- public format marker, not a credential
API_TOKEN_SECRET_BYTES = 32
API_TOKEN_DISPLAY_CHARS = 17
API_TOKEN_PATTERN = re.compile(r"^noki_pat_[A-Za-z0-9_-]{43}$")


def generate_api_token() -> tuple[str, str, str]:
    token = f"{API_TOKEN_PREFIX}{secrets.token_urlsafe(API_TOKEN_SECRET_BYTES)}"
    return token, hash_api_token(token), token[:API_TOKEN_DISPLAY_CHARS]


def hash_api_token(token: str) -> str:
    return hmac.new(
        settings.jwt_secret.encode("utf-8"),
        token.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def is_api_token(value: str) -> bool:
    return API_TOKEN_PATTERN.fullmatch(value) is not None


def serialize_api_token_scopes(scopes: list[str]) -> str:
    selected = set(scopes)
    if "write" in selected:
        selected.add("read")
    return ",".join(scope for scope in ("read", "write") if scope in selected)


def parse_api_token_scopes(scopes: str) -> frozenset[str]:
    return frozenset(scopes.split(","))
