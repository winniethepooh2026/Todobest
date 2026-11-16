from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import IssueBoard, Page, Space, SpaceMember, Task, Team, TeamMember

SPACE_WIDE_TEAM_ROLES = ("owner", "admin")


def _team_access_condition(user_id: UUID):
    return and_(
        Space.deleted_at.is_(None),
        Team.deleted_at.is_(None),
        SpaceMember.user_id == user_id,
        or_(
            SpaceMember.role.in_(SPACE_WIDE_TEAM_ROLES),
            TeamMember.user_id == user_id,
        ),
    )


def _join_team_access(query, user_id: UUID):
    return (
        query.join(
            Space,
            Space.id == Team.space_id,
        )
        .join(
            SpaceMember,
            SpaceMember.space_id == Team.space_id,
        )
        .outerjoin(
            TeamMember,
            and_(
                TeamMember.team_id == Team.id,
                TeamMember.user_id == user_id,
            ),
        )
    )


async def get_space_for_user(
    db: AsyncSession,
    space_id: UUID,
    user_id: UUID,
) -> Space:
    space = await db.scalar(
        select(Space)
        .join(SpaceMember, SpaceMember.space_id == Space.id)
        .where(Space.id == space_id, Space.deleted_at.is_(None), SpaceMember.user_id == user_id)
    )
    if space is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Space not found")
    return space


async def get_team_for_user(
    db: AsyncSession,
    team_id: UUID,
    user_id: UUID,
) -> Team:
    team = await db.scalar(
        _join_team_access(select(Team), user_id).where(
            Team.id == team_id,
            _team_access_condition(user_id),
        )
    )
    if team is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Team not found")
    return team


async def get_board_for_user(
    db: AsyncSession,
    board_id: UUID,
    user_id: UUID,
) -> IssueBoard:
    board = await db.scalar(
        _join_team_access(
            select(IssueBoard).join(Team, Team.id == IssueBoard.team_id),
            user_id,
        ).where(
            IssueBoard.id == board_id,
            IssueBoard.deleted_at.is_(None),
            _team_access_condition(user_id),
        )
    )
    if board is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Issue board not found")
    return board


async def get_page_for_user(
    db: AsyncSession,
    page_id: UUID,
    user_id: UUID,
) -> Page:
    page = await db.scalar(
        _join_team_access(
            select(Page).join(Team, Team.id == Page.team_id),
            user_id,
        )
        .where(
            Page.id == page_id,
            Page.deleted_at.is_(None),
            _team_access_condition(user_id),
        )
        .options(selectinload(Page.created_by))
    )
    if page is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Page not found")
    return page


async def get_task_for_user(
    db: AsyncSession,
    task_id: UUID,
    user_id: UUID,
) -> Task:
    task = await db.scalar(
        _join_team_access(
            select(Task)
            .join(IssueBoard, IssueBoard.id == Task.board_id)
            .join(Team, Team.id == IssueBoard.team_id),
            user_id,
        ).where(
            Task.id == task_id,
            Task.deleted_at.is_(None),
            IssueBoard.deleted_at.is_(None),
            _team_access_condition(user_id),
        )
    )
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    return task
