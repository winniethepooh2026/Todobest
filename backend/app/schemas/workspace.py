from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.schemas.common import ORMModel

SpaceRole = Literal["owner", "admin", "member"]
TeamRole = Literal["owner", "admin", "member"]


class StrictRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SpaceCreate(StrictRequestModel):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Space name is required")
        return value


class SpaceUpdate(SpaceCreate):
    pass


class SpaceOut(ORMModel):
    id: UUID
    name: str
    created_at: datetime
    updated_at: datetime


class SpaceMemberCreate(StrictRequestModel):
    email: EmailStr
    role: SpaceRole = "member"

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()


class SpaceMemberUpdate(StrictRequestModel):
    role: SpaceRole


class SpaceMemberOut(BaseModel):
    user_id: UUID
    email: EmailStr
    name: str
    avatar_url: str | None
    role: SpaceRole
    created_at: datetime


class SpaceMembersOut(BaseModel):
    current_user_role: SpaceRole
    can_manage_members: bool
    members: list[SpaceMemberOut]


class TeamCreate(StrictRequestModel):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Team name is required")
        return value


class TeamUpdate(TeamCreate):
    pass


class TeamOut(ORMModel):
    id: UUID
    space_id: UUID
    name: str
    created_at: datetime
    updated_at: datetime


class TeamMemberCreate(StrictRequestModel):
    user_id: UUID
    role: TeamRole = "member"


class TeamMemberUpdate(StrictRequestModel):
    role: TeamRole


class TeamMemberOut(BaseModel):
    user_id: UUID
    email: EmailStr
    name: str
    avatar_url: str | None
    is_active: bool
    role: TeamRole


class TeamMembersOut(BaseModel):
    current_user_space_role: SpaceRole
    current_user_team_role: TeamRole | None
    can_manage_members: bool
    can_manage_owner_role: bool
    members: list[TeamMemberOut]
