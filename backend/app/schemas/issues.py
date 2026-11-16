from __future__ import annotations

from datetime import datetime
from typing import Literal
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

MAX_TASK_ORDER_ITEMS = 1000


class StrictRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BoardCreate(StrictRequestModel):
    name: str = Field(min_length=1, max_length=100)
    key: str = Field(pattern=r"^[A-Z]{2,5}$")

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Board name is required")
        return value

    @field_validator("key", mode="before")
    @classmethod
    def normalize_key(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value


class BoardUpdate(StrictRequestModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = " ".join(value.split())
        if not value:
            raise ValueError("Board name is required")
        return value


class BoardSummary(ORMModel):
    id: UUID
    team_id: UUID
    name: str
    key: str
    created_at: datetime


class ColumnOut(ORMModel):
    id: UUID
    name: str
    position: int
    system_status: IssueStatus | None
    color: str | None
    is_default: bool


class ColumnDefaultUpdate(StrictRequestModel):
    column_id: UUID


class TaskCreate(StrictRequestModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    assignee_id: UUID | None = None
    deadline: AwareDatetime | None = None
    status_id: UUID | None = None
    priority: Literal["none", "low", "medium", "high", "urgent"] = "none"
    estimate: int | None = Field(default=None, ge=0, le=100000)
    parent_task_id: UUID | None = None
    label_ids: list[UUID] = Field(default_factory=list, max_length=20)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Task title is required")
        return value


class TaskUpdate(StrictRequestModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    assignee_id: UUID | None = None
    deadline: AwareDatetime | None = None
    status_id: UUID | None = None
    priority: Literal["none", "low", "medium", "high", "urgent"] | None = None
    estimate: int | None = Field(default=None, ge=0, le=100000)
    parent_task_id: UUID | None = None
    label_ids: list[UUID] | None = Field(default=None, max_length=20)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = " ".join(value.split())
        if not value:
            raise ValueError("Task title is required")
        return value

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> TaskUpdate:
        if "title" in self.model_fields_set and self.title is None:
            raise ValueError("Task title cannot be null")
        if "status_id" in self.model_fields_set and self.status_id is None:
            raise ValueError("Task status cannot be null")
        if "priority" in self.model_fields_set and self.priority is None:
            raise ValueError("Task priority cannot be null")
        return self


class TaskStatusUpdate(StrictRequestModel):
    status: IssueStatus


class TaskLabelOut(ORMModel):
    id: UUID
    name: str
    color: str


class TaskCard(BaseModel):
    id: UUID
    board_id: UUID
    status_id: UUID
    number: int
    code: str
    title: str
    assignee: UserSummary | None
    created_by: UserSummary
    deadline: datetime | None
    priority: Literal["none", "low", "medium", "high", "urgent"]
    estimate: int | None
    parent_task_id: UUID | None
    labels: list[TaskLabelOut]
    position: int
    created_at: datetime
    updated_at: datetime


class TaskOut(TaskCard):
    description: str


class BoardDetail(BaseModel):
    id: UUID
    team_id: UUID
    name: str
    key: str
    columns: list[ColumnOut]
    tasks: list[TaskCard]
    labels: list[TaskLabelOut]
    has_more_by_column: dict[UUID, bool]
    current_user_id: UUID
    can_create_tasks: bool
    can_manage_tasks: bool
    can_claim_tasks: bool
    created_at: datetime
    updated_at: datetime


class TaskCardPage(BaseModel):
    items: list[TaskCard]
    total: int
    offset: int
    limit: int


class MyTaskPage(BaseModel):
    items: list[TaskCard]
    next_cursor: str | None


class TaskLabelCreate(StrictRequestModel):
    name: str = Field(min_length=1, max_length=40)
    color: str = Field(default="#71717a", pattern=r"^#[0-9a-fA-F]{6}$")

    @field_validator("name")
    @classmethod
    def normalize_label_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Label name is required")
        return value


class TaskRelationCreate(StrictRequestModel):
    target_task_id: UUID
    kind: Literal["blocks", "relates_to", "duplicates"] = "relates_to"


class TaskRelationOut(ORMModel):
    id: UUID
    source_task_id: UUID
    target_task_id: UUID
    kind: Literal["blocks", "relates_to", "duplicates"]
    created_at: datetime


class TaskActivityOut(ORMModel):
    id: UUID
    task_id: UUID
    actor_id: UUID | None
    action: str
    field: str | None
    summary: str
    created_at: datetime


class ColumnConfig(StrictRequestModel):
    id: UUID | None = None
    name: str = Field(min_length=1, max_length=40)
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Column name is required")
        return value


class BoardColumnsUpdate(StrictRequestModel):
    columns: list[ColumnConfig] = Field(min_length=1, max_length=10)

    @field_validator("columns")
    @classmethod
    def unique_column_names(cls, columns: list[ColumnConfig]) -> list[ColumnConfig]:
        normalized = [column.name.casefold() for column in columns]
        if len(normalized) != len(set(normalized)):
            raise ValueError("Column names must be unique")
        ids = [column.id for column in columns if column.id is not None]
        if len(ids) != len(set(ids)):
            raise ValueError("Column ids must be unique")
        return columns


class TaskOrderColumn(StrictRequestModel):
    column_id: UUID
    task_ids: list[UUID] = Field(max_length=MAX_TASK_ORDER_ITEMS)


class TaskOrderRequest(StrictRequestModel):
    columns: list[TaskOrderColumn] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def validate_bounded_unique_order(self) -> TaskOrderRequest:
        column_ids = [column.column_id for column in self.columns]
        if len(column_ids) != len(set(column_ids)):
            raise ValueError("Board column appears more than once")

        task_ids = [task_id for column in self.columns for task_id in column.task_ids]
        if len(task_ids) > MAX_TASK_ORDER_ITEMS:
            raise ValueError(f"Task order cannot contain more than {MAX_TASK_ORDER_ITEMS} tasks")
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("Task appears more than once")
        return self
