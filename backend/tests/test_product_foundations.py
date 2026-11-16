from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.deps import enforce_mail_recipient_rate_limit
from app.core.config import settings
from app.schemas.auth import RegisterRequest
from app.services.mail import render_mail
from app.services.one_time_tokens import hash_token


def test_transactional_mail_escapes_user_controlled_html_and_urls() -> None:
    rendered = render_mail(
        "invitation",
        {
            "name": "<script>alert(1)</script>",
            "target_name": "R&D <Owners>",
            "action_url": 'https://noki.example/invite?token="unsafe"&next=<app>',
        },
    )

    assert "<script>" not in rendered.html
    assert "&lt;script&gt;" in rendered.html
    assert "R&amp;D &lt;Owners&gt;" in rendered.html
    assert "&quot;unsafe&quot;&amp;next=&lt;app&gt;" in rendered.html


def test_one_time_tokens_are_stored_as_fixed_length_hashes() -> None:
    raw = "single-use-token-value"

    digest = hash_token(raw)

    assert digest != raw
    assert len(digest) == 64
    assert digest == hash_token(raw)
    assert digest != hash_token(f"{raw}-different")


def test_registration_requires_both_legal_consents() -> None:
    base = {
        "name": "Team Member",
        "email": "member@example.com",
        "password": "a-strong-password",
    }

    for missing in ("accept_terms", "accept_privacy"):
        payload = {**base, "accept_terms": True, "accept_privacy": True}
        payload.pop(missing)
        try:
            RegisterRequest.model_validate(payload)
        except ValidationError:
            pass
        else:  # pragma: no cover - assertion branch
            raise AssertionError(f"{missing} must be required")


class _MailRateLimitRedis:
    def __init__(self, count: int, ttl: int = 120) -> None:
        self.count = count
        self.ttl = ttl
        self.key = ""

    async def eval(self, _script: str, _keys: int, key: str, _window: int) -> list[int]:
        self.key = key
        return [self.count, self.ttl]


@pytest.mark.asyncio
async def test_mail_recipient_limit_hashes_address_and_can_fail_silently() -> None:
    recipient = "Victim@Example.com"
    redis = _MailRateLimitRedis(settings.mail_recipient_rate_limit_attempts + 1)

    allowed = await enforce_mail_recipient_rate_limit(
        redis,  # type: ignore[arg-type]
        recipient=recipient,
        purpose="password-reset",
        silent=True,
    )

    assert allowed is False
    assert recipient.lower() not in redis.key


@pytest.mark.asyncio
async def test_mail_recipient_limit_returns_retry_after_for_authenticated_actions() -> None:
    redis = _MailRateLimitRedis(settings.mail_recipient_rate_limit_attempts + 1, ttl=77)

    with pytest.raises(HTTPException) as captured:
        await enforce_mail_recipient_rate_limit(
            redis,  # type: ignore[arg-type]
            recipient="invitee@example.com",
            purpose="invitation",
        )

    assert captured.value.status_code == 429
    assert captured.value.headers == {"Retry-After": "77"}
