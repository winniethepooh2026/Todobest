from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from redis.exceptions import RedisError
from sqlalchemy import func, select
from starlette.background import BackgroundTask
from starlette.datastructures import FormData, UploadFile

from app.api.deps import (
    CSRF,
    CurrentUser,
    DBSession,
    RedisClient,
    acquire_distributed_lease,
    client_rate_limit_id,
    enforce_rate_limit,
    release_distributed_lease,
)
from app.core.config import settings
from app.models import IssueBoard, SpaceMember, Team, Upload, User
from app.schemas import Message, UploadOut
from app.services.access import get_page_for_user, get_task_for_user
from app.services.content_encryption import set_upload_original_name
from app.services.images import (
    InsufficientImageStorageError,
    InvalidImageError,
    ProcessedImage,
    UnsupportedImageFormatError,
    finalize_staged_image,
    open_image_for_read,
    process_and_store_image,
    restore_staged_image,
    safe_image_path,
    stage_image_deletion,
)

router = APIRouter(prefix="/uploads", tags=["Uploads"])
logger = logging.getLogger(__name__)
IMAGE_PROCESSING_CONCURRENCY = 2
UPLOAD_RECEIVE_CONCURRENCY = 8
IMAGE_PROCESSING_QUEUE_TIMEOUT_SECONDS = 0.1
UPLOAD_RECEIVE_QUEUE_TIMEOUT_SECONDS = 0.1
image_processing_slots = asyncio.Semaphore(IMAGE_PROCESSING_CONCURRENCY)
upload_receive_slots = asyncio.Semaphore(UPLOAD_RECEIVE_CONCURRENCY)


def _stream_image(stream: BinaryIO) -> Iterator[bytes]:
    try:
        while chunk := stream.read(64 * 1024):
            yield chunk
    finally:
        stream.close()


async def _acquire_image_processing_slot() -> None:
    try:
        await asyncio.wait_for(
            image_processing_slots.acquire(),
            timeout=IMAGE_PROCESSING_QUEUE_TIMEOUT_SECONDS,
        )
    except TimeoutError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Image processing is busy; retry shortly",
            headers={"Retry-After": "2"},
        ) from exc


async def _acquire_upload_receive_slot() -> None:
    try:
        await asyncio.wait_for(
            upload_receive_slots.acquire(),
            timeout=UPLOAD_RECEIVE_QUEUE_TIMEOUT_SECONDS,
        )
    except TimeoutError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Upload receiving is busy; retry shortly",
            headers={"Retry-After": "2"},
        ) from exc


async def _process_uploaded_image(file: UploadFile) -> ProcessedImage:
    try:
        raw = await file.read(settings.max_image_bytes + 1)
        if not raw:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Image file is empty")
        if len(raw) > settings.max_image_bytes:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                "Image exceeds the 25 MB limit",
            )

        try:
            return await asyncio.to_thread(process_and_store_image, raw)
        except InsufficientImageStorageError as exc:
            raise HTTPException(
                status.HTTP_507_INSUFFICIENT_STORAGE,
                str(exc),
            ) from exc
        except UnsupportedImageFormatError as exc:
            raise HTTPException(
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                str(exc),
            ) from exc
        except InvalidImageError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    finally:
        await file.close()


def _single_image_file(form: FormData) -> UploadFile:
    items = form.multi_items()
    if len(items) != 1 or items[0][0] != "file" or not isinstance(items[0][1], UploadFile):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Exactly one image file field named 'file' is required",
        )
    return items[0][1]


async def _reject_if_upload_quota_is_full(owner_id: UUID, db: DBSession) -> None:
    try:
        upload_count, total_bytes = (
            await db.execute(
                select(
                    func.count(Upload.id),
                    func.coalesce(func.sum(Upload.size_bytes), 0),
                ).where(Upload.owner_id == owner_id)
            )
        ).one()
    finally:
        # This is only an early rejection optimization. The authoritative
        # quota check is repeated under a user row lock after processing.
        await db.rollback()
    if int(upload_count) >= settings.upload_max_files_per_user:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Image file limit reached ({settings.upload_max_files_per_user})",
        )
    if int(total_bytes) >= settings.upload_max_total_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "Image storage quota exceeded",
        )


async def _process_and_persist_upload(
    owner_id: UUID,
    db: DBSession,
    file: UploadFile,
    *,
    space_id: UUID | None = None,
    task_id: UUID | None = None,
) -> UploadOut:
    processed = await _process_uploaded_image(file)

    original_name = Path(file.filename or "image").name[:255]
    try:
        # Serialize per-user accounting, but only after Pillow has finished
        # so the transaction does not stay open during heavy image work.
        await db.execute(select(User.id).where(User.id == owner_id).with_for_update())
        upload_count, total_bytes = (
            await db.execute(
                select(
                    func.count(Upload.id),
                    func.coalesce(func.sum(Upload.size_bytes), 0),
                ).where(Upload.owner_id == owner_id)
            )
        ).one()
        if int(upload_count) >= settings.upload_max_files_per_user:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Image file limit reached ({settings.upload_max_files_per_user})",
            )
        if int(total_bytes) + processed.size_bytes > settings.upload_max_total_bytes:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                "Image storage quota exceeded",
            )

        upload = Upload(
            id=uuid4(),
            filename=processed.filename,
            content_type="image/webp",
            size_bytes=processed.size_bytes,
            width=processed.width,
            height=processed.height,
            owner_id=owner_id,
            space_id=space_id,
            task_id=task_id,
        )
        set_upload_original_name(upload, original_name)
        db.add(upload)
        await db.commit()
    except Exception:
        await db.rollback()
        try:
            await asyncio.to_thread(processed.path.unlink, missing_ok=True)
        except OSError:
            logger.exception(
                "Could not remove image %s after database rollback",
                processed.filename,
            )
        raise
    await db.refresh(upload)

    return UploadOut(
        id=upload.id,
        url=f"/media/images/{upload.filename}",
        width=upload.width,
        height=upload.height,
        size_bytes=upload.size_bytes,
    )


@router.post("/images", response_model=UploadOut, status_code=status.HTTP_201_CREATED)
async def upload_image(
    request: Request,
    current_user: CurrentUser,
    db: DBSession,
    redis: RedisClient,
    _: CSRF,
    space_id: UUID | None = None,
    team_id: UUID | None = None,
    task_id: UUID | None = None,
) -> UploadOut:
    owner_id = current_user.id
    if task_id is not None:
        task = await get_task_for_user(db, task_id, owner_id)
        board = await db.get(IssueBoard, task.board_id)
        if board is None or (team_id is not None and board.team_id != team_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
        team_id = board.team_id
    if team_id is not None:
        team = await db.get(Team, team_id)
        if team is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Team not found")
        if space_id is not None and space_id != team.space_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Space not found")
        space_id = team.space_id
    if space_id is not None:
        membership = await db.get(SpaceMember, (space_id, owner_id))
        if membership is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Space not found")
    # Authentication loaded the user through this session. Release that
    # transaction before rate limiting, waiting for an upload slot, receiving a
    # slow body or running Pillow; quota persistence opens a fresh transaction.
    await db.rollback()
    await enforce_rate_limit(
        redis,
        scope="upload-user",
        identifier=str(owner_id),
        limit=settings.upload_rate_limit_attempts,
        window_seconds=settings.upload_rate_limit_window_seconds,
    )
    await enforce_rate_limit(
        redis,
        scope="upload-ip",
        identifier=client_rate_limit_id(request),
        limit=settings.upload_ip_rate_limit_attempts,
        window_seconds=settings.upload_rate_limit_window_seconds,
    )
    lease_token = await acquire_distributed_lease(
        redis,
        scope="upload-user",
        identifier=str(owner_id),
        ttl_seconds=max(60, settings.request_timeout_seconds * 4),
    )
    try:
        await _reject_if_upload_quota_is_full(owner_id, db)

        # FastAPI body parameters are parsed before dependencies. Parse
        # multipart manually only after authentication, CSRF and admission
        # controls. Slow clients occupy a separate bounded receive pool, never
        # the smaller Pillow CPU pool.
        await _acquire_upload_receive_slot()
        try:
            async with request.form(
                max_files=1,
                max_fields=0,
                max_part_size=settings.max_image_bytes + 1024 * 1024,
            ) as form:
                file = _single_image_file(form)
                await _acquire_image_processing_slot()
                try:
                    return await _process_and_persist_upload(
                        owner_id,
                        db,
                        file,
                        space_id=space_id,
                        task_id=task_id,
                    )
                finally:
                    image_processing_slots.release()
        finally:
            upload_receive_slots.release()
    finally:
        try:
            await release_distributed_lease(
                redis,
                scope="upload-user",
                identifier=str(owner_id),
                token=lease_token,
            )
        except RedisError:
            # The lease has a TTL, and masking a successfully committed upload
            # with a release failure would make clients retry and create
            # duplicates.
            logger.exception("Could not release upload lease for owner %s", owner_id)


@router.get("/images/{filename}", response_class=StreamingResponse)
async def get_image(
    filename: str,
    current_user: CurrentUser,
    db: DBSession,
) -> StreamingResponse:
    try:
        safe_image_path(filename)
    except InvalidImageError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found") from exc

    upload = await db.scalar(select(Upload).where(Upload.filename == filename))
    if upload is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found")
    if upload.owner_id != current_user.id:
        if upload.page_id is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found")
        await get_page_for_user(db, upload.page_id, current_user.id)

    try:
        opened = open_image_for_read(filename)
    except InvalidImageError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found") from exc

    return StreamingResponse(
        _stream_image(opened.stream),
        media_type="image/webp",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Length": str(opened.size_bytes),
        },
        background=BackgroundTask(opened.stream.close),
    )


@router.delete("/images/{filename}", response_model=Message)
async def delete_image(
    filename: str,
    current_user: CurrentUser,
    db: DBSession,
    _: CSRF,
) -> Message:
    upload = await db.scalar(
        select(Upload)
        .where(
            Upload.filename == filename,
            Upload.owner_id == current_user.id,
        )
        .with_for_update()
    )
    if upload is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found")
    if upload.page_id is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Remove the image from the Page before deleting it",
        )

    try:
        staged = await asyncio.to_thread(stage_image_deletion, filename)
    except InvalidImageError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found") from exc
    except OSError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Image is currently in use; retry shortly",
            headers={"Retry-After": "2"},
        ) from exc

    await db.delete(upload)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        try:
            await asyncio.to_thread(restore_staged_image, staged)
        except OSError:
            logger.exception(
                "Could not restore staged image %s after database rollback",
                filename,
            )
        raise

    try:
        await asyncio.to_thread(finalize_staged_image, staged)
    except OSError:
        logger.exception("Could not finalize deletion of image %s", filename)
    return Message(message="Image deleted")
