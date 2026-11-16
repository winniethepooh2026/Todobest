from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class NavigationBoard(BaseModel):
    id: UUID
    name: str
    key: str


class NavigationPage(BaseModel):
    id: UUID
    title: str


class NavigationTeam(BaseModel):
    id: UUID
    name: str
    boards: list[NavigationBoard]
    pages: list[NavigationPage]


class NavigationSpace(BaseModel):
    id: UUID
    name: str
    role: Literal["owner", "admin", "member"]
    teams: list[NavigationTeam]
