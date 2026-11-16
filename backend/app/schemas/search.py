from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class SearchResult(BaseModel):
    id: UUID
    kind: Literal["task", "page"]
    title: str
    subtitle: str
    url: str
    updated_at: datetime


class SearchResponse(BaseModel):
    items: list[SearchResult]
    query: str
