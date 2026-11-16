from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import UserSummary


class StrictRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _normalize_comment_body(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Comment body is required")
    return value


class CommentCreate(StrictRequestModel):
    body: str = Field(min_length=1, max_length=4000)

    _normalize_body = field_validator("body")(_normalize_comment_body)


class CommentUpdate(StrictRequestModel):
    body: str = Field(min_length=1, max_length=4000)

    _normalize_body = field_validator("body")(_normalize_comment_body)


class CommentOut(BaseModel):
    id: UUID
    task_id: UUID
    body: str
    created_by: UserSummary
    created_at: datetime
    updated_at: datetime
