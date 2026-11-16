from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import CheckConstraint, event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

pytest.importorskip("aiosqlite")

from app.api.routes.issues import claim_task, create_task, update_task
from app.api.routes.workspaces import (
    add_team_member,
    create_team,
    remove_space_member,
    remove_team_member,
    update_team,
    update_team_member,
)
from app.core.encryption import DataCipher
from app.models import (
    BoardColumn,
    IssueBoard,
    Space,
    SpaceMember,
    Task,
    TaskActivity,
    TaskLabel,
    TaskLabelLink,
    Team,
    TeamMember,
    User,
)
from app.schemas import (
    TaskCreate,
    TaskUpdate,
    TeamCreate,
    TeamMemberCreate,
    TeamMemberUpdate,
    TeamUpdate,
)
from app.services import content_encryption
from app.services.access import get_team_for_user

TEST_KEY = base64.urlsafe_b64encode(bytes(range(32))).decode()


@pytest.fixture
async def db(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def configure_sqlite(dbapi_connection, connection_record) -> None:
        dbapi_connection.create_function("char_length", 1, len)
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    regex_constraints = [
        (table, constraint)
        for table in (IssueBoard.__table__, BoardColumn.__table__, TaskLabel.__table__)
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
                        TaskActivity.__table__,
                        TaskLabel.__table__,
                        TaskLabelLink.__table__,
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


async def seed_space(db: AsyncSession) -> tuple[User, User, User, User, Space]:
    owner = User(id=uuid4(), email="owner@example.com", name="Owner")
    admin = User(id=uuid4(), email="admin@example.com", name="Admin")
    member = User(id=uuid4(), email="member@example.com", name="Member")
    outsider = User(id=uuid4(), email="outsider@example.com", name="Outsider")
    space = Space(id=uuid4(), name="Noki", created_by_id=owner.id)
    db.add_all(
        [
            owner,
            admin,
            member,
            outsider,
            space,
            SpaceMember(space_id=space.id, user_id=owner.id, role="owner"),
            SpaceMember(space_id=space.id, user_id=admin.id, role="admin"),
            SpaceMember(space_id=space.id, user_id=member.id, role="member"),
        ]
    )
    await db.commit()
    return owner, admin, member, outsider, space


async def seed_board(
    db: AsyncSession,
    *,
    owner: User,
    member: User,
    space: Space,
) -> tuple[Team, IssueBoard, BoardColumn]:
    team = Team(
        id=uuid4(),
        space_id=space.id,
        name="Development",
        created_by_id=owner.id,
    )
    board = IssueBoard(
        id=uuid4(),
        team_id=team.id,
        name="Issues",
        key="DEV",
        created_by_id=owner.id,
    )
    column = BoardColumn(
        id=uuid4(),
        board_id=board.id,
        name="Todo",
        position=0,
    )
    db.add_all(
        [
            team,
            TeamMember(team_id=team.id, user_id=owner.id, role="owner"),
            TeamMember(team_id=team.id, user_id=member.id, role="member"),
            board,
            column,
        ]
    )
    await db.commit()
    return team, board, column


async def test_team_membership_crud_and_access_rules(db: AsyncSession) -> None:
    owner, admin, member, outsider, space = await seed_space(db)
    team = await create_team(space.id, TeamCreate(name="Backend"), owner, db, None)

    renamed = await update_team(
        team.id,
        TeamUpdate(name="Platform Engineering"),
        owner,
        db,
        None,
    )
    assert renamed.name == "Platform Engineering"

    creator_membership = await db.get(TeamMember, (team.id, owner.id))
    assert creator_membership is not None
    assert creator_membership.role == "owner"

    added = await add_team_member(
        team.id,
        TeamMemberCreate(user_id=member.id, role="member"),
        owner,
        db,
        None,
    )
    assert added.user_id == member.id

    with pytest.raises(HTTPException) as duplicate_error:
        await add_team_member(
            team.id,
            TeamMemberCreate(user_id=member.id),
            owner,
            db,
            None,
        )
    assert duplicate_error.value.status_code == 409

    with pytest.raises(HTTPException) as outsider_error:
        await add_team_member(
            team.id,
            TeamMemberCreate(user_id=outsider.id),
            owner,
            db,
            None,
        )
    assert outsider_error.value.status_code == 400

    with pytest.raises(HTTPException) as member_error:
        await add_team_member(
            team.id,
            TeamMemberCreate(user_id=admin.id),
            member,
            db,
            None,
        )
    assert member_error.value.status_code == 403

    updated = await update_team_member(
        team.id,
        member.id,
        TeamMemberUpdate(role="admin"),
        owner,
        db,
        None,
    )
    assert updated.role == "admin"

    with pytest.raises(HTTPException) as last_owner_error:
        await remove_team_member(team.id, owner.id, owner, db, None)
    assert last_owner_error.value.status_code == 409

    await remove_team_member(team.id, member.id, owner, db, None)
    with pytest.raises(HTTPException) as access_error:
        await get_team_for_user(db, team.id, member.id)
    assert access_error.value.status_code == 404

    await add_team_member(
        team.id,
        TeamMemberCreate(user_id=admin.id, role="member"),
        owner,
        db,
        None,
    )
    await remove_space_member(space.id, admin.id, owner, db, None)
    assert await db.get(TeamMember, (team.id, admin.id)) is None
    with pytest.raises(HTTPException) as removed_from_space_error:
        await get_team_for_user(db, team.id, admin.id)
    assert removed_from_space_error.value.status_code == 404


async def test_team_cannot_be_managed_from_another_space(db: AsyncSession) -> None:
    owner, _, member, _, space = await seed_space(db)
    team = await create_team(space.id, TeamCreate(name="Backend"), owner, db, None)

    other_owner = User(id=uuid4(), email="other@example.com", name="Other")
    other_space = Space(id=uuid4(), name="Other", created_by_id=other_owner.id)
    db.add_all(
        [
            other_owner,
            other_space,
            SpaceMember(space_id=other_space.id, user_id=other_owner.id, role="owner"),
        ]
    )
    await db.commit()

    with pytest.raises(HTTPException) as exc_info:
        await add_team_member(
            team.id,
            TeamMemberCreate(user_id=member.id),
            other_owner,
            db,
            None,
        )
    assert exc_info.value.status_code == 404


async def test_issue_assignee_patch_and_claim_rules(db: AsyncSession) -> None:
    owner, _, member, outsider, space = await seed_space(db)
    team, board, _ = await seed_board(db, owner=owner, member=member, space=space)

    unassigned = await create_task(
        board.id,
        TaskCreate(title="Unassigned"),
        owner,
        db,
        None,
    )
    assert unassigned.assignee is None
    assert unassigned.created_by.id == owner.id

    assigned = await create_task(
        board.id,
        TaskCreate(title="Assigned", assignee_id=member.id),
        owner,
        db,
        None,
    )
    assert assigned.assignee is not None
    assert assigned.assignee.id == member.id

    with pytest.raises(HTTPException) as invalid_assignee:
        await create_task(
            board.id,
            TaskCreate(title="Invalid", assignee_id=outsider.id),
            owner,
            db,
            None,
        )
    assert invalid_assignee.value.status_code == 400

    unchanged = await update_task(
        assigned.id,
        TaskUpdate(title="Renamed"),
        owner,
        db,
        None,
    )
    assert unchanged.assignee is not None
    assert unchanged.assignee.id == member.id

    cleared = await update_task(
        assigned.id,
        TaskUpdate(assignee_id=None),
        owner,
        db,
        None,
    )
    assert cleared.assignee is None

    claimed = await claim_task(unassigned.id, member, db, None)
    assert claimed.assignee is not None
    assert claimed.assignee.id == member.id

    second = await create_task(
        board.id,
        TaskCreate(title="Occupied", assignee_id=member.id),
        owner,
        db,
        None,
    )
    with pytest.raises(HTTPException) as claim_error:
        await claim_task(second.id, owner, db, None)
    assert claim_error.value.status_code == 409

    with pytest.raises(HTTPException) as outsider_claim:
        await claim_task(cleared.id, outsider, db, None)
    assert outsider_claim.value.status_code == 404


async def test_deleting_assignee_sets_task_to_unassigned(db: AsyncSession) -> None:
    owner, _, member, _, space = await seed_space(db)
    _, board, _ = await seed_board(db, owner=owner, member=member, space=space)
    task = await create_task(
        board.id,
        TaskCreate(title="Assigned", assignee_id=member.id),
        owner,
        db,
        None,
    )

    await db.delete(member)
    await db.commit()
    db.expire_all()

    stored = await db.scalar(select(Task).where(Task.id == task.id))
    assert stored is not None
    assert stored.assignee_id is None
