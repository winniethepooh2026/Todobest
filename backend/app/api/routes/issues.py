from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import defer, selectinload

from app.api.deps import CSRF, CurrentUser, DBSession
from app.models import (
    BoardColumn,
    Comment,
    IssueBoard,
    IssueStatus,
    Space,
    SpaceMember,
    Task,
    TaskActivity,
    TaskLabel,
    TaskRelation,
    Team,
    TeamMember,
    Upload,
)
from app.schemas import (
    BoardColumnsUpdate,
    BoardCreate,
    BoardDetail,
    BoardSummary,
    BoardUpdate,
    ColumnDefaultUpdate,
    ColumnOut,
    CommentCreate,
    CommentOut,
    CommentUpdate,
    Message,
    MyTaskPage,
    TaskActivityOut,
    TaskCard,
    TaskCardPage,
    TaskCreate,
    TaskLabelCreate,
    TaskLabelOut,
    TaskOrderRequest,
    TaskOut,
    TaskRelationCreate,
    TaskRelationOut,
    TaskStatusUpdate,
    TaskUpdate,
    UploadOut,
    UserSummary,
)
from app.services.access import (
    SPACE_WIDE_TEAM_ROLES,
    get_board_for_user,
    get_task_for_user,
    get_team_for_user,
)
from app.services.avatars import user_avatar_url
from app.services.content_encryption import (
    get_comment_body,
    get_task_description,
    get_task_title,
    set_comment_body,
    set_task_description,
    set_task_title,
)
from app.services.memberships import (
    ensure_can_change_task_status,
    ensure_can_manage_team_resources,
    get_team_actor_context,
    require_direct_team_member,
    validate_task_update_permissions,
)

router = APIRouter(tags=["Issues"])


def task_card_to_schema(task: Task, board_key: str) -> TaskCard:
    return TaskCard(
        id=task.id,
        board_id=task.board_id,
        status_id=task.status_id,
        number=task.number,
        code=f"{board_key}-{task.number}",
        title=get_task_title(task),
        assignee=(
            UserSummary(
                id=task.assignee.id,
                name=task.assignee.name,
                email=task.assignee.email,
                avatar_url=user_avatar_url(task.assignee),
            )
            if task.assignee is not None
            else None
        ),
        created_by=UserSummary(
            id=task.created_by.id,
            name=task.created_by.name,
            email=task.created_by.email,
            avatar_url=user_avatar_url(task.created_by),
        ),
        deadline=task.deadline,
        priority=task.priority,
        estimate=task.estimate,
        parent_task_id=task.parent_task_id,
        labels=[TaskLabelOut.model_validate(label) for label in task.labels],
        position=task.position,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def task_to_schema(task: Task, board_key: str) -> TaskOut:
    return TaskOut(
        **task_card_to_schema(task, board_key).model_dump(),
        description=get_task_description(task),
    )


async def load_board_detail(
    db: DBSession,
    board_id: UUID,
    user_id: UUID,
    updated_since: datetime | None = None,
) -> BoardDetail:
    accessible_board = await get_board_for_user(db, board_id, user_id)
    context = await get_team_actor_context(
        db,
        team_id=accessible_board.team_id,
        user_id=user_id,
    )
    board = await db.scalar(
        select(IssueBoard)
        .where(IssueBoard.id == board_id)
        .options(
            selectinload(IssueBoard.columns),
        )
    )
    if board is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Issue board not found")

    tasks: list[Task] = []
    has_more_by_column: dict[UUID, bool] = {}
    for column in sorted(board.columns, key=lambda item: item.position):
        task_query = (
            select(Task)
            .where(
                Task.board_id == board_id,
                Task.status_id == column.id,
                Task.deleted_at.is_(None),
            )
            .options(
                selectinload(Task.assignee),
                selectinload(Task.created_by),
                selectinload(Task.labels),
                defer(Task.description_ciphertext),
                defer(Task.description_nonce),
                defer(Task.description_tag),
            )
            .order_by(Task.position, Task.id)
            .limit(101)
        )
        if updated_since is not None:
            task_query = task_query.where(Task.updated_at > updated_since)
        column_tasks = list(await db.scalars(task_query))
        has_more_by_column[column.id] = len(column_tasks) > 100
        tasks.extend(column_tasks[:100])

    labels = list(
        await db.scalars(
            select(TaskLabel).where(TaskLabel.board_id == board_id).order_by(TaskLabel.name)
        )
    )

    return BoardDetail(
        id=board.id,
        team_id=board.team_id,
        name=board.name,
        key=board.key,
        columns=sorted(board.columns, key=lambda column: column.position),
        tasks=[task_card_to_schema(task, board.key) for task in tasks],
        labels=[TaskLabelOut.model_validate(label) for label in labels],
        has_more_by_column=has_more_by_column,
        current_user_id=user_id,
        can_create_tasks=context.can_access,
        can_manage_tasks=context.can_manage_resources,
        can_claim_tasks=context.team_membership is not None,
        created_at=board.created_at,
        updated_at=board.updated_at,
    )


async def load_task_out(db: DBSession, task_id: UUID) -> TaskOut:
    task = await db.scalar(
        select(Task)
        .where(Task.id == task_id)
        .options(
            selectinload(Task.assignee),
            selectinload(Task.created_by),
            selectinload(Task.labels),
            selectinload(Task.board),
            selectinload(Task.labels),
        )
    )
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    return task_to_schema(task, task.board.key)


def comment_to_schema(comment: Comment) -> CommentOut:
    return CommentOut(
        id=comment.id,
        task_id=comment.task_id,
        body=get_comment_body(comment),
        created_by=UserSummary(
            id=comment.created_by.id,
            name=comment.created_by.name,
            email=comment.created_by.email,
            avatar_url=user_avatar_url(comment.created_by),
        ),
        created_at=comment.created_at,
        updated_at=comment.updated_at,
    )


async def load_comment_out(db: DBSession, comment_id: UUID) -> CommentOut:
    comment = await db.scalar(
        select(Comment).where(Comment.id == comment_id).options(selectinload(Comment.created_by))
    )
    if comment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found")
    return comment_to_schema(comment)


@router.get("/teams/{team_id}/boards", response_model=list[BoardSummary])
async def list_boards(
    team_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
) -> list[IssueBoard]:
    await get_team_for_user(db, team_id, current_user.id)
    result = await db.scalars(
        select(IssueBoard)
        .where(IssueBoard.team_id == team_id, IssueBoard.deleted_at.is_(None))
        .order_by(IssueBoard.created_at)
    )
    return list(result)


@router.post(
    "/teams/{team_id}/boards",
    response_model=BoardSummary,
    status_code=status.HTTP_201_CREATED,
)
async def create_board(
    team_id: UUID,
    payload: BoardCreate,
    current_user: CurrentUser,
    db: DBSession,
    _: CSRF,
) -> IssueBoard:
    context = await get_team_actor_context(
        db,
        team_id=team_id,
        user_id=current_user.id,
        for_update=True,
    )
    ensure_can_manage_team_resources(
        context,
        detail="Only a Team owner/admin or Space owner/admin can create Issue boards",
    )
    board = IssueBoard(
        team_id=team_id,
        name=payload.name,
        key=payload.key,
        created_by_id=current_user.id,
    )
    board.columns.extend(
        [
            BoardColumn(
                name="Todo",
                position=0,
                system_status=IssueStatus.TODO,
                is_default=True,
            ),
            BoardColumn(
                name="In Progress",
                position=1,
                system_status=IssueStatus.IN_PROGRESS,
            ),
            BoardColumn(
                name="Done",
                position=2,
                system_status=IssueStatus.DONE,
            ),
        ]
    )
    db.add(board)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This board key is already used in the Team",
        ) from exc
    await db.refresh(board)
    return board


@router.get("/boards/{board_id}", response_model=BoardDetail)
async def get_board(
    board_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
    updated_since: datetime | None = None,
) -> BoardDetail:
    return await load_board_detail(db, board_id, current_user.id, updated_since)


@router.get("/boards/{board_id}/tasks", response_model=TaskCardPage)
async def list_board_task_cards(
    board_id: UUID,
    column_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
    offset: int = 0,
    limit: int = 100,
    updated_since: datetime | None = None,
) -> TaskCardPage:
    board = await get_board_for_user(db, board_id, current_user.id)
    if not 0 <= offset <= 100_000 or not 1 <= limit <= 100:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid pagination")
    column = await db.scalar(
        select(BoardColumn.id).where(
            BoardColumn.id == column_id,
            BoardColumn.board_id == board_id,
        )
    )
    if column is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Board column not found")
    filters = [
        Task.board_id == board_id,
        Task.status_id == column_id,
        Task.deleted_at.is_(None),
    ]
    if updated_since is not None:
        filters.append(Task.updated_at > updated_since)
    total = int(await db.scalar(select(func.count()).select_from(Task).where(*filters)) or 0)
    tasks = list(
        await db.scalars(
            select(Task)
            .where(*filters)
            .options(
                selectinload(Task.assignee),
                selectinload(Task.created_by),
                selectinload(Task.labels),
                defer(Task.description_ciphertext),
                defer(Task.description_nonce),
                defer(Task.description_tag),
            )
            .order_by(Task.position, Task.id)
            .offset(offset)
            .limit(limit)
        )
    )
    return TaskCardPage(
        items=[task_card_to_schema(task, board.key) for task in tasks],
        total=total,
        offset=offset,
        limit=limit,
    )


async def load_valid_labels(
    db: DBSession,
    *,
    board_id: UUID,
    label_ids: list[UUID],
) -> list[TaskLabel]:
    if len(label_ids) != len(set(label_ids)):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Duplicate label")
    if not label_ids:
        return []
    labels = list(
        await db.scalars(
            select(TaskLabel).where(
                TaskLabel.board_id == board_id,
                TaskLabel.id.in_(label_ids),
            )
        )
    )
    if len(labels) != len(label_ids):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid task label")
    return labels


async def validate_parent_task(
    db: DBSession,
    *,
    board_id: UUID,
    parent_task_id: UUID | None,
    task_id: UUID | None = None,
) -> None:
    if parent_task_id is None:
        return
    if parent_task_id == task_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Task cannot be its own parent")
    rows = await db.execute(
        select(Task.id, Task.parent_task_id).where(
            Task.board_id == board_id,
            Task.deleted_at.is_(None),
        )
    )
    parents = dict(rows.all())
    if parent_task_id not in parents:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Parent task must be on this board")
    current = parent_task_id
    visited: set[UUID] = set()
    while current is not None:
        if current == task_id or current in visited:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Task parent relationship is cyclic")
        visited.add(current)
        current = parents.get(current)


@router.get("/boards/{board_id}/labels", response_model=list[TaskLabelOut])
async def list_task_labels(
    board_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
) -> list[TaskLabel]:
    await get_board_for_user(db, board_id, current_user.id)
    return list(
        await db.scalars(
            select(TaskLabel).where(TaskLabel.board_id == board_id).order_by(TaskLabel.name)
        )
    )


@router.post(
    "/boards/{board_id}/labels",
    response_model=TaskLabelOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_task_label(
    board_id: UUID,
    payload: TaskLabelCreate,
    current_user: CurrentUser,
    db: DBSession,
    _: CSRF,
) -> TaskLabel:
    board = await get_board_for_user(db, board_id, current_user.id)
    context = await get_team_actor_context(db, team_id=board.team_id, user_id=current_user.id)
    ensure_can_manage_team_resources(context)
    label = TaskLabel(board_id=board_id, name=payload.name, color=payload.color)
    db.add(label)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Label name is already used") from exc
    await db.refresh(label)
    return label


@router.delete("/boards/{board_id}/labels/{label_id}", response_model=Message)
async def delete_task_label(
    board_id: UUID,
    label_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
    _: CSRF,
) -> Message:
    board = await get_board_for_user(db, board_id, current_user.id)
    context = await get_team_actor_context(db, team_id=board.team_id, user_id=current_user.id)
    ensure_can_manage_team_resources(context)
    label = await db.scalar(
        select(TaskLabel).where(TaskLabel.id == label_id, TaskLabel.board_id == board_id)
    )
    if label is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task label not found")
    await db.delete(label)
    await db.commit()
    return Message(message="Task label deleted")


@router.patch("/boards/{board_id}", response_model=BoardSummary)
async def update_board(
    board_id: UUID,
    payload: BoardUpdate,
    current_user: CurrentUser,
    db: DBSession,
    _: CSRF,
) -> IssueBoard:
    board = await get_board_for_user(db, board_id, current_user.id)
    context = await get_team_actor_context(
        db,
        team_id=board.team_id,
        user_id=current_user.id,
        for_update=True,
    )
    ensure_can_manage_team_resources(
        context,
        detail="Only a Team owner/admin or Space owner/admin can update Issue boards",
    )
    board = await db.scalar(
        select(IssueBoard)
        .where(IssueBoard.id == board_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if board is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Issue board not found")
    if payload.name is not None:
        board.name = payload.name
    await db.commit()
    return board


@router.delete("/boards/{board_id}", response_model=Message)
async def delete_board(
    board_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
    _: CSRF,
) -> Message:
    board = await get_board_for_user(db, board_id, current_user.id)
    context = await get_team_actor_context(
        db,
        team_id=board.team_id,
        user_id=current_user.id,
        for_update=True,
    )
    ensure_can_manage_team_resources(
        context,
        detail="Only a Team owner/admin or Space owner/admin can delete Issue boards",
    )
    board = await db.scalar(
        select(IssueBoard)
        .where(IssueBoard.id == board_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if board is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Issue board not found")
    board.deleted_at = datetime.now(UTC)
    await db.commit()
    return Message(message="Issue board deleted")


@router.patch("/boards/{board_id}/columns/default", response_model=ColumnOut)
async def set_default_column(
    board_id: UUID,
    payload: ColumnDefaultUpdate,
    current_user: CurrentUser,
    db: DBSession,
    _: CSRF,
) -> BoardColumn:
    column_id = payload.column_id
    board = await get_board_for_user(db, board_id, current_user.id)
    context = await get_team_actor_context(
        db,
        team_id=board.team_id,
        user_id=current_user.id,
        for_update=True,
    )
    ensure_can_manage_team_resources(
        context,
        detail="Only a Team owner/admin or Space owner/admin can set default Issue column",
    )
    column = await db.scalar(
        select(BoardColumn)
        .where(BoardColumn.id == column_id, BoardColumn.board_id == board_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if column is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Issue column not found")
    if not column.is_default:
        await db.execute(
            update(BoardColumn)
            .where(BoardColumn.board_id == board_id, BoardColumn.id != column_id)
            .values(is_default=False)
        )
        column.is_default = True
    await db.commit()
    await db.refresh(column)
    return column


@router.put("/boards/{board_id}/columns", response_model=BoardDetail)
async def configure_columns(
    board_id: UUID,
    payload: BoardColumnsUpdate,
    current_user: CurrentUser,
    db: DBSession,
    _: CSRF,
) -> BoardDetail:
    board = await get_board_for_user(db, board_id, current_user.id)
    context = await get_team_actor_context(
        db,
        team_id=board.team_id,
        user_id=current_user.id,
        for_update=True,
    )
    ensure_can_manage_team_resources(
        context,
        detail="Only a Team owner/admin or Space owner/admin can configure columns",
    )
    await db.execute(select(IssueBoard.id).where(IssueBoard.id == board_id).with_for_update())

    existing_columns = list(
        await db.scalars(
            select(BoardColumn)
            .where(BoardColumn.board_id == board_id)
            .order_by(BoardColumn.position)
        )
    )
    existing_by_id = {column.id: column for column in existing_columns}
    requested_ids = {item.id for item in payload.columns if item.id is not None}
    if not requested_ids.issubset(existing_by_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown board column")
    removed = [column for column in existing_columns if column.id not in requested_ids]
    if any(column.system_status is not None for column in removed):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "System status columns cannot be removed",
        )

    # Move all persisted positions out of the final range first so swaps never
    # collide with the unique (board_id, position) constraint.
    for offset, column in enumerate(existing_columns, start=1000):
        column.position = offset
    await db.flush()

    ordered_columns: list[BoardColumn] = []
    for index, item in enumerate(payload.columns):
        if item.id is None:
            column = BoardColumn(
                board_id=board_id,
                name=item.name,
                position=2000 + index,
                color=item.color,
            )
            db.add(column)
        else:
            column = existing_by_id[item.id]
            column.name = item.name
            column.color = item.color
        ordered_columns.append(column)
    await db.flush()

    if removed:
        target = ordered_columns[0]
        await db.execute(
            update(Task)
            .where(Task.status_id.in_([column.id for column in removed]))
            .values(status_id=target.id)
        )
        for column in removed:
            await db.delete(column)
        await db.flush()

        default_removed = any(column.is_default for column in removed)
        if default_removed:
            target.is_default = True

    for position, column in enumerate(ordered_columns):
        column.position = position
    await db.commit()
    return await load_board_detail(db, board_id, current_user.id)


@router.post(
    "/boards/{board_id}/tasks",
    response_model=TaskOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_task(
    board_id: UUID,
    payload: TaskCreate,
    current_user: CurrentUser,
    db: DBSession,
    _: CSRF,
) -> TaskOut:
    accessible_board = await get_board_for_user(db, board_id, current_user.id)
    await get_team_actor_context(
        db,
        team_id=accessible_board.team_id,
        user_id=current_user.id,
        for_update=True,
    )
    board = await db.scalar(
        select(IssueBoard)
        .where(IssueBoard.id == board_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if board is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Issue board not found")
    if payload.status_id is None:
        selected_column = await db.scalar(
            select(BoardColumn).where(
                BoardColumn.board_id == board_id,
                BoardColumn.is_default == True,  # noqa: E712
            )
        )
        if selected_column is None:
            selected_column = await db.scalar(
                select(BoardColumn)
                .where(BoardColumn.board_id == board_id)
                .order_by(BoardColumn.position)
                .limit(1)
            )
    else:
        selected_column = await db.scalar(
            select(BoardColumn).where(
                BoardColumn.id == payload.status_id,
                BoardColumn.board_id == board_id,
            )
        )
    if selected_column is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid task status")

    assignee_id = payload.assignee_id
    if assignee_id is not None:
        await require_direct_team_member(
            db,
            team_id=accessible_board.team_id,
            user_id=assignee_id,
            detail="Assignee must be a member of this Team",
        )
    position = await db.scalar(
        select(func.coalesce(func.max(Task.position), -1)).where(
            Task.status_id == selected_column.id
        )
    )
    await validate_parent_task(
        db,
        board_id=board_id,
        parent_task_id=payload.parent_task_id,
    )
    labels = await load_valid_labels(db, board_id=board_id, label_ids=payload.label_ids)

    task = Task(
        id=uuid4(),
        board_id=board_id,
        status_id=selected_column.id,
        assignee_id=assignee_id,
        created_by_id=current_user.id,
        number=board.next_task_number,
        deadline=payload.deadline.astimezone(UTC) if payload.deadline else None,
        priority=payload.priority,
        estimate=payload.estimate,
        parent_task_id=payload.parent_task_id,
        position=int(position or 0) + 1,
    )
    task.labels = labels
    set_task_title(task, payload.title)
    set_task_description(task, payload.description)
    board.next_task_number += 1
    db.add(task)
    await db.flush()
    db.add(
        TaskActivity(
            task_id=task.id,
            actor_id=current_user.id,
            action="created",
            summary="Задача создана",
        )
    )
    await db.commit()
    return await load_task_out(db, task.id)


@router.patch("/tasks/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: UUID,
    payload: TaskUpdate,
    current_user: CurrentUser,
    db: DBSession,
    _: CSRF,
) -> TaskOut:
    task = await get_task_for_user(db, task_id, current_user.id)
    board = await db.get(IssueBoard, task.board_id)
    if board is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Issue board not found")

    context = await get_team_actor_context(
        db,
        team_id=board.team_id,
        user_id=current_user.id,
        for_update=True,
    )
    fields = payload.model_fields_set
    validate_task_update_permissions(
        context,
        fields,
        current_user.id,
        getattr(task, "created_by_id", None),
        task.assignee_id,
    )

    task = await db.scalar(
        select(Task)
        .where(Task.id == task_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")

    if (
        "assignee_id" in fields
        and payload.assignee_id is not None
        and payload.assignee_id != task.assignee_id
    ):
        await require_direct_team_member(
            db,
            team_id=board.team_id,
            user_id=payload.assignee_id,
            detail="Assignee must be an active member of this Team and its Space",
        )

    selected_column: BoardColumn | None = None
    if "status_id" in fields:
        status_id = payload.status_id
        if status_id is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Task status cannot be null",
            )
        selected_column = await db.scalar(
            select(BoardColumn).where(
                BoardColumn.id == status_id,
                BoardColumn.board_id == task.board_id,
            )
        )
        if selected_column is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid task status")
        if not context.can_manage_resources and selected_column.system_status is None:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Members can move tasks only between system statuses",
            )

    if "title" in fields:
        title = payload.title
        if title is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Task title cannot be null",
            )
        set_task_title(task, title)
    if "description" in fields:
        set_task_description(task, payload.description or "")
    if "deadline" in fields:
        task.deadline = payload.deadline.astimezone(UTC) if payload.deadline else None
    if "assignee_id" in fields:
        task.assignee_id = payload.assignee_id
    if "priority" in fields and payload.priority is not None:
        task.priority = payload.priority
    if "estimate" in fields:
        task.estimate = payload.estimate
    if "parent_task_id" in fields:
        await validate_parent_task(
            db,
            board_id=task.board_id,
            parent_task_id=payload.parent_task_id,
            task_id=task.id,
        )
        task.parent_task_id = payload.parent_task_id
    if "label_ids" in fields:
        task.labels = await load_valid_labels(
            db,
            board_id=task.board_id,
            label_ids=payload.label_ids or [],
        )
    if selected_column is not None and task.status_id != selected_column.id:
        last_position = await db.scalar(
            select(func.coalesce(func.max(Task.position), -1)).where(
                Task.status_id == selected_column.id
            )
        )
        task.status_id = selected_column.id
        task.position = int(last_position or 0) + 1

    field_labels = {
        "title": "Название изменено",
        "description": "Описание изменено",
        "deadline": "Дедлайн изменён",
        "assignee_id": "Исполнитель изменён",
        "priority": "Приоритет изменён",
        "estimate": "Оценка изменена",
        "parent_task_id": "Родительская задача изменена",
        "label_ids": "Метки изменены",
        "status_id": "Статус изменён",
    }
    for field in fields:
        if field in field_labels:
            db.add(
                TaskActivity(
                    task_id=task.id,
                    actor_id=current_user.id,
                    action="updated",
                    field=field,
                    summary=field_labels[field],
                )
            )
    await db.commit()
    return await load_task_out(db, task.id)


@router.patch("/tasks/{task_id}/status", response_model=TaskOut)
async def update_task_status(
    task_id: UUID,
    payload: TaskStatusUpdate,
    current_user: CurrentUser,
    db: DBSession,
    _: CSRF,
) -> TaskOut:
    accessible_task = await get_task_for_user(db, task_id, current_user.id)
    board = await db.get(IssueBoard, accessible_task.board_id)
    if board is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Issue board not found")

    context = await get_team_actor_context(
        db,
        team_id=board.team_id,
        user_id=current_user.id,
        for_update=True,
    )
    task = await db.scalar(
        select(Task)
        .where(Task.id == task_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    current_column = await db.scalar(
        select(BoardColumn).where(
            BoardColumn.id == task.status_id,
            BoardColumn.board_id == task.board_id,
        )
    )
    if current_column is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid current task status")
    ensure_can_change_task_status(
        context,
        user_id=current_user.id,
        assignee_id=task.assignee_id,
    )
    if not context.can_manage_resources and current_column.system_status is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Members can move tasks only between system status columns",
        )

    column = await db.scalar(
        select(BoardColumn).where(
            BoardColumn.board_id == task.board_id,
            BoardColumn.system_status == payload.status.value,
        )
    )
    if column is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This board does not have the requested system status",
        )

    status_changed = task.status_id != column.id
    if status_changed:
        last_position = await db.scalar(
            select(func.coalesce(func.max(Task.position), -1)).where(Task.status_id == column.id)
        )
        task.status_id = column.id
        task.position = int(last_position or 0) + 1

    if status_changed:
        db.add(
            TaskActivity(
                task_id=task.id,
                actor_id=current_user.id,
                action="updated",
                field="status_id",
                summary="Статус изменён",
            )
        )

    await db.commit()
    return await load_task_out(db, task.id)


@router.post("/tasks/{task_id}/claim", response_model=TaskOut)
async def claim_task(
    task_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
    _: CSRF,
) -> TaskOut:
    task = await get_task_for_user(db, task_id, current_user.id)
    board = await db.get(IssueBoard, task.board_id)
    if board is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Issue board not found")

    await get_team_actor_context(
        db,
        team_id=board.team_id,
        user_id=current_user.id,
        for_update=True,
    )
    await require_direct_team_member(
        db,
        team_id=board.team_id,
        user_id=current_user.id,
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Only a Team member can claim this task",
    )

    claimed_id = await db.scalar(
        update(Task)
        .where(Task.id == task_id, Task.assignee_id.is_(None))
        .values(assignee_id=current_user.id)
        .returning(Task.id)
    )
    if claimed_id is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Task is already assigned",
        )

    db.add(
        TaskActivity(
            task_id=task_id,
            actor_id=current_user.id,
            action="updated",
            field="assignee_id",
            summary="Исполнитель изменён",
        )
    )
    await db.commit()
    return await load_task_out(db, task_id)


@router.delete("/tasks/{task_id}", response_model=Message)
async def delete_task(
    task_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
    _: CSRF,
) -> Message:
    task = await get_task_for_user(db, task_id, current_user.id)
    board = await db.get(IssueBoard, task.board_id)
    if board is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Issue board not found")
    context = await get_team_actor_context(
        db,
        team_id=board.team_id,
        user_id=current_user.id,
        for_update=True,
    )
    ensure_can_manage_team_resources(
        context,
        detail="Only a Team owner/admin or Space owner/admin can delete Issues",
    )
    task = await db.scalar(
        select(Task)
        .where(Task.id == task_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    task.deleted_at = datetime.now(UTC)
    await db.commit()
    return Message(message="Task deleted")


@router.get("/tasks/{task_id}/subtasks", response_model=list[TaskOut])
async def list_subtasks(
    task_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
) -> list[TaskOut]:
    parent = await get_task_for_user(db, task_id, current_user.id)
    board = await db.get(IssueBoard, parent.board_id)
    if board is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Issue board not found")
    tasks = list(
        await db.scalars(
            select(Task)
            .where(Task.parent_task_id == task_id, Task.deleted_at.is_(None))
            .options(
                selectinload(Task.assignee),
                selectinload(Task.created_by),
                selectinload(Task.labels),
            )
            .order_by(Task.position)
        )
    )
    return [task_to_schema(task, board.key) for task in tasks]


@router.get("/tasks/{task_id}/activity", response_model=list[TaskActivityOut])
async def list_task_activity(
    task_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
) -> list[TaskActivity]:
    await get_task_for_user(db, task_id, current_user.id)
    return list(
        await db.scalars(
            select(TaskActivity)
            .where(TaskActivity.task_id == task_id)
            .order_by(TaskActivity.created_at.desc())
            .limit(100)
        )
    )


@router.get("/tasks/{task_id}/attachments", response_model=list[UploadOut])
async def list_task_attachments(
    task_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
) -> list[UploadOut]:
    await get_task_for_user(db, task_id, current_user.id)
    uploads = list(
        await db.scalars(
            select(Upload).where(Upload.task_id == task_id).order_by(Upload.created_at)
        )
    )
    return [
        UploadOut(
            id=upload.id,
            url=f"/media/images/{upload.filename}",
            width=upload.width,
            height=upload.height,
            size_bytes=upload.size_bytes,
        )
        for upload in uploads
    ]


@router.get("/tasks/{task_id}/relations", response_model=list[TaskRelationOut])
async def list_task_relations(
    task_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
) -> list[TaskRelation]:
    await get_task_for_user(db, task_id, current_user.id)
    return list(
        await db.scalars(
            select(TaskRelation)
            .where(
                or_(
                    TaskRelation.source_task_id == task_id,
                    TaskRelation.target_task_id == task_id,
                )
            )
            .order_by(TaskRelation.created_at)
        )
    )


@router.post(
    "/tasks/{task_id}/relations",
    response_model=TaskRelationOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_task_relation(
    task_id: UUID,
    payload: TaskRelationCreate,
    current_user: CurrentUser,
    db: DBSession,
    _: CSRF,
) -> TaskRelation:
    task = await get_task_for_user(db, task_id, current_user.id)
    board = await db.get(IssueBoard, task.board_id)
    if board is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Issue board not found")
    context = await get_team_actor_context(db, team_id=board.team_id, user_id=current_user.id)
    ensure_can_manage_team_resources(context)
    await validate_parent_task(
        db,
        board_id=task.board_id,
        parent_task_id=payload.target_task_id,
        task_id=task.id,
    )
    relation = TaskRelation(
        source_task_id=task.id,
        target_task_id=payload.target_task_id,
        kind=payload.kind,
    )
    db.add(relation)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Task relation already exists") from exc
    await db.refresh(relation)
    return relation


@router.delete("/tasks/{task_id}/relations/{relation_id}", response_model=Message)
async def delete_task_relation(
    task_id: UUID,
    relation_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
    _: CSRF,
) -> Message:
    task = await get_task_for_user(db, task_id, current_user.id)
    board = await db.get(IssueBoard, task.board_id)
    if board is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Issue board not found")
    context = await get_team_actor_context(db, team_id=board.team_id, user_id=current_user.id)
    ensure_can_manage_team_resources(context)
    relation = await db.scalar(
        select(TaskRelation).where(
            TaskRelation.id == relation_id,
            or_(
                TaskRelation.source_task_id == task_id,
                TaskRelation.target_task_id == task_id,
            ),
        )
    )
    if relation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task relation not found")
    await db.delete(relation)
    await db.commit()
    return Message(message="Task relation deleted")


@router.get("/tasks/{task_id}/comments", response_model=list[CommentOut])
async def list_comments(
    task_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
) -> list[CommentOut]:
    await get_task_for_user(db, task_id, current_user.id)
    comments = list(
        await db.scalars(
            select(Comment)
            .where(Comment.task_id == task_id)
            .options(selectinload(Comment.created_by))
            .order_by(Comment.created_at)
        )
    )
    return [comment_to_schema(comment) for comment in comments]


@router.post(
    "/tasks/{task_id}/comments",
    response_model=CommentOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_comment(
    task_id: UUID,
    payload: CommentCreate,
    current_user: CurrentUser,
    db: DBSession,
    _: CSRF,
) -> CommentOut:
    # Posting is as open as viewing: any Team member (or Space owner/admin)
    # who can see this Task can discuss it, regardless of who can edit it.
    await get_task_for_user(db, task_id, current_user.id)

    locked_task_id = await db.scalar(select(Task.id).where(Task.id == task_id).with_for_update())
    if locked_task_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    comment = Comment(id=uuid4(), task_id=task_id, created_by_id=current_user.id)
    set_comment_body(comment, payload.body)
    db.add(comment)
    await db.commit()
    return await load_comment_out(db, comment.id)


@router.patch("/comments/{comment_id}", response_model=CommentOut)
async def update_comment(
    comment_id: UUID,
    payload: CommentUpdate,
    current_user: CurrentUser,
    db: DBSession,
    _: CSRF,
) -> CommentOut:
    comment = await db.scalar(select(Comment).where(Comment.id == comment_id).with_for_update())
    if comment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found")
    await get_task_for_user(db, comment.task_id, current_user.id)
    if comment.created_by_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the author can edit this comment")

    set_comment_body(comment, payload.body)
    await db.commit()
    return await load_comment_out(db, comment_id)


@router.delete("/comments/{comment_id}", response_model=Message)
async def delete_comment(
    comment_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
    _: CSRF,
) -> Message:
    comment = await db.scalar(select(Comment).where(Comment.id == comment_id).with_for_update())
    if comment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found")
    task = await get_task_for_user(db, comment.task_id, current_user.id)

    if comment.created_by_id != current_user.id:
        board = await db.get(IssueBoard, task.board_id)
        if board is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Issue board not found")
        context = await get_team_actor_context(
            db,
            team_id=board.team_id,
            user_id=current_user.id,
            for_update=True,
        )
        ensure_can_manage_team_resources(
            context,
            detail="Only the author, or a Team owner/admin, can delete this comment",
        )

    await db.delete(comment)
    await db.commit()
    return Message(message="Comment deleted")


@router.put("/boards/{board_id}/task-order", response_model=BoardDetail)
async def reorder_tasks(
    board_id: UUID,
    payload: TaskOrderRequest,
    current_user: CurrentUser,
    db: DBSession,
    _: CSRF,
) -> BoardDetail:
    board = await get_board_for_user(db, board_id, current_user.id)
    context = await get_team_actor_context(
        db,
        team_id=board.team_id,
        user_id=current_user.id,
        for_update=True,
    )
    ensure_can_manage_team_resources(
        context,
        detail="Only a Team owner/admin or Space owner/admin can reorder Issues",
    )
    await db.execute(select(IssueBoard.id).where(IssueBoard.id == board_id).with_for_update())
    columns = list(await db.scalars(select(BoardColumn).where(BoardColumn.board_id == board_id)))
    tasks = list(
        await db.scalars(
            select(Task)
            .where(Task.board_id == board_id, Task.deleted_at.is_(None))
            .order_by(Task.status_id, Task.position, Task.id)
        )
    )

    actual_column_ids = {column.id for column in columns}
    payload_column_ids = {column.column_id for column in payload.columns}
    if actual_column_ids != payload_column_ids:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Order payload must include every board column",
        )

    ordered_task_ids = [task_id for column in payload.columns for task_id in column.task_ids]
    if len(ordered_task_ids) != len(set(ordered_task_ids)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Task appears more than once")
    tasks_by_id = {task.id: task for task in tasks}
    if not set(ordered_task_ids) <= tasks_by_id.keys():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Order contains an unknown board task")

    # The client may have loaded only the first page of a column. Keep the
    # omitted tasks in their existing order after the visible part.
    included_ids = set(ordered_task_ids)
    for column in payload.columns:
        visible_ids = column.task_ids
        hidden_tasks = [
            task
            for task in tasks
            if task.status_id == column.column_id and task.id not in included_ids
        ]
        for position, task_id in enumerate([*visible_ids, *(task.id for task in hidden_tasks)]):
            task = tasks_by_id[task_id]
            task.status_id = column.column_id
            task.position = position

    await db.commit()
    return await load_board_detail(db, board_id, current_user.id)


def _my_tasks_query(user_id: UUID):
    return (
        select(Task)
        .join(IssueBoard, IssueBoard.id == Task.board_id)
        .join(Team, Team.id == IssueBoard.team_id)
        .join(Space, Space.id == Team.space_id)
        .join(SpaceMember, SpaceMember.space_id == Team.space_id)
        .outerjoin(
            TeamMember,
            and_(
                TeamMember.team_id == Team.id,
                TeamMember.user_id == user_id,
            ),
        )
        .where(
            Task.assignee_id == user_id,
            Task.deleted_at.is_(None),
            IssueBoard.deleted_at.is_(None),
            Team.deleted_at.is_(None),
            Space.deleted_at.is_(None),
            SpaceMember.user_id == user_id,
            or_(
                SpaceMember.role.in_(SPACE_WIDE_TEAM_ROLES),
                TeamMember.user_id == user_id,
            ),
        )
        .options(
            selectinload(Task.assignee),
            selectinload(Task.created_by),
            selectinload(Task.board),
        )
    )


@router.get("/tasks/my/page", response_model=MyTaskPage)
async def list_my_task_cards(
    current_user: CurrentUser,
    db: DBSession,
    limit: int = 50,
    cursor: str | None = None,
) -> MyTaskPage:
    if not 1 <= limit <= 100:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid page size")
    query = _my_tasks_query(current_user.id).options(
        defer(Task.description_ciphertext),
        defer(Task.description_nonce),
        defer(Task.description_tag),
    )
    if cursor is not None:
        if len(cursor) > 128:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid cursor")
        try:
            timestamp_raw, task_id_raw = cursor.rsplit("|", 1)
            timestamp = datetime.fromisoformat(timestamp_raw)
            task_id = UUID(task_id_raw)
            if timestamp.tzinfo is None:
                raise ValueError("Cursor must include timezone")
        except (ValueError, TypeError) as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid cursor") from exc
        query = query.where(
            or_(
                Task.updated_at < timestamp,
                and_(Task.updated_at == timestamp, Task.id < task_id),
            )
        )
    tasks = list(
        await db.scalars(query.order_by(Task.updated_at.desc(), Task.id.desc()).limit(limit + 1))
    )
    has_more = len(tasks) > limit
    items = tasks[:limit]
    if has_more and items:
        last_updated = items[-1].updated_at
        if last_updated.tzinfo is None:
            last_updated = last_updated.replace(tzinfo=UTC)
        next_cursor = f"{last_updated.isoformat()}|{items[-1].id}"
    else:
        next_cursor = None
    return MyTaskPage(
        items=[task_card_to_schema(task, task.board.key) for task in items],
        next_cursor=next_cursor,
    )


@router.get("/tasks/my/calendar", response_model=list[TaskCard])
async def list_my_calendar_cards(
    current_user: CurrentUser,
    db: DBSession,
    deadline_from: datetime,
    deadline_before: datetime,
) -> list[TaskCard]:
    if (
        deadline_from.tzinfo is None
        or deadline_before.tzinfo is None
        or deadline_before <= deadline_from
        or deadline_before - deadline_from > timedelta(days=31)
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid deadline range")
    tasks = list(
        await db.scalars(
            _my_tasks_query(current_user.id)
            .where(Task.deadline >= deadline_from, Task.deadline < deadline_before)
            .options(
                defer(Task.description_ciphertext),
                defer(Task.description_nonce),
                defer(Task.description_tag),
            )
            .order_by(Task.deadline, Task.id)
        )
    )
    return [task_card_to_schema(task, task.board.key) for task in tasks]


@router.get("/tasks/my", response_model=list[TaskOut])
async def list_my_tasks(
    current_user: CurrentUser,
    db: DBSession,
) -> list[TaskOut]:
    tasks = list(
        await db.scalars(
            _my_tasks_query(current_user.id).order_by(
                Task.deadline.asc().nulls_last(), Task.updated_at.desc()
            )
        )
    )
    return [task_to_schema(task, task.board.key) for task in tasks]


# Registered after /tasks/my: Starlette matches routes in registration order,
# so a {task_id} path param declared earlier would swallow the literal "my"
# segment before this router ever sees it.
@router.get("/tasks/{task_id}", response_model=TaskOut)
async def get_task(
    task_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
) -> TaskOut:
    await get_task_for_user(db, task_id, current_user.id)
    return await load_task_out(db, task_id)
