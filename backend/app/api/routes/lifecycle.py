from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import CSRF, CurrentUser, DBSession
from app.models import IssueBoard, Page, Space, SpaceMember, Task, Team
from app.schemas import Message
from app.schemas.lifecycle import NamedDeleteRequest, TrashItem
from app.services.content_encryption import get_page_title, get_task_title
from app.services.memberships import (
    SPACE_MANAGER_ROLES,
    ensure_can_manage_team_resources,
    get_team_actor_context,
    require_space_role,
)

router = APIRouter(tags=["Trash"])


@router.delete("/spaces/{space_id}", response_model=Message)
async def delete_space(
    space_id: UUID,
    payload: NamedDeleteRequest,
    current_user: CurrentUser,
    db: DBSession,
    _: CSRF,
) -> Message:
    space = await db.scalar(select(Space).where(Space.id == space_id).with_for_update())
    if space is None or space.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Space not found")
    await require_space_role(db, space_id=space_id, user_id=current_user.id, roles={"owner"})
    if payload.name != space.name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Space name does not match")
    space.deleted_at = datetime.now(UTC)
    await db.commit()
    return Message(message="Space moved to trash")


@router.delete("/teams/{team_id}", response_model=Message)
async def delete_team(
    team_id: UUID,
    payload: NamedDeleteRequest,
    current_user: CurrentUser,
    db: DBSession,
    _: CSRF,
) -> Message:
    context = await get_team_actor_context(
        db, team_id=team_id, user_id=current_user.id, for_update=True
    )
    ensure_can_manage_team_resources(context)
    if payload.name != context.team.name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Team name does not match")
    context.team.deleted_at = datetime.now(UTC)
    await db.commit()
    return Message(message="Team moved to trash")


@router.get("/trash", response_model=list[TrashItem])
async def list_trash(current_user: CurrentUser, db: DBSession) -> list[TrashItem]:
    managed_space_ids = select(SpaceMember.space_id).where(
        SpaceMember.user_id == current_user.id, SpaceMember.role.in_(SPACE_MANAGER_ROLES)
    )
    spaces = list(
        await db.scalars(
            select(Space).where(Space.id.in_(managed_space_ids), Space.deleted_at.is_not(None))
        )
    )
    teams = list(
        await db.scalars(
            select(Team).where(Team.space_id.in_(managed_space_ids), Team.deleted_at.is_not(None))
        )
    )
    active_team_ids = select(Team.id).where(Team.space_id.in_(managed_space_ids))
    boards = list(
        await db.scalars(
            select(IssueBoard).where(
                IssueBoard.team_id.in_(active_team_ids), IssueBoard.deleted_at.is_not(None)
            )
        )
    )
    pages = list(
        await db.scalars(
            select(Page).where(Page.team_id.in_(active_team_ids), Page.deleted_at.is_not(None))
        )
    )
    board_ids = select(IssueBoard.id).where(IssueBoard.team_id.in_(active_team_ids))
    tasks = list(
        await db.scalars(
            select(Task).where(Task.board_id.in_(board_ids), Task.deleted_at.is_not(None))
        )
    )
    return [
        *[TrashItem(kind="space", id=x.id, name=x.name, deleted_at=x.deleted_at) for x in spaces],
        *[TrashItem(kind="team", id=x.id, name=x.name, deleted_at=x.deleted_at) for x in teams],
        *[TrashItem(kind="board", id=x.id, name=x.name, deleted_at=x.deleted_at) for x in boards],
        *[
            TrashItem(kind="page", id=x.id, name=get_page_title(x), deleted_at=x.deleted_at)
            for x in pages
        ],
        *[
            TrashItem(kind="task", id=x.id, name=get_task_title(x), deleted_at=x.deleted_at)
            for x in tasks
        ],
    ]


@router.post("/trash/{kind}/{resource_id}/restore", response_model=Message)
async def restore_from_trash(
    kind: Literal["space", "team", "board", "page", "task"],
    resource_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
    _: CSRF,
) -> Message:
    model = {"space": Space, "team": Team, "board": IssueBoard, "page": Page, "task": Task}[kind]
    resource = await db.scalar(select(model).where(model.id == resource_id).with_for_update())
    if resource is None or resource.deleted_at is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trash item not found")
    if kind == "space":
        membership = await db.get(SpaceMember, (resource.id, current_user.id))
        if membership is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Trash item not found")
        if membership.role != "owner":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient Space permissions")
    else:
        if kind == "team":
            parent = await db.scalar(
                select(Space).where(
                    Space.id == resource.space_id,
                    Space.deleted_at.is_(None),
                )
            )
            if parent is None:
                raise HTTPException(status.HTTP_409_CONFLICT, "Restore the parent Space first")
            await require_space_role(
                db,
                space_id=resource.space_id,
                user_id=current_user.id,
                roles=SPACE_MANAGER_ROLES,
            )
            resource.deleted_at = None
            await db.commit()
            return Message(message="Item restored")
        team_id = None
        if kind in {"board", "page"}:
            team_id = resource.team_id
        elif kind == "task":
            board = await db.get(IssueBoard, resource.board_id)
            team_id = board.team_id if board else None
        if team_id is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "Parent resource is unavailable")
        context = await get_team_actor_context(db, team_id=team_id, user_id=current_user.id)
        ensure_can_manage_team_resources(context)
    resource.deleted_at = None
    await db.commit()
    return Message(message="Item restored")
