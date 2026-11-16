from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.api.deps import CSRF, CurrentUser, DBSession, RedisClient, enforce_rate_limit
from app.core.config import settings
from app.models import SpaceExport
from app.schemas.exports import SpaceExportOut
from app.services.memberships import get_space_membership

router = APIRouter(tags=["Exports"])


@router.post(
    "/spaces/{space_id}/exports",
    response_model=SpaceExportOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_space_export(
    space_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
    redis: RedisClient,
    _: CSRF,
) -> SpaceExport:
    await get_space_membership(db, space_id=space_id, user_id=current_user.id)
    await enforce_rate_limit(
        redis,
        scope="space-export-user",
        identifier=str(current_user.id),
        limit=settings.export_rate_limit_attempts,
        window_seconds=settings.mail_rate_limit_window_seconds,
    )
    export = SpaceExport(space_id=space_id, requested_by_id=current_user.id)
    db.add(export)
    await db.commit()
    try:
        from app.worker.tasks import export_space_task

        export_space_task.apply_async(args=(str(export.id),), queue="celery")
    except Exception as exc:
        export.status = "failed"
        export.error = type(exc).__name__
        await db.commit()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Export worker is unavailable"
        ) from exc
    return export


@router.get("/spaces/{space_id}/exports", response_model=list[SpaceExportOut])
async def list_space_exports(
    space_id: UUID, current_user: CurrentUser, db: DBSession
) -> list[SpaceExport]:
    await get_space_membership(db, space_id=space_id, user_id=current_user.id)
    rows = await db.scalars(
        select(SpaceExport)
        .where(
            SpaceExport.space_id == space_id,
            SpaceExport.requested_by_id == current_user.id,
        )
        .order_by(SpaceExport.created_at.desc())
    )
    return list(rows)


@router.get("/exports/{export_id}/download", response_model=None)
async def download_space_export(
    export_id: UUID, current_user: CurrentUser, db: DBSession
) -> FileResponse:
    export = await db.get(SpaceExport, export_id)
    if export is None or export.requested_by_id != current_user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Export not found")
    if (
        export.status != "ready"
        or export.file_path is None
        or export.expires_at is None
        or export.expires_at <= datetime.now(UTC)
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "Export is not ready")
    root = settings.export_dir.resolve()
    path = Path(export.file_path).resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Export file is unavailable")
    return FileResponse(
        path, media_type="application/zip", filename=f"noki-space-{export.space_id}.zip"
    )
