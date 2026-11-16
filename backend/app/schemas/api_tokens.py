from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

ApiTokenScope = Literal["read", "write"]


class ApiTokenCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    scopes: list[ApiTokenScope] = Field(default_factory=lambda: ["read"], min_length=1)
    expires_in_days: int = Field(default=90, ge=1, le=365)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Token name is required")
        return value

    @field_validator("scopes")
    @classmethod
    def normalize_scopes(cls, value: list[ApiTokenScope]) -> list[ApiTokenScope]:
        if len(value) != len(set(value)):
            raise ValueError("Token scopes must be unique")
        selected = set(value)
        if "write" in selected:
            selected.add("read")
        return [scope for scope in ("read", "write") if scope in selected]


class ApiTokenOut(BaseModel):
    id: UUID
    name: str
    prefix: str
    scopes: list[ApiTokenScope]
    expires_at: datetime
    last_used_at: datetime | None
    created_at: datetime


class ApiTokenCreated(ApiTokenOut):
    token: str
