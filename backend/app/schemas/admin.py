from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr

from app.schemas.auth import StrictRequest


class AdminOverviewOut(BaseModel):
    total_users: int
    new_users_today: int
    new_users_7d: int
    new_users_30d: int
    active_users_24h: int
    active_users_7d: int
    active_users_30d: int
    total_spaces: int
    total_teams: int
    total_boards: int
    total_pages: int
    total_tasks: int


class AdminUserOut(BaseModel):
    id: UUID
    email: EmailStr
    name: str
    avatar_url: str | None
    is_platform_admin: bool
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None
    space_count: int
    team_count: int


class AdminUsersPageOut(BaseModel):
    items: list[AdminUserOut]
    total: int
    limit: int
    offset: int


class AdminUpdateUserRequest(StrictRequest):
    is_platform_admin: bool | None = None
    is_active: bool | None = None
    force_logout: bool = False


class AdminStepUpRequest(StrictRequest):
    password: str
    mfa_code: str


class AdminStepUpOut(BaseModel):
    token: str
    expires_in_seconds: int = 600


class AdminFunnelStepOut(BaseModel):
    label: str
    count: int


class AdminFunnelOut(BaseModel):
    steps: list[AdminFunnelStepOut]


class AdminRegistrationPointOut(BaseModel):
    date: str
    count: int


class AdminRegistrationsOut(BaseModel):
    points: list[AdminRegistrationPointOut]
