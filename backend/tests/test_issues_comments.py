from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import CheckConstraint, event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.routes.issues import (
    create_comment,
    delete_comment,
    list_comments,
    update_comment,
)
from app.core.encryption import DataCipher
from app.models import (
    BoardColumn,
    Comment,
    IssueBoard,
    IssueStatus,
    Space,
    SpaceMember,
    Task,
    Team,
    TeamMember,
    Upload,
    User,
)
from app.schemas import CommentCreate, CommentUpdate
from app.services import content_encryption

pytest.importorskip("aiosqlite")

TEST_KEY = base64.urlsafe_b64encode(bytes(range(32))).decode()


@dataclass(slots=True)
class CommentScenario:
    space_owner: User
    member: User
    other_member: User
    outsider: User
    task: Task


@pytest.fixture
async def db(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def configure_sqlite(dbapi_connection, connection_record) -> None:
        dbapi_connection.create_function("char_length", 1, len)
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    regex_constraints = [
        (table, constraint)
        for table in (IssueBoard.__table__, BoardColumn.__table__)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint) and " ~ " in str(constraint.sqltext)
    ]
    for table, constraint in regex_constraints:
        table.constraints.remove(constraint)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda sync_connection: User.metadata.create_all(
                    sync_connection,
                    tables=[
                        User.__table__,
                        Space.__table__,
                        SpaceMember.__table__,
                        Team.__table__,
                        TeamMember.__table__,
                        IssueBoard.__table__,
                        BoardColumn.__table__,
                        Task.__table__,
                        Upload.__table__,
                        Comment.__table__,
                    ],
                )
            )
    finally:
        for table, constraint in regex_constraints:
            table.constraints.add(constraint)

    monkeypatch.setattr(
        content_encryption,
        "get_data_cipher",
        lambda: DataCipher(TEST_KEY),
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def scenario(db: AsyncSession) -> CommentScenario:
    space_owner = User(id=uuid4(), email="space-owner@example.com", name="Space Owner")
    member = User(id=uuid4(), email="member@example.com", name="Member")
    other_member = User(id=uuid4(), email="other-member@example.com", name="Other Member")
    outsider = User(id=uuid4(), email="outsider@example.com", name="Outsider")

    space = Space(id=uuid4(), name="Noki", created_by_id=space_owner.id)
    team = Team(id=uuid4(), space_id=space.id, name="Development", created_by_id=space_owner.id)
    board = IssueBoard(
        id=uuid4(),
        team_id=team.id,
        name="Issues",
        key="DEV",
        created_by_id=space_owner.id,
        next_task_number=2,
    )
    todo_column = BoardColumn(
        id=uuid4(),
        board_id=board.id,
        name="Todo",
        position=0,
        system_status=IssueStatus.TODO,
    )
    task = Task(
        id=uuid4(),
        board_id=board.id,
        status_id=todo_column.id,
        created_by_id=space_owner.id,
        number=1,
        position=0,
    )
    content_encryption.set_task_title(task, "Ship comments")
    content_encryption.set_task_description(task, "")

    db.add_all(
        [
            space_owner,
            member,
            other_member,
            outsider,
            space,
            SpaceMember(space_id=space.id, user_id=space_owner.id, role="owner"),
            SpaceMember(space_id=space.id, user_id=member.id, role="member"),
            SpaceMember(space_id=space.id, user_id=other_member.id, role="member"),
            team,
            TeamMember(team_id=team.id, user_id=member.id, role="member"),
            TeamMember(team_id=team.id, user_id=other_member.id, role="member"),
            board,
            todo_column,
            task,
        ]
    )
    await db.commit()
    return CommentScenario(
        space_owner=space_owner,
        member=member,
        other_member=other_member,
        outsider=outsider,
        task=task,
    )


@pytest.mark.asyncio
async def test_member_can_post_and_list_comment(
    db: AsyncSession, scenario: CommentScenario
) -> None:
    created = await create_comment(
        scenario.task.id,
        CommentCreate(body="Первый комментарий"),
        scenario.member,
        db,
        None,
    )
    assert created.body == "Первый комментарий"
    assert created.created_by.id == scenario.member.id

    comments = await list_comments(scenario.task.id, scenario.other_member, db)
    assert [comment.body for comment in comments] == ["Первый комментарий"]


@pytest.mark.asyncio
async def test_outsider_cannot_view_or_post(db: AsyncSession, scenario: CommentScenario) -> None:
    with pytest.raises(HTTPException) as exc:
        await list_comments(scenario.task.id, scenario.outsider, db)
    assert exc.value.status_code == 404

    with pytest.raises(HTTPException) as exc:
        await create_comment(
            scenario.task.id,
            CommentCreate(body="Не должно пройти"),
            scenario.outsider,
            db,
            None,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_only_author_can_edit_comment(db: AsyncSession, scenario: CommentScenario) -> None:
    created = await create_comment(
        scenario.task.id, CommentCreate(body="Исходный текст"), scenario.member, db, None
    )

    updated = await update_comment(
        created.id, CommentUpdate(body="Исправленный текст"), scenario.member, db, None
    )
    assert updated.body == "Исправленный текст"

    with pytest.raises(HTTPException) as exc:
        await update_comment(
            created.id, CommentUpdate(body="Чужая правка"), scenario.other_member, db, None
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_author_or_admin_can_delete_comment(
    db: AsyncSession, scenario: CommentScenario
) -> None:
    author_comment = await create_comment(
        scenario.task.id, CommentCreate(body="От автора"), scenario.member, db, None
    )
    admin_target = await create_comment(
        scenario.task.id, CommentCreate(body="Удалит owner"), scenario.member, db, None
    )

    with pytest.raises(HTTPException) as exc:
        await delete_comment(admin_target.id, scenario.other_member, db, None)
    assert exc.value.status_code == 403

    await delete_comment(author_comment.id, scenario.member, db, None)
    await delete_comment(admin_target.id, scenario.space_owner, db, None)

    remaining = await list_comments(scenario.task.id, scenario.member, db)
    assert remaining == []


@pytest.mark.asyncio
async def test_deleting_task_cascades_to_comments(
    db: AsyncSession, scenario: CommentScenario
) -> None:
    await create_comment(
        scenario.task.id, CommentCreate(body="Будет удалён"), scenario.member, db, None
    )

    task = await db.get(Task, scenario.task.id)
    assert task is not None
    await db.delete(task)
    await db.commit()

    remaining = (await db.scalars(select(Comment).where(Comment.task_id == scenario.task.id))).all()
    assert list(remaining) == []
