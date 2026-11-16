from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import selectinload

from app.api.deps import DBSession
from app.api.public_deps import ReadApiPrincipal, WriteApiPrincipal
from app.api.routes.api_tokens import api_token_to_schema
from app.api.routes.issues import (
    claim_task as claim_task_internal,
)
from app.api.routes.issues import (
    comment_to_schema,
    task_to_schema,
)
from app.api.routes.issues import (
    create_comment as create_comment_internal,
)
from app.api.routes.issues import (
    create_task as create_task_internal,
)
from app.api.routes.issues import (
    get_task as get_task_internal,
)
from app.api.routes.issues import (
    list_boards as list_boards_internal,
)
from app.api.routes.issues import (
    update_task as update_task_internal,
)
from app.api.routes.issues import (
    update_task_status as update_task_status_internal,
)
from app.api.routes.workspaces import (
    list_spaces as list_spaces_internal,
)
from app.api.routes.workspaces import (
    list_team_members as list_team_members_internal,
)
from app.api.routes.workspaces import (
    list_teams as list_teams_internal,
)
from app.core.config import settings
from app.models import (
    ApiToken,
    Comment,
    IssueBoard,
    SpaceMember,
    Task,
    Team,
    TeamMember,
    Todo,
    User,
)
from app.schemas import (
    ApiTokenCreate,
    BoardSummary,
    CommentCreate,
    CommentOut,
    Message,
    SpaceOut,
    TaskCreate,
    TaskOut,
    TaskStatusUpdate,
    TaskUpdate,
    TeamMembersOut,
    TeamOut,
    TodoCreate,
    TodoOut,
    TodoUpdate,
)
from app.schemas.common import UserSummary
from app.schemas.public_api import (
    PublicApiError,
    PublicApiInfo,
    PublicApiTokenCreated,
    PublicApiTokenOut,
    PublicBoardOut,
    PublicCommentPage,
    PublicTaskCreate,
    PublicTaskPage,
    PublicUserOut,
)
from app.services.access import SPACE_WIDE_TEAM_ROLES, get_board_for_user, get_task_for_user
from app.services.api_tokens import generate_api_token, serialize_api_token_scopes
from app.services.avatars import user_avatar_url

PUBLIC_ERROR_RESPONSES = {
    status.HTTP_400_BAD_REQUEST: {"model": PublicApiError},
    status.HTTP_401_UNAUTHORIZED: {"model": PublicApiError},
    status.HTTP_403_FORBIDDEN: {"model": PublicApiError},
    status.HTTP_404_NOT_FOUND: {"model": PublicApiError},
    status.HTTP_405_METHOD_NOT_ALLOWED: {"model": PublicApiError},
    status.HTTP_408_REQUEST_TIMEOUT: {"model": PublicApiError},
    status.HTTP_409_CONFLICT: {"model": PublicApiError},
    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE: {"model": PublicApiError},
    status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": PublicApiError},
    status.HTTP_429_TOO_MANY_REQUESTS: {"model": PublicApiError},
    status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": PublicApiError},
    status.HTTP_504_GATEWAY_TIMEOUT: {"model": PublicApiError},
}

router = APIRouter(
    prefix=settings.public_api_v1_prefix,
    responses=PUBLIC_ERROR_RESPONSES,
)


def _with_task_access(query: Any, user_id: UUID) -> Any:
    return (
        query.join(IssueBoard, IssueBoard.id == Task.board_id)
        .join(Team, Team.id == IssueBoard.team_id)
        .join(
            SpaceMember,
            and_(
                SpaceMember.space_id == Team.space_id,
                SpaceMember.user_id == user_id,
            ),
        )
        .outerjoin(
            TeamMember,
            and_(
                TeamMember.team_id == Team.id,
                TeamMember.user_id == user_id,
            ),
        )
        .where(
            or_(
                SpaceMember.role.in_(SPACE_WIDE_TEAM_ROLES),
                TeamMember.user_id == user_id,
            )
        )
    )


def _apply_task_filters(
    query: Any,
    *,
    board_id: UUID | None,
    team_id: UUID | None,
    status_id: UUID | None,
    assignee_id: UUID | None,
    updated_after: AwareDatetime | None,
    updated_after_id: UUID | None,
) -> Any:
    if board_id is not None:
        query = query.where(Task.board_id == board_id)
    if team_id is not None:
        query = query.where(IssueBoard.team_id == team_id)
    if status_id is not None:
        query = query.where(Task.status_id == status_id)
    if assignee_id is not None:
        query = query.where(Task.assignee_id == assignee_id)
    if updated_after is not None:
        updated_at = updated_after.astimezone(UTC)
        if updated_after_id is None:
            query = query.where(Task.updated_at >= updated_at)
        else:
            query = query.where(
                or_(
                    Task.updated_at > updated_at,
                    and_(Task.updated_at == updated_at, Task.id > updated_after_id),
                )
            )
    return query


@router.get("", response_model=PublicApiInfo, include_in_schema=False)
async def public_api_info() -> PublicApiInfo:
    return PublicApiInfo(
        name="Noki Public API",
        version="1.0.0",
        openapi_url=f"{settings.public_api_v1_prefix}/openapi.json",
    )


@router.get(
    "/me",
    response_model=PublicUserOut,
    tags=["Account"],
    operation_id="getCurrentUser",
)
async def get_current_user(principal: ReadApiPrincipal) -> PublicUserOut:
    user = principal.user
    return PublicUserOut(
        id=user.id,
        email=user.email,
        name=user.name,
        avatar_url=user_avatar_url(user),
        timezone=user.timezone,
    )


@router.get(
    "/api-tokens",
    response_model=list[PublicApiTokenOut],
    tags=["API tokens"],
    operation_id="listApiTokens",
)
async def list_public_api_tokens(
    principal: ReadApiPrincipal,
    db: DBSession,
) -> list[PublicApiTokenOut]:
    now = datetime.now(UTC)
    tokens = list(
        await db.scalars(
            select(ApiToken)
            .where(
                ApiToken.user_id == principal.user.id,
                ApiToken.revoked_at.is_(None),
                ApiToken.expires_at > now,
                ApiToken.auth_version == principal.user.auth_version,
            )
            .order_by(ApiToken.created_at.desc(), ApiToken.id.desc())
        )
    )
    return [api_token_to_schema(token) for token in tokens]


@router.post(
    "/api-tokens",
    response_model=PublicApiTokenCreated,
    status_code=status.HTTP_201_CREATED,
    tags=["API tokens"],
    operation_id="createApiToken",
)
async def create_public_api_token(
    payload: ApiTokenCreate,
    principal: WriteApiPrincipal,
    db: DBSession,
) -> PublicApiTokenCreated:
    now = datetime.now(UTC)
    locked_user = await db.scalar(
        select(User)
        .where(User.id == principal.user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked_user is None or not locked_user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User is unavailable")

    await db.execute(
        delete(ApiToken).where(
            ApiToken.user_id == principal.user.id,
            or_(
                ApiToken.revoked_at.is_not(None),
                ApiToken.expires_at <= now,
                ApiToken.auth_version != locked_user.auth_version,
            ),
        )
    )
    raw_token, token_hash, token_prefix = generate_api_token()
    token = ApiToken(
        user_id=principal.user.id,
        name=payload.name,
        token_hash=token_hash,
        token_prefix=token_prefix,
        scopes=serialize_api_token_scopes(payload.scopes),
        auth_version=locked_user.auth_version,
        expires_at=now + timedelta(days=payload.expires_in_days),
        created_at=now,
    )
    db.add(token)
    await db.commit()
    await db.refresh(token)

    result = api_token_to_schema(token)
    return PublicApiTokenCreated(**result.model_dump(), token=raw_token)


@router.delete(
    "/api-tokens/{token_id}",
    response_model=Message,
    tags=["API tokens"],
    operation_id="revokeApiToken",
)
async def revoke_public_api_token(
    token_id: UUID,
    principal: WriteApiPrincipal,
    db: DBSession,
) -> Message:
    token = await db.scalar(
        select(ApiToken)
        .where(
            ApiToken.id == token_id,
            ApiToken.user_id == principal.user.id,
            ApiToken.revoked_at.is_(None),
        )
        .with_for_update()
    )
    if token is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "API token not found")

    await db.delete(token)
    await db.commit()
    return Message(message="API token revoked")


@router.get(
    "/spaces",
    response_model=list[SpaceOut],
    tags=["Structure"],
    operation_id="listSpaces",
)
async def list_spaces(principal: ReadApiPrincipal, db: DBSession) -> list[SpaceOut]:
    return await list_spaces_internal(principal.user, db)


@router.get(
    "/spaces/{space_id}/teams",
    response_model=list[TeamOut],
    tags=["Structure"],
    operation_id="listTeams",
)
async def list_teams(
    space_id: UUID,
    principal: ReadApiPrincipal,
    db: DBSession,
) -> list[TeamOut]:
    return await list_teams_internal(space_id, principal.user, db)


@router.get(
    "/teams/{team_id}/members",
    response_model=TeamMembersOut,
    tags=["Structure"],
    operation_id="listTeamMembers",
)
async def list_team_members(
    team_id: UUID,
    principal: ReadApiPrincipal,
    db: DBSession,
) -> TeamMembersOut:
    return await list_team_members_internal(team_id, principal.user, db)


@router.get(
    "/teams/{team_id}/boards",
    response_model=list[BoardSummary],
    tags=["Structure"],
    operation_id="listBoards",
)
async def list_boards(
    team_id: UUID,
    principal: ReadApiPrincipal,
    db: DBSession,
) -> list[BoardSummary]:
    return await list_boards_internal(team_id, principal.user, db)


@router.get(
    "/boards/{board_id}",
    response_model=PublicBoardOut,
    tags=["Structure"],
    operation_id="getBoard",
)
async def get_board(
    board_id: UUID,
    principal: ReadApiPrincipal,
    db: DBSession,
) -> PublicBoardOut:
    await get_board_for_user(db, board_id, principal.user.id)
    board = await db.scalar(
        select(IssueBoard)
        .where(IssueBoard.id == board_id)
        .options(selectinload(IssueBoard.columns))
    )
    if board is None:
        # Access was checked above. This branch covers a concurrent delete.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Issue board not found")
    return PublicBoardOut(
        id=board.id,
        team_id=board.team_id,
        name=board.name,
        key=board.key,
        columns=sorted(board.columns, key=lambda column: column.position),
        created_at=board.created_at,
        updated_at=board.updated_at,
    )


@router.get(
    "/tasks",
    response_model=PublicTaskPage,
    tags=["Tasks"],
    operation_id="listTasks",
)
async def list_tasks(
    principal: ReadApiPrincipal,
    db: DBSession,
    board_id: UUID | None = None,
    team_id: UUID | None = None,
    status_id: UUID | None = None,
    assignee_id: UUID | None = None,
    updated_after: AwareDatetime | None = None,
    updated_after_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> PublicTaskPage:
    if updated_after_id is not None and updated_after is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "updated_after_id requires updated_after",
        )
    filters = {
        "board_id": board_id,
        "team_id": team_id,
        "status_id": status_id,
        "assignee_id": assignee_id,
        "updated_after": updated_after,
        "updated_after_id": updated_after_id,
    }
    count_query = _apply_task_filters(
        _with_task_access(select(func.count(Task.id)), principal.user.id),
        **filters,
    )
    total = int(await db.scalar(count_query) or 0)

    task_query = _apply_task_filters(
        _with_task_access(select(Task), principal.user.id),
        **filters,
    )
    tasks = list(
        await db.scalars(
            task_query.options(
                selectinload(Task.assignee),
                selectinload(Task.created_by),
                selectinload(Task.board),
            )
            .order_by(Task.updated_at.asc(), Task.id.asc())
            .offset(offset)
            .limit(limit)
        )
    )
    return PublicTaskPage(
        items=[task_to_schema(task, task.board.key) for task in tasks],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/tasks",
    response_model=TaskOut,
    status_code=status.HTTP_201_CREATED,
    tags=["Tasks"],
    operation_id="createTask",
)
async def create_task(
    payload: PublicTaskCreate,
    principal: WriteApiPrincipal,
    db: DBSession,
) -> TaskOut:
    task_payload = TaskCreate(**payload.model_dump(exclude={"board_id"}))
    return await create_task_internal(payload.board_id, task_payload, principal.user, db, None)


@router.get(
    "/tasks/{task_id}",
    response_model=TaskOut,
    tags=["Tasks"],
    operation_id="getTask",
)
async def get_task(
    task_id: UUID,
    principal: ReadApiPrincipal,
    db: DBSession,
) -> TaskOut:
    return await get_task_internal(task_id, principal.user, db)


@router.patch(
    "/tasks/{task_id}",
    response_model=TaskOut,
    tags=["Tasks"],
    operation_id="updateTask",
)
async def update_task(
    task_id: UUID,
    payload: TaskUpdate,
    principal: WriteApiPrincipal,
    db: DBSession,
) -> TaskOut:
    return await update_task_internal(task_id, payload, principal.user, db, None)


@router.patch(
    "/tasks/{task_id}/status",
    response_model=TaskOut,
    tags=["Tasks"],
    operation_id="updateTaskStatus",
)
async def update_task_status(
    task_id: UUID,
    payload: TaskStatusUpdate,
    principal: WriteApiPrincipal,
    db: DBSession,
) -> TaskOut:
    return await update_task_status_internal(task_id, payload, principal.user, db, None)


@router.post(
    "/tasks/{task_id}/claim",
    response_model=TaskOut,
    tags=["Tasks"],
    operation_id="claimTask",
)
async def claim_task(
    task_id: UUID,
    principal: WriteApiPrincipal,
    db: DBSession,
) -> TaskOut:
    return await claim_task_internal(task_id, principal.user, db, None)


@router.get(
    "/tasks/{task_id}/comments",
    response_model=PublicCommentPage,
    tags=["Comments"],
    operation_id="listTaskComments",
)
async def list_task_comments(
    task_id: UUID,
    principal: ReadApiPrincipal,
    db: DBSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> PublicCommentPage:
    await get_task_for_user(db, task_id, principal.user.id)
    total = int(
        await db.scalar(select(func.count(Comment.id)).where(Comment.task_id == task_id)) or 0
    )
    comments = list(
        await db.scalars(
            select(Comment)
            .where(Comment.task_id == task_id)
            .options(selectinload(Comment.created_by))
            .order_by(Comment.created_at.asc(), Comment.id.asc())
            .offset(offset)
            .limit(limit)
        )
    )
    return PublicCommentPage(
        items=[comment_to_schema(comment) for comment in comments],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/tasks/{task_id}/comments",
    response_model=CommentOut,
    status_code=status.HTTP_201_CREATED,
    tags=["Comments"],
    operation_id="createTaskComment",
)
async def create_task_comment(
    task_id: UUID,
    payload: CommentCreate,
    principal: WriteApiPrincipal,
    db: DBSession,
) -> CommentOut:
    return await create_comment_internal(task_id, payload, principal.user, db, None)


def _todo_to_schema(todo: Todo) -> TodoOut:
    from app.services.content_encryption import get_todo_description, get_todo_title

    return TodoOut(
        id=todo.id,
        title=get_todo_title(todo),
        description=get_todo_description(todo),
        deadline=todo.deadline,
        status=todo.status,
        position=todo.position,
        completed_by=(
            UserSummary(
                id=todo.completed_by.id,
                name=todo.completed_by.name,
                email=todo.completed_by.email,
                avatar_url=user_avatar_url(todo.completed_by),
            )
            if todo.completed_by is not None
            else None
        ),
        created_at=todo.created_at,
        updated_at=todo.updated_at,
    )


@router.get(
    "/todos",
    response_model=list[TodoOut],
    tags=["Todos"],
    operation_id="listTodos",
)
async def list_todos(
    principal: ReadApiPrincipal,
    db: DBSession,
) -> list[TodoOut]:
    todos = list(
        await db.scalars(
            select(Todo)
            .where(Todo.user_id == principal.user.id)
            .options(selectinload(Todo.completed_by))
            .order_by(Todo.deadline.asc().nulls_last(), Todo.position, Todo.created_at)
        )
    )
    return [_todo_to_schema(todo) for todo in todos]


@router.get(
    "/todos/{todo_id}",
    response_model=TodoOut,
    tags=["Todos"],
    operation_id="getTodo",
)
async def get_todo(
    todo_id: UUID,
    principal: ReadApiPrincipal,
    db: DBSession,
) -> TodoOut:
    todo = await db.scalar(
        select(Todo)
        .where(Todo.id == todo_id, Todo.user_id == principal.user.id)
        .options(selectinload(Todo.completed_by))
    )
    if todo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Todo not found")
    return _todo_to_schema(todo)


@router.post(
    "/todos",
    response_model=TodoOut,
    status_code=status.HTTP_201_CREATED,
    tags=["Todos"],
    operation_id="createTodo",
)
async def create_todo(
    payload: TodoCreate,
    principal: WriteApiPrincipal,
    db: DBSession,
) -> TodoOut:
    from app.services.content_encryption import set_todo_description, set_todo_title

    todo = Todo(
        id=uuid4(),
        user_id=principal.user.id,
        status=payload.status.value,
        position=payload.position,
        deadline=payload.deadline.astimezone(UTC) if payload.deadline else None,
    )
    set_todo_title(todo, payload.title)
    set_todo_description(todo, payload.description or "")
    db.add(todo)
    await db.commit()
    await db.refresh(todo)
    return _todo_to_schema(todo)


@router.patch(
    "/todos/{todo_id}",
    response_model=TodoOut,
    tags=["Todos"],
    operation_id="updateTodo",
)
async def update_todo(
    todo_id: UUID,
    payload: TodoUpdate,
    principal: WriteApiPrincipal,
    db: DBSession,
) -> TodoOut:
    from app.services.content_encryption import set_todo_description, set_todo_title

    todo = await db.scalar(
        select(Todo).where(Todo.id == todo_id, Todo.user_id == principal.user.id).with_for_update()
    )
    if todo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Todo not found")

    fields = payload.model_fields_set

    if "title" in fields:
        if payload.title is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Todo title cannot be null",
            )
        set_todo_title(todo, payload.title)

    if "description" in fields:
        set_todo_description(todo, payload.description or "")

    if "deadline" in fields:
        todo.deadline = payload.deadline.astimezone(UTC) if payload.deadline else None

    if "status" in fields:
        if payload.status is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Todo status cannot be null",
            )
        todo.status = payload.status.value
        if payload.status.value == "done":
            todo.completed_by_id = principal.user.id
        else:
            todo.completed_by_id = None

    if "position" in fields:
        if payload.position is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Todo position cannot be null",
            )
        todo.position = payload.position

    await db.commit()
    await db.refresh(todo)
    return _todo_to_schema(todo)


@router.delete(
    "/todos/{todo_id}",
    response_model=Message,
    tags=["Todos"],
    operation_id="deleteTodo",
)
async def delete_todo(
    todo_id: UUID,
    principal: WriteApiPrincipal,
    db: DBSession,
) -> Message:
    todo = await db.scalar(
        select(Todo).where(Todo.id == todo_id, Todo.user_id == principal.user.id)
    )
    if todo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Todo not found")
    await db.delete(todo)
    await db.commit()
    return Message(message="Todo deleted")


@lru_cache(maxsize=1)
def public_openapi_schema() -> dict[str, Any]:
    return get_openapi(
        title="Noki Public API",
        version="1.0.0",
        description="Stable REST API for Noki integrations.",
        routes=router.routes,
    )


@router.get("/openapi.json", include_in_schema=False)
async def public_openapi() -> JSONResponse:
    return JSONResponse(public_openapi_schema())
