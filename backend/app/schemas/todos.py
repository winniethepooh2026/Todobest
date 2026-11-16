from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.models import IssueStatus
from app.schemas.common import ORMModel, UserSummary


class StrictRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TodoCreate(StrictRequestModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    deadline: AwareDatetime | None = None
    status: IssueStatus = IssueStatus.TODO
    position: int = Field(default=0, ge=0)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Todo title is required")
        return value


class TodoUpdate(StrictRequestModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    deadline: AwareDatetime | None = None
    status: IssueStatus | None = None
    position: int | None = Field(default=None, ge=0)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = " ".join(value.split())
        if not value:
            raise ValueError("Todo title is required")
        return value

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> TodoUpdate:
        required_fields = ("title", "description", "status", "position")
        for field_name in required_fields:
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"Todo {field_name} cannot be null")
        return self


class TodoOut(ORMModel):
    id: UUID
    title: str
    description: str
    deadline: datetime | None
    status: IssueStatus
    position: int
    completed_by: UserSummary | None
    created_at: datetime
    updated_at: datetime
