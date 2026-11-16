from __future__ import annotations

import asyncio
import json
import re
import zipfile
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
from celery.utils.log import get_task_logger
from sqlalchemy import delete, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.db.options import postgres_connect_args
from app.models import (
    Comment,
    IssueBoard,
    Page,
    Space,
    SpaceExport,
    Task,
    Team,
    Upload,
    User,
    UserSession,
)
from app.services.antivirus import MalwareDetectedError, MalwareScannerUnavailableError
from app.services.avatar_processing import (
    AvatarSourceUnavailableError,
    InvalidAvatarError,
    validate_google_picture_url,
)
from app.services.avatars import AvatarImportResult, import_google_avatar
from app.services.content_encryption import (
    get_comment_body,
    get_page_content,
    get_page_markdown,
    get_page_title,
    get_task_description,
    get_task_title,
)
from app.services.images import (
    InvalidImageError,
    StagedImageDeletion,
    finalize_staged_image,
    list_staged_image_deletions,
    list_stored_image_paths,
    restore_staged_image,
    safe_image_path,
    stage_image_deletion,
)
from app.services.mail import MailKind, enqueue_mail, send_mail
from app.services.object_storage import (
    AvatarStorageError,
    delete_avatar_objects,
    list_avatar_objects,
)
from app.worker.celery_app import celery_app

logger = get_task_logger(__name__)

CLEANUP_BATCH_SIZE = 100
CLEANUP_ADVISORY_LOCK_ID = 1_316_381_513
STAGED_RECONCILIATION_AGE = timedelta(hours=1)
UNTRACKED_IMAGE_GRACE_AGE = timedelta(hours=24)
AVATAR_ORPHAN_GRACE_AGE = timedelta(hours=24)
AVATAR_CLEANUP_ADVISORY_LOCK_ID = 1_316_381_514


@celery_app.task(
    bind=True,
    name="noki.send_mail",
    autoretry_for=(httpx.HTTPError, RuntimeError),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=6,
    rate_limit="120/m",
    ignore_result=True,
    soft_time_limit=30,
    time_limit=45,
)
def send_mail_task(
    self,
    recipient: str,
    kind: MailKind,
    context: dict[str, object],
    idempotency_key: str,
) -> dict[str, str]:
    message_id = send_mail(
        recipient=recipient,
        kind=kind,
        context=context,
        idempotency_key=idempotency_key,
    )
    return {"message_id": message_id}


def _safe_export_name(value: str, fallback: str) -> str:
    value = re.sub(r"[^\w.-]+", "-", value, flags=re.UNICODE).strip("-.")
    return value[:80] or fallback


async def _build_space_export(export_id: UUID) -> str:
    engine = create_async_engine(settings.database_url, **_cleanup_engine_options())
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as db:
            export = await db.scalar(
                select(SpaceExport).where(SpaceExport.id == export_id).with_for_update()
            )
            if export is None:
                raise ValueError("Export not found")
            export.status = "processing"
            await db.commit()
            space = await db.get(Space, export.space_id)
            if space is None:
                raise ValueError("Space not found")
            teams = list(await db.scalars(select(Team).where(Team.space_id == space.id)))
            team_ids = [team.id for team in teams]
            boards = (
                list(await db.scalars(select(IssueBoard).where(IssueBoard.team_id.in_(team_ids))))
                if team_ids
                else []
            )
            pages = (
                list(await db.scalars(select(Page).where(Page.team_id.in_(team_ids))))
                if team_ids
                else []
            )
            board_ids = [board.id for board in boards]
            tasks = (
                list(await db.scalars(select(Task).where(Task.board_id.in_(board_ids))))
                if board_ids
                else []
            )
            task_ids = [task.id for task in tasks]
            comments = (
                list(await db.scalars(select(Comment).where(Comment.task_id.in_(task_ids))))
                if task_ids
                else []
            )
            page_ids = [page.id for page in pages]
            uploads = (
                list(await db.scalars(select(Upload).where(Upload.page_id.in_(page_ids))))
                if page_ids
                else []
            )

            comments_by_task: dict[UUID, list[Comment]] = {}
            for comment in comments:
                comments_by_task.setdefault(comment.task_id, []).append(comment)
            payload = {
                "exported_at": datetime.now(UTC).isoformat(),
                "space": {"id": str(space.id), "name": space.name},
                "teams": [{"id": str(team.id), "name": team.name} for team in teams],
                "boards": [
                    {
                        "id": str(board.id),
                        "team_id": str(board.team_id),
                        "name": board.name,
                        "key": board.key,
                    }
                    for board in boards
                ],
                "pages": [
                    {
                        "id": str(page.id),
                        "team_id": str(page.team_id),
                        "title": get_page_title(page),
                        "content": get_page_content(page),
                        "markdown": get_page_markdown(page),
                    }
                    for page in pages
                ],
                "tasks": [
                    {
                        "id": str(task.id),
                        "board_id": str(task.board_id),
                        "number": task.number,
                        "title": get_task_title(task),
                        "description": get_task_description(task),
                        "deadline": task.deadline.isoformat() if task.deadline else None,
                        "comments": [
                            {"id": str(comment.id), "body": get_comment_body(comment)}
                            for comment in comments_by_task.get(task.id, [])
                        ],
                    }
                    for task in tasks
                ],
            }
            settings.export_dir.mkdir(parents=True, exist_ok=True)
            destination = (settings.export_dir / f"{export.id}.zip").resolve()
            if settings.export_dir.resolve() not in destination.parents:
                raise ValueError("Unsafe export path")
            with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("space.json", json.dumps(payload, ensure_ascii=False, indent=2))
                for page in pages:
                    archive.writestr(
                        f"pages/{_safe_export_name(get_page_title(page), str(page.id))}.md",
                        get_page_markdown(page),
                    )
                for upload in uploads:
                    source = safe_image_path(upload.filename)
                    if source.is_file():
                        archive.write(source, f"images/{upload.filename}")
            export = await db.scalar(
                select(SpaceExport).where(SpaceExport.id == export_id).with_for_update()
            )
            if export is None:
                destination.unlink(missing_ok=True)
                raise ValueError("Export was removed")
            now = datetime.now(UTC)
            export.status = "ready"
            export.file_path = str(destination)
            export.completed_at = now
            export.expires_at = now + timedelta(days=7)
            owner = await db.get(User, export.requested_by_id)
            await db.commit()
            if owner is not None:
                download_url = (
                    f"{settings.backend_url}{settings.api_v1_prefix}/exports/{export.id}/download"
                )
                enqueue_mail(
                    recipient=owner.email,
                    kind="export_ready",
                    context={
                        "name": owner.name,
                        "action_url": download_url,
                    },
                    idempotency_key=f"space-export/{export.id}",
                )
            return str(destination)
    except Exception as exc:
        async with session_factory() as db:
            export = await db.get(SpaceExport, export_id)
            if export is not None:
                export.status = "failed"
                export.error = type(exc).__name__[:500]
                await db.commit()
        raise
    finally:
        await engine.dispose()


@celery_app.task(
    name="noki.export_space",
    autoretry_for=(SQLAlchemyError, OSError),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=3,
    soft_time_limit=600,
    time_limit=660,
)
def export_space_task(export_id: str) -> dict[str, str]:
    return {"path": asyncio.run(_build_space_export(UUID(export_id)))}


async def _cleanup_upload_batch(
    db: AsyncSession,
    *,
    threshold: datetime,
) -> int:
    orphan_uploads = list(
        await db.scalars(
            select(Upload)
            .where(
                Upload.page_id.is_(None),
                Upload.created_at < threshold,
            )
            .order_by(Upload.created_at, Upload.id)
            .limit(CLEANUP_BATCH_SIZE)
            .with_for_update(skip_locked=True)
        )
    )
    if not orphan_uploads:
        return 0

    staged_deletions: list[StagedImageDeletion] = []
    try:
        for upload in orphan_uploads:
            try:
                staged = stage_image_deletion(upload.filename)
            except InvalidImageError:
                logger.warning("Skipped invalid upload filename %s", upload.filename)
                staged = None
            if staged is not None:
                staged_deletions.append(staged)
            await db.delete(upload)
        await db.commit()
    except Exception:
        await db.rollback()
        for staged in reversed(staged_deletions):
            try:
                restore_staged_image(staged)
            except OSError:
                logger.exception(
                    "Could not restore %s after cleanup rollback",
                    staged.original_path.name,
                )
        raise

    for staged in staged_deletions:
        try:
            finalize_staged_image(staged)
        except OSError:
            logger.exception(
                "Could not finalize cleanup of %s",
                staged.original_path.name,
            )
    return len(orphan_uploads)


async def _reconcile_staged_images(db: AsyncSession) -> None:
    cutoff = datetime.now(UTC).timestamp() - STAGED_RECONCILIATION_AGE.total_seconds()
    staged_deletions: list[StagedImageDeletion] = []
    for deletion in list_staged_image_deletions():
        try:
            if deletion.staged_path.stat().st_mtime < cutoff:
                staged_deletions.append(deletion)
        except FileNotFoundError:
            continue
    if not staged_deletions:
        return

    filenames = [deletion.original_path.name for deletion in staged_deletions]
    existing_filenames = set(
        await db.scalars(
            select(Upload.filename)
            .where(Upload.filename.in_(filenames))
            .order_by(Upload.filename)
            .with_for_update()
        )
    )
    for deletion in staged_deletions:
        try:
            if deletion.original_path.name in existing_filenames:
                restore_staged_image(deletion)
            else:
                finalize_staged_image(deletion)
        except OSError:
            logger.exception(
                "Could not reconcile staged image %s",
                deletion.original_path.name,
            )
    await db.commit()


async def _reconcile_untracked_images(db: AsyncSession) -> None:
    cutoff = datetime.now(UTC).timestamp() - UNTRACKED_IMAGE_GRACE_AGE.total_seconds()
    candidates = []
    for path in list_stored_image_paths():
        try:
            if path.lstat().st_mtime < cutoff:
                candidates.append(path)
        except FileNotFoundError:
            continue

    for offset in range(0, len(candidates), CLEANUP_BATCH_SIZE):
        batch = candidates[offset : offset + CLEANUP_BATCH_SIZE]
        filenames = [path.name for path in batch]
        tracked_filenames = set(
            await db.scalars(select(Upload.filename).where(Upload.filename.in_(filenames)))
        )
        for path in batch:
            if path.is_symlink():
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    logger.exception("Could not remove unsafe image symlink %s", path.name)
                continue
            if path.name in tracked_filenames:
                continue
            try:
                staged = stage_image_deletion(
                    path.name,
                    recover_existing=False,
                )
                finalize_staged_image(staged)
            except (InvalidImageError, OSError):
                logger.exception("Could not remove untracked image %s", path.name)


def _cleanup_engine_options() -> dict[str, object]:
    engine_options: dict[str, object] = {
        "poolclass": NullPool,
        "hide_parameters": True,
    }
    if settings.database_url.startswith("postgresql+asyncpg://"):
        engine_options["connect_args"] = postgres_connect_args(
            "noki-cleanup",
            lock_timeout_seconds=5,
        )
    return engine_options


async def _cleanup_orphans() -> dict[str, int]:
    engine_options = _cleanup_engine_options()
    engine = create_async_engine(settings.database_url, **engine_options)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    upload_count = 0
    session_count = 0
    advisory_lock_acquired = False

    try:
        async with engine.connect() as lock_connection:
            if engine.dialect.name == "postgresql":
                advisory_lock_acquired = bool(
                    await lock_connection.scalar(
                        text("SELECT pg_try_advisory_lock(:lock_id)"),
                        {"lock_id": CLEANUP_ADVISORY_LOCK_ID},
                    )
                )
                if not advisory_lock_acquired:
                    logger.info("Skipped cleanup because another worker holds the lock")
                    return {"uploads": 0, "sessions": 0}

            try:
                async with session_factory() as db:
                    threshold = datetime.now(UTC) - timedelta(hours=24)
                    while True:
                        cleaned = await _cleanup_upload_batch(
                            db,
                            threshold=threshold,
                        )
                        upload_count += cleaned
                        if cleaned < CLEANUP_BATCH_SIZE:
                            break

                    await _reconcile_staged_images(db)
                    await _reconcile_untracked_images(db)
                    expired_sessions = await db.execute(
                        delete(UserSession).where(UserSession.expires_at < datetime.now(UTC))
                    )
                    await db.commit()
                    session_count = int(expired_sessions.rowcount or 0)
            finally:
                if advisory_lock_acquired:
                    try:
                        await lock_connection.execute(
                            text("SELECT pg_advisory_unlock(:lock_id)"),
                            {"lock_id": CLEANUP_ADVISORY_LOCK_ID},
                        )
                    except Exception:
                        logger.exception("Could not release cleanup advisory lock")

    finally:
        await engine.dispose()

    return {"uploads": upload_count, "sessions": session_count}


@celery_app.task(
    name="noki.cleanup_orphans",
    soft_time_limit=600,
    time_limit=660,
)
def cleanup_orphans() -> dict[str, int]:
    return asyncio.run(_cleanup_orphans())


def _avatar_import_engine_options() -> dict[str, object]:
    engine_options: dict[str, object] = {
        "poolclass": NullPool,
        "hide_parameters": True,
    }
    if settings.database_url.startswith("postgresql+asyncpg://"):
        engine_options["connect_args"] = postgres_connect_args("noki-avatar-import")
    return engine_options


async def _run_google_avatar_import(
    user_id: UUID,
    picture_url: str,
    avatar_import_generation: int,
) -> AvatarImportResult:
    """Run one Celery import without sharing asyncpg state across event loops."""

    engine = create_async_engine(settings.database_url, **_avatar_import_engine_options())
    try:
        session_factory = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
        return await import_google_avatar(
            user_id,
            picture_url,
            avatar_import_generation,
            session_factory=session_factory,
        )
    finally:
        await engine.dispose()


@celery_app.task(
    bind=True,
    name="noki.import_google_avatar",
    autoretry_for=(
        AvatarSourceUnavailableError,
        MalwareScannerUnavailableError,
        AvatarStorageError,
        SQLAlchemyError,
    ),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=4,
    rate_limit="30/m",
    ignore_result=True,
    soft_time_limit=60,
    time_limit=90,
)
def import_google_avatar_task(
    self,
    user_id: str,
    picture_url: str,
    avatar_import_generation: int,
) -> dict[str, object]:
    try:
        parsed_user_id = UUID(user_id)
        if (
            isinstance(avatar_import_generation, bool)
            or not isinstance(avatar_import_generation, int)
            or avatar_import_generation <= 0
        ):
            raise InvalidAvatarError("Avatar import generation is invalid")
        validated_url = validate_google_picture_url(picture_url)
        if validated_url is None:
            raise InvalidAvatarError("Google profile picture URL is missing")
        result = asyncio.run(
            _run_google_avatar_import(
                parsed_user_id,
                validated_url,
                avatar_import_generation,
            )
        )
    except MalwareDetectedError:
        logger.warning("Rejected malware-positive Google avatar for user %s", user_id)
        return {"status": "rejected", "uploaded": False}
    except (InvalidAvatarError, ValueError):
        logger.warning("Rejected invalid Google avatar for user %s", user_id)
        return {"status": "invalid", "uploaded": False}
    logger.info(
        "Google avatar import completed for user %s: status=%s uploaded=%s",
        user_id,
        result.status,
        result.uploaded,
    )
    return {"status": result.status, "uploaded": result.uploaded}


async def _cleanup_avatar_orphans() -> int:
    if not settings.avatar_storage_enabled:
        return 0
    engine = create_async_engine(settings.database_url, **_cleanup_engine_options())
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    lock_acquired = False
    try:
        async with engine.connect() as lock_connection:
            if engine.dialect.name == "postgresql":
                lock_acquired = bool(
                    await lock_connection.scalar(
                        text("SELECT pg_try_advisory_lock(:lock_id)"),
                        {"lock_id": AVATAR_CLEANUP_ADVISORY_LOCK_ID},
                    )
                )
                if not lock_acquired:
                    return 0
            try:
                async with session_factory() as db:
                    tracked_keys = set(
                        await db.scalars(
                            select(User.avatar_object_key).where(
                                User.avatar_object_key.is_not(None)
                            )
                        )
                    )
                objects = await asyncio.to_thread(list_avatar_objects)
                cutoff = datetime.now(UTC) - AVATAR_ORPHAN_GRACE_AGE
                orphan_keys = [
                    item.key
                    for item in objects
                    if item.key not in tracked_keys and item.last_modified < cutoff
                ][:1000]
                return await asyncio.to_thread(delete_avatar_objects, orphan_keys)
            finally:
                if lock_acquired:
                    await lock_connection.execute(
                        text("SELECT pg_advisory_unlock(:lock_id)"),
                        {"lock_id": AVATAR_CLEANUP_ADVISORY_LOCK_ID},
                    )
    finally:
        await engine.dispose()


@celery_app.task(
    name="noki.cleanup_avatar_orphans",
    autoretry_for=(AvatarStorageError, SQLAlchemyError),
    retry_backoff=True,
    retry_backoff_max=900,
    retry_jitter=True,
    max_retries=3,
    soft_time_limit=300,
    time_limit=330,
)
def cleanup_avatar_orphans() -> dict[str, int]:
    return {"avatars": asyncio.run(_cleanup_avatar_orphans())}
