from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import CheckConstraint, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import get_current_admin_user
from app.api.routes.admin import (
    get_funnel,
    get_overview,
    get_registrations_timeseries,
    list_users,
    update_user_admin_flag,
)
from app.models import (
    BoardColumn,
    IssueBoard,
    IssueStatus,
    Page,
    Space,
    SpaceMember,
    Task,
    Team,
    TeamMember,
    Upload,
    User,
    UserSession,
)
from app.schemas import AdminUpdateUserRequest

pytest.importorskip("aiosqlite")

DUMMY_NONCE = b"0" * 12
DUMMY_TAG = b"0" * 16


@pytest.fixture
async def db() -> AsyncIterator[AsyncSession]:
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
                        UserSession.__table__,
                        Space.__table__,
                        SpaceMember.__table__,
                        Team.__table__,
                        TeamMember.__table__,
                        IssueBoard.__table__,
                        BoardColumn.__table__,
                        Task.__table__,
                        Page.__table__,
                        Upload.__table__,
                    ],
                )
            )
    finally:
        for table, constraint in regex_constraints:
            table.constraints.add(constraint)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


def _task(*, board_id, status_id, created_by_id, number=1) -> Task:
    return Task(
        id=uuid4(),
        board_id=board_id,
        status_id=status_id,
        created_by_id=created_by_id,
        number=number,
        title_ciphertext=b"title",
        title_nonce=DUMMY_NONCE,
        title_tag=DUMMY_TAG,
        description_ciphertext=b"description",
        description_nonce=DUMMY_NONCE,
        description_tag=DUMMY_TAG,
        encryption_key_version=1,
    )


def _page(*, team_id, created_by_id) -> Page:
    return Page(
        id=uuid4(),
        team_id=team_id,
        created_by_id=created_by_id,
        title_ciphertext=b"title",
        title_nonce=DUMMY_NONCE,
        title_tag=DUMMY_TAG,
        content_ciphertext=b"content",
        content_nonce=DUMMY_NONCE,
        content_tag=DUMMY_TAG,
        markdown_ciphertext=b"markdown",
        markdown_nonce=DUMMY_NONCE,
        markdown_tag=DUMMY_TAG,
        encryption_key_version=1,
    )


@pytest.mark.asyncio
async def test_get_current_admin_user_rejects_non_admin_and_allows_admin() -> None:
    admin = User(id=uuid4(), email="admin@example.com", name="Admin", is_platform_admin=True)
    regular = User(id=uuid4(), email="user@example.com", name="User", is_platform_admin=False)

    assert await get_current_admin_user(admin) is admin

    with pytest.raises(HTTPException) as exc:
        await get_current_admin_user(regular)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_set_platform_admin_toggles_flag_and_logs(
    db: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    from app.services.admin import set_platform_admin

    user = User(id=uuid4(), email="promote@example.com", name="Promote Me")
    db.add(user)
    await db.commit()

    with caplog.at_level(logging.INFO, logger="noki.admin"):
        await set_platform_admin(db, user, is_admin=True)
    assert user.is_platform_admin is True
    assert "platform_admin_changed" in caplog.text

    await set_platform_admin(db, user, is_admin=False)
    assert user.is_platform_admin is False


async def _build_scenario(db: AsyncSession):
    admin = User(id=uuid4(), email="admin@example.com", name="Admin", is_platform_admin=True)
    onboarded = User(id=uuid4(), email="onboarded@example.com", name="Onboarded User")
    bare = User(id=uuid4(), email="bare@example.com", name="Bare User")

    space = Space(id=uuid4(), name="Space", created_by_id=onboarded.id)
    team = Team(id=uuid4(), space_id=space.id, name="Team", created_by_id=onboarded.id)
    board = IssueBoard(
        id=uuid4(),
        team_id=team.id,
        name="Board",
        key="ABC",
        created_by_id=onboarded.id,
        next_task_number=2,
    )
    todo_column = BoardColumn(
        id=uuid4(),
        board_id=board.id,
        name="Todo",
        position=0,
        system_status=IssueStatus.TODO,
    )

    session = UserSession(
        id=uuid4(),
        user_id=onboarded.id,
        refresh_jti=uuid4(),
        expires_at=datetime.now(UTC) + timedelta(days=30),
        created_at=datetime.now(UTC) - timedelta(days=10),
        last_seen_at=datetime.now(UTC),
    )

    db.add_all(
        [
            admin,
            onboarded,
            bare,
            space,
            SpaceMember(space_id=space.id, user_id=onboarded.id, role="owner"),
            team,
            TeamMember(team_id=team.id, user_id=onboarded.id, role="owner"),
            board,
            todo_column,
            session,
            _task(board_id=board.id, status_id=todo_column.id, created_by_id=onboarded.id),
            _page(team_id=team.id, created_by_id=onboarded.id),
        ]
    )
    await db.commit()
    return admin, onboarded, bare


@pytest.mark.asyncio
async def test_admin_overview_counts_users_and_resources(db: AsyncSession) -> None:
    admin, *_ = await _build_scenario(db)

    overview = await get_overview(admin, db)

    assert overview.total_users == 3
    assert overview.new_users_today == 3
    assert overview.total_spaces == 1
    assert overview.total_teams == 1
    assert overview.total_boards == 1
    assert overview.total_pages == 1
    assert overview.total_tasks == 1
    assert overview.active_users_24h == 1


@pytest.mark.asyncio
async def test_admin_funnel_counts_each_step(db: AsyncSession) -> None:
    admin, *_ = await _build_scenario(db)

    funnel = await get_funnel(admin, db)

    counts = {step.label: step.count for step in funnel.steps}
    assert counts["Зарегистрировались"] == 3
    assert counts["Space (создали или вступили)"] == 1
    assert counts["Team (создали или вступили)"] == 1
    assert counts["Создали Board или Page"] == 1
    assert counts["Создали Task"] == 1


@pytest.mark.asyncio
async def test_admin_list_users_search_and_pagination(db: AsyncSession) -> None:
    admin, onboarded, bare = await _build_scenario(db)

    all_users = await list_users(admin, db, limit=50, offset=0, q=None)
    assert all_users.total == 3
    assert {item.email for item in all_users.items} == {
        admin.email,
        onboarded.email,
        bare.email,
    }
    onboarded_row = next(item for item in all_users.items if item.id == onboarded.id)
    assert onboarded_row.space_count == 1
    assert onboarded_row.team_count == 1
    assert onboarded_row.last_login_at is not None

    bare_row = next(item for item in all_users.items if item.id == bare.id)
    assert bare_row.space_count == 0
    assert bare_row.last_login_at is None

    filtered = await list_users(admin, db, limit=50, offset=0, q="bare")
    assert filtered.total == 1
    assert filtered.items[0].id == bare.id

    first_page = await list_users(admin, db, limit=1, offset=0, q=None)
    assert len(first_page.items) == 1
    assert first_page.total == 3


@pytest.mark.asyncio
async def test_admin_update_user_admin_flag_route(db: AsyncSession) -> None:
    admin, onboarded, _ = await _build_scenario(db)

    updated = await update_user_admin_flag(
        onboarded.id,
        AdminUpdateUserRequest(is_platform_admin=True),
        admin,
        db,
        None,
    )
    assert updated.is_platform_admin is True
    assert onboarded.is_platform_admin is True

    with pytest.raises(HTTPException) as exc:
        await update_user_admin_flag(
            uuid4(),
            AdminUpdateUserRequest(is_platform_admin=True),
            admin,
            db,
            None,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_admin_registrations_timeseries_groups_by_day(db: AsyncSession) -> None:
    admin, *_ = await _build_scenario(db)

    result = await get_registrations_timeseries(admin, db, days=30)

    assert sum(point.count for point in result.points) == 3
