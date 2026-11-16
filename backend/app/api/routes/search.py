from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DBSession
from app.models import IssueBoard, Page, SpaceMember, Task, Team, TeamMember
from app.schemas.search import SearchResponse, SearchResult
from app.services.access import SPACE_WIDE_TEAM_ROLES
from app.services.content_encryption import (
    blind_title_index,
    get_page_title,
    get_task_title,
    normalize_search_title,
)

router = APIRouter(tags=["Search"])


@router.get("/search", response_model=SearchResponse)
async def global_search(
    current_user: CurrentUser,
    db: DBSession,
    q: str = "",
    limit: int = 30,
) -> SearchResponse:
    query = normalize_search_title(q)[:200]
    if len(query) < 2:
        return SearchResponse(items=[], query=query)
    limit = max(1, min(limit, 50))
    accessible_teams = (
        select(Team.id)
        .join(SpaceMember, SpaceMember.space_id == Team.space_id)
        .outerjoin(
            TeamMember,
            and_(TeamMember.team_id == Team.id, TeamMember.user_id == current_user.id),
        )
        .where(
            SpaceMember.user_id == current_user.id,
            Team.deleted_at.is_(None),
            or_(
                SpaceMember.role.in_(SPACE_WIDE_TEAM_ROLES),
                TeamMember.user_id == current_user.id,
            ),
        )
    )
    digest = blind_title_index(query)
    tasks = list(
        await db.scalars(
            select(Task)
            .join(IssueBoard, IssueBoard.id == Task.board_id)
            .where(
                IssueBoard.team_id.in_(accessible_teams),
                IssueBoard.deleted_at.is_(None),
                Task.deleted_at.is_(None),
                or_(Task.title_blind_index == digest, Task.title_blind_index.is_(None)),
            )
            .options(selectinload(Task.board))
            .order_by(Task.updated_at.desc())
            .limit(max(limit * 2, 100))
        )
    )
    pages = list(
        await db.scalars(
            select(Page)
            .where(
                Page.team_id.in_(accessible_teams),
                Page.deleted_at.is_(None),
                or_(Page.title_blind_index == digest, Page.title_blind_index.is_(None)),
            )
            .options(selectinload(Page.team))
            .order_by(Page.updated_at.desc())
            .limit(max(limit * 2, 100))
        )
    )

    items: list[SearchResult] = []
    indexed_legacy = False
    for task in tasks:
        title = get_task_title(task)
        normalized = normalize_search_title(title)
        if task.title_blind_index is None:
            task.title_blind_index = blind_title_index(title)
            indexed_legacy = True
        if query == normalized:
            items.append(
                SearchResult(
                    id=task.id,
                    kind="task",
                    title=title,
                    subtitle=f"{task.board.key}-{task.number} · {task.board.name}",
                    url=f"/app/tasks/{task.id}",
                    updated_at=task.updated_at,
                )
            )
    for page in pages:
        title = get_page_title(page)
        normalized = normalize_search_title(title)
        if page.title_blind_index is None:
            page.title_blind_index = blind_title_index(title)
            indexed_legacy = True
        if query == normalized:
            items.append(
                SearchResult(
                    id=page.id,
                    kind="page",
                    title=title,
                    subtitle=f"Page · {page.team.name}",
                    url=f"/app/pages/{page.id}",
                    updated_at=page.updated_at,
                )
            )
    if indexed_legacy:
        await db.commit()
    items.sort(key=lambda item: item.updated_at, reverse=True)
    return SearchResponse(items=items[:limit], query=query)
