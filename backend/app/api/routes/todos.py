from __future__ import annotations

from datetime import UTC
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CSRF, CurrentUser, DBSession
from app.models import Todo
from app.schemas import Message, TodoCreate, TodoOut, TodoUpdate
from app.schemas.common import UserSummary
from app.services.content_encryption import (
    get_todo_description,
    get_todo_title,
    set_todo_description,
    set_todo_title,
)

router = APIRouter(tags=["Todos"])


def todo_to_schema(todo: Todo) -> TodoOut:
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
                avatar_url=None,
            )
            if todo.completed_by is not None
            else None
        ),
        created_at=todo.created_at,
        updated_at=todo.updated_at,
    )


@router.get("/todos", response_model=list[TodoOut])
async def list_todos(
    current_user: CurrentUser,
    db: DBSession,
) -> list[TodoOut]:
    todos = list(
        await db.scalars(
            select(Todo)
            .where(Todo.user_id == current_user.id)
            .options(selectinload(Todo.completed_by))
            .order_by(Todo.deadline.asc().nulls_last(), Todo.position, Todo.created_at)
        )
    )
    return [todo_to_schema(todo) for todo in todos]


@router.post("/todos", response_model=TodoOut, status_code=status.HTTP_201_CREATED)
async def create_todo(
    payload: TodoCreate,
    current_user: CurrentUser,
    db: DBSession,
    _: CSRF,
) -> TodoOut:
    todo = Todo(
        id=uuid4(),
        user_id=current_user.id,
        status=payload.status.value,
        position=payload.position,
        deadline=payload.deadline.astimezone(UTC) if payload.deadline else None,
    )
    set_todo_title(todo, payload.title)
    set_todo_description(todo, payload.description or "")
    db.add(todo)
    await db.commit()
    return todo_to_schema(todo)


@router.get("/todos/{todo_id}", response_model=TodoOut)
async def get_todo(
    todo_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
) -> TodoOut:
    todo = await db.scalar(
        select(Todo)
        .where(Todo.id == todo_id, Todo.user_id == current_user.id)
        .options(selectinload(Todo.completed_by))
    )
    if todo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Todo not found")
    return todo_to_schema(todo)


@router.patch("/todos/{todo_id}", response_model=TodoOut)
async def update_todo(
    todo_id: UUID,
    payload: TodoUpdate,
    current_user: CurrentUser,
    db: DBSession,
    _: CSRF,
) -> TodoOut:
    todo = await db.scalar(
        select(Todo).where(Todo.id == todo_id, Todo.user_id == current_user.id).with_for_update()
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
        if payload.description is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Todo description cannot be null",
            )
        set_todo_description(todo, payload.description)

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
            todo.completed_by_id = current_user.id
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
    return todo_to_schema(todo)


@router.delete("/todos/{todo_id}", response_model=Message)
async def delete_todo(
    todo_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
    _: CSRF,
) -> Message:
    todo = await db.scalar(select(Todo).where(Todo.id == todo_id, Todo.user_id == current_user.id))
    if todo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Todo not found")
    await db.delete(todo)
    await db.commit()
    return Message(message="Todo deleted")
