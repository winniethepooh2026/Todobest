from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class SpaceExportOut(BaseModel):
    id: UUID
    space_id: UUID
    status: str
    expires_at: datetime | None
    completed_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}
