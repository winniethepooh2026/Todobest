from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Message(BaseModel):
    message: str


class UserSummary(BaseModel):
    id: UUID
    name: str
    email: EmailStr
    avatar_url: str | None


class ResourceSummary(ORMModel):
    id: UUID
    name: str
    created_at: datetime
