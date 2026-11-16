from __future__ import annotations

import unicodedata
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)


def _reject_non_content_password(value: str) -> str:
    if all(
        character.isspace() or unicodedata.category(character).startswith("C")
        for character in value
    ):
        raise ValueError("Password must contain a visible character")
    return value


def _normalize_display_name(value: str) -> str:
    value = " ".join(value.split())
    if len(value) < 2:
        raise ValueError("Name must contain at least 2 characters")
    return value


def _normalize_bio(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if any(
        unicodedata.category(character).startswith("C") and character not in "\n\t"
        for character in value
    ):
        raise ValueError("Bio must not contain control characters")
    return value


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterRequest(StrictRequest):
    name: str = Field(min_length=2, max_length=80)
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    accept_terms: Literal[True]
    accept_privacy: Literal[True]

    _normalize_name = field_validator("name")(_normalize_display_name)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()

    _validate_password_content = field_validator("password")(_reject_non_content_password)

    @model_validator(mode="after")
    def password_must_differ_from_email(self) -> RegisterRequest:
        if self.password.casefold() == str(self.email).casefold():
            raise ValueError("Password must not match email")
        return self


class LoginRequest(StrictRequest):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    mfa_code: str | None = Field(default=None, min_length=6, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()


class UserOut(BaseModel):
    id: UUID
    email: EmailStr
    name: str
    bio: str | None
    avatar_url: str | None
    timezone: str
    has_password: bool
    google_connected: bool
    is_platform_admin: bool
    email_verified: bool
    totp_enabled: bool = False
    created_at: datetime


class TotpSetupRequest(StrictRequest):
    password: str = Field(min_length=1, max_length=128)


class TotpSetupOut(BaseModel):
    secret: str
    otpauth_uri: str


class TotpCodeRequest(StrictRequest):
    code: str = Field(min_length=6, max_length=128)


class TotpConfirmOut(BaseModel):
    recovery_codes: list[str]


class SessionOut(BaseModel):
    id: UUID
    user_agent: str | None
    ip_address: str | None
    created_at: datetime
    last_seen_at: datetime | None
    expires_at: datetime
    current: bool


class AuthResponse(BaseModel):
    user: UserOut


class ChangePasswordRequest(StrictRequest):
    old_password: str | None = Field(default=None, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)
    new_password_confirm: str = Field(min_length=12, max_length=128)

    _validate_password_content = field_validator("new_password")(_reject_non_content_password)

    @model_validator(mode="after")
    def passwords_match(self) -> ChangePasswordRequest:
        if self.new_password != self.new_password_confirm:
            raise ValueError("New passwords do not match")
        return self


class EmailRequest(StrictRequest):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()


class TokenRequest(StrictRequest):
    token: str = Field(min_length=32, max_length=256)


class ResetPasswordRequest(TokenRequest):
    new_password: str = Field(min_length=12, max_length=128)
    new_password_confirm: str = Field(min_length=12, max_length=128)

    _validate_password_content = field_validator("new_password")(_reject_non_content_password)

    @model_validator(mode="after")
    def passwords_match(self) -> ResetPasswordRequest:
        if self.new_password != self.new_password_confirm:
            raise ValueError("New passwords do not match")
        return self


class UpdateProfileRequest(StrictRequest):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    bio: str | None = Field(default=None, max_length=280)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        return None if value is None else _normalize_display_name(value)

    _validate_bio = field_validator("bio")(_normalize_bio)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Unknown IANA timezone") from exc
        return value
