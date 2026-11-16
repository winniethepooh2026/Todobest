from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.routes.todos import (
    create_todo,
    delete_todo,
    get_todo,
    list_todos,
    update_todo,
)
from app.core.encryption import DataCipher
from app.models import Todo, User
from app.schemas import TodoCreate, TodoUpdate
from app.services import content_encryption

pytest.importorskip("aiosqlite")

TEST_KEY = base64.urlsafe_b64encode(bytes(range(32))).decode()


@pytest.fixture
async def db(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: User.metadata.create_all(
                sync_connection,
                tables=[User.__table__, Todo.__table__],
            )
        )
    monkeypatch.setattr(
        content_encryption,
        "get_data_cipher",
        lambda: DataCipher(TEST_KEY),
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_todos_are_private_and_support_full_crud(db: AsyncSession) -> None:
    owner = User(id=uuid4(), email="owner@example.com", name="Owner")
    outsider = User(id=uuid4(), email="outsider@example.com", name="Outsider")
    db.add_all([owner, outsider])
    await db.commit()

    created = await create_todo(
        TodoCreate(
            title="  Личная   задача  ",
            description="Только для владельца",
            deadline=datetime(2026, 8, 5, 13, 30, tzinfo=UTC),
        ),
        owner,
        db,
        None,
    )

    assert created.title == "Личная задача"
    assert created.description == "Только для владельца"
    assert created.deadline == datetime(2026, 8, 5, 13, 30, tzinfo=UTC)
    assert created.status.value == "todo"

    owner_todos = await list_todos(owner, db)
    outsider_todos = await list_todos(outsider, db)
    assert [todo.id for todo in owner_todos] == [created.id]
    assert outsider_todos == []

    with pytest.raises(HTTPException) as inaccessible:
        await get_todo(created.id, outsider, db)
    assert inaccessible.value.status_code == 404

    updated = await update_todo(
        created.id,
        TodoUpdate.model_validate(
            {
                "title": "Готовая задача",
                "description": "Обновлённое описание",
                "deadline": None,
                "status": "done",
            }
        ),
        owner,
        db,
        None,
    )
    assert updated.title == "Готовая задача"
    assert updated.description == "Обновлённое описание"
    assert updated.deadline is None
    assert updated.status.value == "done"

    with pytest.raises(HTTPException) as forbidden_delete:
        await delete_todo(created.id, outsider, db, None)
    assert forbidden_delete.value.status_code == 404

    deleted = await delete_todo(created.id, owner, db, None)
    assert deleted.message == "Todo deleted"
    assert await list_todos(owner, db) == []
