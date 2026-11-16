from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
from email_validator import EmailNotValidError, validate_email

from app.core.config import settings
from app.services.avatar_processing import InvalidAvatarError, validate_google_picture_url

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_RESPONSE_MAX_BYTES = 64 * 1024
GOOGLE_HTTP_TIMEOUT = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
GOOGLE_HTTP_LIMITS = httpx.Limits(max_connections=5, max_keepalive_connections=2)


class GoogleOAuthError(RuntimeError):
    pass


class GoogleOAuthUnavailableError(GoogleOAuthError):
    pass


@dataclass(slots=True)
class GoogleIdentity:
    sub: str
    email: str
    name: str
    picture_url: str | None = None


def build_google_authorization_url(state: str) -> str:
    query = urlencode(
        {
            "client_id": settings.google_client_id,
            "redirect_uri": settings.google_redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "access_type": "online",
            "prompt": "select_account",
        }
    )
    return f"{GOOGLE_AUTH_URL}?{query}"


async def _read_google_json(response: httpx.Response) -> dict[str, object]:
    declared_length = response.headers.get("Content-Length")
    if declared_length:
        try:
            if int(declared_length) > GOOGLE_RESPONSE_MAX_BYTES:
                raise GoogleOAuthUnavailableError("Google returned an oversized response")
        except ValueError:
            pass

    body = bytearray()
    async for chunk in response.aiter_bytes():
        if len(body) + len(chunk) > GOOGLE_RESPONSE_MAX_BYTES:
            raise GoogleOAuthUnavailableError("Google returned an oversized response")
        body.extend(chunk)
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError, RecursionError) as exc:
        raise GoogleOAuthUnavailableError("Google returned an invalid response") from exc
    if not isinstance(payload, dict):
        raise GoogleOAuthUnavailableError("Google returned an invalid response")
    return payload


async def fetch_google_identity(code: str) -> GoogleIdentity:
    try:
        async with httpx.AsyncClient(
            timeout=GOOGLE_HTTP_TIMEOUT,
            limits=GOOGLE_HTTP_LIMITS,
        ) as client:
            async with client.stream(
                "POST",
                GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "redirect_uri": settings.google_redirect_uri,
                    "grant_type": "authorization_code",
                },
            ) as token_response:
                if token_response.status_code == 429 or token_response.is_server_error:
                    raise GoogleOAuthUnavailableError("Google sign-in is temporarily unavailable")
                if token_response.is_error:
                    raise GoogleOAuthError("Google rejected the authorization code")
                token_payload = await _read_google_json(token_response)

            access_token = token_payload.get("access_token")
            if (
                not isinstance(access_token, str)
                or not access_token
                or len(access_token) > 8192
                or not access_token.isprintable()
                or any(character.isspace() for character in access_token)
            ):
                raise GoogleOAuthError("Google did not return a valid access token")

            async with client.stream(
                "GET",
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            ) as user_response:
                if user_response.status_code == 429 or user_response.is_server_error:
                    raise GoogleOAuthUnavailableError("Google sign-in is temporarily unavailable")
                if user_response.is_error:
                    raise GoogleOAuthError("Could not load Google profile")
                profile = await _read_google_json(user_response)
    except httpx.HTTPError as exc:
        raise GoogleOAuthUnavailableError("Google sign-in is temporarily unavailable") from exc

    if profile.get("email_verified") is not True:
        raise GoogleOAuthError("Google email is not verified")

    sub = profile.get("sub")
    email = profile.get("email")
    if (
        not isinstance(sub, str)
        or not 1 <= len(sub) <= 255
        or not sub.isprintable()
        or sub.strip() != sub
        or not isinstance(email, str)
        or len(email) > 320
    ):
        raise GoogleOAuthError("Google profile is incomplete")
    try:
        normalized_email = validate_email(
            email,
            check_deliverability=False,
        ).normalized
    except EmailNotValidError as exc:
        raise GoogleOAuthError("Google profile is incomplete") from exc
    if len(normalized_email) > 320:
        raise GoogleOAuthError("Google profile is incomplete")

    name = profile.get("name")
    if not isinstance(name, str) or not name.strip():
        name = normalized_email.split("@", maxsplit=1)[0]

    try:
        picture_url = validate_google_picture_url(profile.get("picture"))
    except InvalidAvatarError:
        # The optional profile photo is never allowed to make authentication
        # fail. It is simply skipped unless it passes the dedicated policy.
        picture_url = None

    return GoogleIdentity(
        sub=sub,
        email=normalized_email.lower(),
        name=name.strip()[:80],
        picture_url=picture_url,
    )
