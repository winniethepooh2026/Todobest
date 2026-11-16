"""Resumable data backfills that are intentionally kept out of Alembic DDL."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Page, Space, SpaceMember, Task, Team, Todo, Upload, User
from app.services.content_encryption import (
    blind_title_index,
    get_page_title,
    get_task_title,
    get_todo_title,
)

TitledRecord = TypeVar("TitledRecord", Task, Page, Todo)


async def _backfill_verified_users(db: AsyncSession, *, batch_size: int) -> int:
    total = 0
    while True:
        users = list(
            await db.scalars(
                select(User)
                .where(User.email_verified_at.is_(None))
                .order_by(User.id)
                .limit(batch_size)
                .with_for_update()
            )
        )
        if not users:
            return total
        for user in users:
            user.email_verified_at = user.created_at
        await db.commit()
        total += len(users)


async def _backfill_space_owners(db: AsyncSession, *, batch_size: int) -> int:
    total = 0
    owner_member_id = (
        select(SpaceMember.user_id)
        .where(SpaceMember.space_id == Space.id, SpaceMember.role == "owner")
        .order_by(SpaceMember.created_at, SpaceMember.user_id)
        .limit(1)
        .correlate(Space)
        .scalar_subquery()
    )
    resolved_owner_id = func.coalesce(owner_member_id, Space.created_by_id)
    while True:
        rows = (
            await db.execute(
                select(Space, resolved_owner_id.label("owner_id"))
                .where(Space.owner_user_id.is_(None))
                .order_by(Space.id)
                .limit(batch_size)
                .with_for_update(of=Space)
            )
        ).all()
        if not rows:
            return total
        for space, owner_id in rows:
            space.owner_user_id = owner_id
        await db.commit()
        total += len(rows)


async def _backfill_titles(
    db: AsyncSession,
    model: type[TitledRecord],
    decrypt_title: Callable[[TitledRecord], str],
    *,
    batch_size: int,
) -> int:
    total = 0
    while True:
        records = list(
            await db.scalars(
                select(model)
                .where(model.title_blind_index.is_(None))
                .order_by(model.id)
                .limit(batch_size)
                .with_for_update()
            )
        )
        if not records:
            return total
        for record in records:
            record.title_blind_index = blind_title_index(decrypt_title(record))
        await db.commit()
        total += len(records)


async def _backfill_upload_spaces(db: AsyncSession, *, batch_size: int) -> int:
    total = 0
    while True:
        rows = (
            await db.execute(
                select(Upload, Team.space_id)
                .join(Page, Page.id == Upload.page_id)
                .join(Team, Team.id == Page.team_id)
                .where(Upload.space_id.is_(None))
                .order_by(Upload.id)
                .limit(batch_size)
                .with_for_update(of=Upload)
            )
        ).all()
        if not rows:
            return total
        for upload, space_id in rows:
            upload.space_id = space_id
        await db.commit()
        total += len(rows)


async def backfill_production_data(
    db: AsyncSession,
    *,
    batch_size: int = 250,
) -> dict[str, int]:
    if not 1 <= batch_size <= 10_000:
        raise ValueError("batch_size must be between 1 and 10000")
    return {
        "verified_users": await _backfill_verified_users(db, batch_size=batch_size),
        "space_owners": await _backfill_space_owners(db, batch_size=batch_size),
        "upload_spaces": await _backfill_upload_spaces(db, batch_size=batch_size),
        "task_titles": await _backfill_titles(db, Task, get_task_title, batch_size=batch_size),
        "page_titles": await _backfill_titles(db, Page, get_page_title, batch_size=batch_size),
        "todo_titles": await _backfill_titles(db, Todo, get_todo_title, batch_size=batch_size),
    }
