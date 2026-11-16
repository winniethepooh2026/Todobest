from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, EmailStr

from app.schemas.comments import CommentOut
from app.schemas.issues import ColumnOut, TaskCreate, TaskOut


class PublicApiInfo(BaseModel):
    name: str
    version: str
    openapi_url: str


class PublicApiErrorDetail(BaseModel):
    code: str
    message: str
    details: list[dict[str, Any]] | None = None
    request_id: str | None = None


class PublicApiError(BaseModel):
    error: PublicApiErrorDetail


class PublicUserOut(BaseModel):
    id: UUID
    email: EmailStr
    name: str
    avatar_url: str | None
    timezone: str


class PublicBoardOut(BaseModel):
    id: UUID
    team_id: UUID
    name: str
    key: str
    columns: list[ColumnOut]
    created_at: datetime
    updated_at: datetime


class PublicTaskCreate(TaskCreate):
    board_id: UUID


class PublicTaskPage(BaseModel):
    items: list[TaskOut]
    total: int
    limit: int
    offset: int


class PublicCommentPage(BaseModel):
    items: list[CommentOut]
    total: int
    limit: int
    offset: int


class PublicApiTokenOut(BaseModel):
    id: UUID
    name: str
    prefix: str
    scopes: list[str]
    expires_at: datetime
    last_used_at: datetime | None
    created_at: datetime


class PublicApiTokenCreated(PublicApiTokenOut):
    token: str
