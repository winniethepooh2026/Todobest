from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class NamedDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)


class AccountDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=320)


class TrashItem(BaseModel):
    kind: Literal["space", "team", "board", "page", "task"]
    id: UUID
    name: str
    deleted_at: datetime
