from __future__ import annotations

import base64
from collections.abc import AsyncIterator, Awaitable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import CheckConstraint, event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.routes.issues import (
    claim_task,
    configure_columns,
    create_board,
    create_task,
    delete_board,
    delete_task,
    get_board,
    list_my_calendar_cards,
    list_my_task_cards,
    reorder_tasks,
    set_default_column,
    update_board,
    update_task,
    update_task_status,
)
from app.api.routes.pages import create_page, delete_page, get_page, update_page
from app.core.config import settings
from app.core.encryption import DataCipher
from app.models import (
    BoardColumn,
    IssueBoard,
    IssueStatus,
    Page,
    Space,
    SpaceMember,
    Task,
    TaskActivity,
    TaskLabel,
    TaskLabelLink,
    Team,
    TeamMember,
    Upload,
    User,
)
from app.schemas import (
    BoardColumnsUpdate,
    BoardCreate,
    BoardUpdate,
    ColumnDefaultUpdate,
    PageCreate,
    PageUpdate,
    TaskCreate,
    TaskOrderRequest,
    TaskStatusUpdate,
    TaskUpdate,
)
from app.schemas.issues import ColumnConfig, TaskOrderColumn
from app.services import content_encryption

pytest.importorskip("aiosqlite")

TEST_KEY = base64.urlsafe_b64encode(bytes(range(32))).decode()


@dataclass(slots=True)
class ResourceScenario:
    space_owner: User
    owner: User
    admin: User
    member: User
    peer: User
    outsider: User
    space: Space
    team: Team
    board: IssueBoard
    columns: dict[IssueStatus, BoardColumn]
    other_space: Space
    other_team: Team
    other_board: IssueBoard
    other_columns: dict[IssueStatus, BoardColumn]


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
                        Page.__table__,
                        Upload.__table__,
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
async def scenario(db: AsyncSession) -> ResourceScenario:
    space_owner = User(id=uuid4(), email="space-owner@example.com", name="Space Owner")
    owner = User(id=uuid4(), email="owner@example.com", name="Team Owner")
    admin = User(id=uuid4(), email="admin@example.com", name="Team Admin")
    member = User(id=uuid4(), email="member@example.com", name="Member")
    peer = User(id=uuid4(), email="peer@example.com", name="Peer")
    outsider = User(id=uuid4(), email="outsider@example.com", name="Outsider")

    space = Space(
        id=uuid4(),
        name="Noki",
        created_by_id=space_owner.id,
    )
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
        next_task_number=1,
    )
    columns = {
        IssueStatus.TODO: BoardColumn(
            id=uuid4(),
            board_id=board.id,
            name="Todo",
            position=0,
            system_status=IssueStatus.TODO,
        ),
        IssueStatus.IN_PROGRESS: BoardColumn(
            id=uuid4(),
            board_id=board.id,
            name="In Progress",
            position=1,
            system_status=IssueStatus.IN_PROGRESS,
        ),
        IssueStatus.DONE: BoardColumn(
            id=uuid4(),
            board_id=board.id,
            name="Done",
            position=2,
            system_status=IssueStatus.DONE,
        ),
    }

    other_space = Space(
        id=uuid4(),
        name="Other Space",
        created_by_id=outsider.id,
    )
    other_team = Team(
        id=uuid4(),
        space_id=other_space.id,
        name="Private Team",
        created_by_id=outsider.id,
    )
    other_board = IssueBoard(
        id=uuid4(),
        team_id=other_team.id,
        name="Private Issues",
        key="EXT",
        created_by_id=outsider.id,
        next_task_number=1,
    )
    other_columns = {
        IssueStatus.TODO: BoardColumn(
            id=uuid4(),
            board_id=other_board.id,
            name="Todo",
            position=0,
            system_status=IssueStatus.TODO,
        ),
        IssueStatus.IN_PROGRESS: BoardColumn(
            id=uuid4(),
            board_id=other_board.id,
            name="In Progress",
            position=1,
            system_status=IssueStatus.IN_PROGRESS,
        ),
        IssueStatus.DONE: BoardColumn(
            id=uuid4(),
            board_id=other_board.id,
            name="Done",
            position=2,
            system_status=IssueStatus.DONE,
        ),
    }

    db.add_all(
        [
            space_owner,
            owner,
            admin,
            member,
            peer,
            outsider,
            space,
            SpaceMember(space_id=space.id, user_id=space_owner.id, role="owner"),
            SpaceMember(space_id=space.id, user_id=owner.id, role="member"),
            SpaceMember(space_id=space.id, user_id=admin.id, role="member"),
            SpaceMember(space_id=space.id, user_id=member.id, role="member"),
            SpaceMember(space_id=space.id, user_id=peer.id, role="member"),
            team,
            TeamMember(team_id=team.id, user_id=owner.id, role="owner"),
            TeamMember(team_id=team.id, user_id=admin.id, role="admin"),
            TeamMember(team_id=team.id, user_id=member.id, role="member"),
            TeamMember(team_id=team.id, user_id=peer.id, role="member"),
            board,
            *columns.values(),
            other_space,
            SpaceMember(space_id=other_space.id, user_id=outsider.id, role="owner"),
            other_team,
            TeamMember(team_id=other_team.id, user_id=outsider.id, role="owner"),
            other_board,
            *other_columns.values(),
        ]
    )
    await db.commit()
    return ResourceScenario(
        space_owner=space_owner,
        owner=owner,
        admin=admin,
        member=member,
        peer=peer,
        outsider=outsider,
        space=space,
        team=team,
        board=board,
        columns=columns,
        other_space=other_space,
        other_team=other_team,
        other_board=other_board,
        other_columns=other_columns,
    )


async def seed_task(
    db: AsyncSession,
    scenario: ResourceScenario,
    *,
    created_by: User | None = None,
    assignee: User | None = None,
    board: IssueBoard | None = None,
    columns: dict[IssueStatus, BoardColumn] | None = None,
    title: str = "Seed issue",
    description: str = "Seed description",
    deadline: datetime | None = None,
) -> Task:
    selected_board = board or scenario.board
    selected_columns = columns or scenario.columns
    creator = created_by or scenario.owner
    number = selected_board.next_task_number
    selected_board.next_task_number += 1
    task = Task(
        id=uuid4(),
        board_id=selected_board.id,
        status_id=selected_columns[IssueStatus.TODO].id,
        assignee_id=assignee.id if assignee is not None else None,
        created_by_id=creator.id,
        number=number,
        deadline=deadline,
        position=number,
    )
    content_encryption.set_task_title(task, title)
    content_encryption.set_task_description(task, description)
    db.add(task)
    await db.commit()
    return task


async def assert_http_error(
    expected_status: int,
    awaitable: Awaitable[object],
) -> HTTPException:
    with pytest.raises(HTTPException) as exc_info:
        await awaitable
    assert exc_info.value.status_code == expected_status
    return exc_info.value


@pytest.mark.parametrize("actor_name", ["owner", "admin"])
async def test_owner_and_admin_can_create_update_and_delete_issue(
    db: AsyncSession,
    scenario: ResourceScenario,
    actor_name: str,
) -> None:
    actor = getattr(scenario, actor_name)
    created = await create_task(
        scenario.board.id,
        TaskCreate(title=f"{actor_name} issue", description="Initial"),
        actor,
        db,
        None,
    )
    assert created.created_by.id == actor.id
    assert created.assignee is None

    deadline = datetime(2032, 5, 6, 12, 0, tzinfo=UTC)
    updated = await update_task(
        created.id,
        TaskUpdate(
            title="Managed title",
            description="Managed description",
            assignee_id=scenario.member.id,
            deadline=deadline,
            status_id=scenario.columns[IssueStatus.IN_PROGRESS].id,
        ),
        actor,
        db,
        None,
    )
    assert updated.title == "Managed title"
    assert updated.description == "Managed description"
    assert updated.assignee is not None
    assert updated.assignee.id == scenario.member.id
    assert updated.deadline is not None
    assert updated.deadline.date() == deadline.date()
    assert updated.status_id == scenario.columns[IssueStatus.IN_PROGRESS].id

    cleared = await update_task(
        created.id,
        TaskUpdate(assignee_id=None, deadline=None),
        actor,
        db,
        None,
    )
    assert cleared.assignee is None
    assert cleared.deadline is None

    renamed_board = await update_board(
        scenario.board.id,
        BoardUpdate(name=f"{actor_name.title()} planning"),
        actor,
        db,
        None,
    )
    assert renamed_board.name == f"{actor_name.title()} planning"

    await delete_task(created.id, actor, db, None)
    deleted = await db.get(Task, created.id)
    assert deleted is not None
    assert deleted.deleted_at is not None


@pytest.mark.parametrize("key", ["PR", "LONGA"])
async def test_board_accepts_two_to_five_letter_key(
    db: AsyncSession,
    scenario: ResourceScenario,
    key: str,
) -> None:
    board = await create_board(
        scenario.team.id,
        BoardCreate(name=f"Board {key}", key=key.lower()),
        scenario.owner,
        db,
        None,
    )
    assert board.key == key


async def test_my_task_cards_use_cursor_without_loading_descriptions(
    db: AsyncSession,
    scenario: ResourceScenario,
) -> None:
    for number in range(3):
        await seed_task(
            db,
            scenario,
            assignee=scenario.member,
            title=f"Assigned {number}",
            description="Private full description",
        )
    await seed_task(db, scenario, assignee=scenario.owner, title="Not assigned")
    db.expunge_all()

    first = await list_my_task_cards(scenario.member, db, limit=2)
    second = await list_my_task_cards(scenario.member, db, limit=2, cursor=first.next_cursor)
    assert len(first.items) == 2
    assert len(second.items) == 1
    assert first.next_cursor is not None
    assert second.next_cursor is None
    assert {item.id for item in first.items}.isdisjoint({item.id for item in second.items})
    assert all("description" not in item.model_dump() for item in first.items + second.items)


async def test_my_calendar_only_reads_selected_week(
    db: AsyncSession,
    scenario: ResourceScenario,
) -> None:
    week_start = datetime(2032, 5, 3, tzinfo=UTC)
    in_week = await seed_task(
        db,
        scenario,
        assignee=scenario.member,
        deadline=datetime(2032, 5, 4, 9, tzinfo=UTC),
    )
    await seed_task(
        db,
        scenario,
        assignee=scenario.member,
        deadline=datetime(2032, 6, 4, 9, tzinfo=UTC),
    )
    db.expunge_all()
    cards = await list_my_calendar_cards(
        scenario.member,
        db,
        deadline_from=week_start,
        deadline_before=datetime(2032, 5, 10, tzinfo=UTC),
    )
    assert [card.id for card in cards] == [in_week.id]


async def test_reorder_keeps_unloaded_tasks_in_place(
    db: AsyncSession,
    scenario: ResourceScenario,
) -> None:
    first = await seed_task(db, scenario, title="First")
    second = await seed_task(db, scenario, title="Second")
    hidden = await seed_task(db, scenario, title="Hidden")

    await reorder_tasks(
        scenario.board.id,
        TaskOrderRequest(
            columns=[
                TaskOrderColumn(
                    column_id=scenario.columns[IssueStatus.TODO].id,
                    task_ids=[second.id, first.id],
                ),
                TaskOrderColumn(
                    column_id=scenario.columns[IssueStatus.IN_PROGRESS].id,
                    task_ids=[],
                ),
                TaskOrderColumn(
                    column_id=scenario.columns[IssueStatus.DONE].id,
                    task_ids=[],
                ),
            ]
        ),
        scenario.owner,
        db,
        None,
    )
    db.expunge_all()
    ordered = list(
        await db.scalars(
            select(Task).where(Task.board_id == scenario.board.id).order_by(Task.position)
        )
    )
    assert [task.id for task in ordered] == [second.id, first.id, hidden.id]


async def test_new_board_has_exactly_one_default_column(
    db: AsyncSession,
    scenario: ResourceScenario,
) -> None:
    board = await create_board(
        scenario.team.id,
        BoardCreate(name="Planning", key="PLN"),
        scenario.owner,
        db,
        None,
    )
    columns = list(
        await db.scalars(
            select(BoardColumn)
            .where(BoardColumn.board_id == board.id)
            .order_by(BoardColumn.position)
        )
    )

    assert len(columns) == 3
    assert [column.name for column in columns] == ["Todo", "In Progress", "Done"]
    assert [column.name for column in columns if column.is_default] == ["Todo"]

    selected_default = await set_default_column(
        board.id,
        ColumnDefaultUpdate(column_id=columns[1].id),
        scenario.owner,
        db,
        None,
    )
    created = await create_task(
        board.id,
        TaskCreate(title="Uses the starred column"),
        scenario.owner,
        db,
        None,
    )

    assert selected_default.id == columns[1].id
    assert created.status_id == columns[1].id


async def test_deadline_only_patch_does_not_reencrypt_issue_content(
    db: AsyncSession,
    scenario: ResourceScenario,
) -> None:
    task = await seed_task(db, scenario)
    encrypted_before = (
        task.title_ciphertext,
        task.title_nonce,
        task.title_tag,
        task.description_ciphertext,
        task.description_nonce,
        task.description_tag,
    )

    await update_task(
        task.id,
        TaskUpdate(deadline=datetime(2031, 1, 2, tzinfo=UTC)),
        scenario.owner,
        db,
        None,
    )
    await db.refresh(task)

    assert (
        task.title_ciphertext,
        task.title_nonce,
        task.title_tag,
        task.description_ciphertext,
        task.description_nonce,
        task.description_tag,
    ) == encrypted_before


@pytest.mark.parametrize("target_name", ["space_owner", "outsider"])
async def test_manager_cannot_assign_user_without_direct_team_access(
    db: AsyncSession,
    scenario: ResourceScenario,
    target_name: str,
) -> None:
    target = getattr(scenario, target_name)
    task = await seed_task(db, scenario, assignee=scenario.member)

    await assert_http_error(
        400,
        create_task(
            scenario.board.id,
            TaskCreate(title="Invalid assignee", assignee_id=target.id),
            scenario.owner,
            db,
            None,
        ),
    )
    await assert_http_error(
        400,
        update_task(
            task.id,
            TaskUpdate(assignee_id=target.id),
            scenario.owner,
            db,
            None,
        ),
    )
    await db.refresh(task)
    assert task.assignee_id == scenario.member.id


@pytest.mark.parametrize(
    "field_name",
    ["assignee_id"],
)
async def test_member_generic_patch_rejects_each_field(
    db: AsyncSession,
    scenario: ResourceScenario,
    field_name: str,
) -> None:
    task = await seed_task(db, scenario, assignee=scenario.member)
    values = {
        "title": "Forbidden title",
        "description": "Forbidden description",
        "deadline": datetime(2035, 1, 1, tzinfo=UTC),
        "assignee_id": scenario.peer.id,
        "status_id": scenario.columns[IssueStatus.DONE].id,
    }

    await assert_http_error(
        403,
        update_task(
            task.id,
            TaskUpdate(**{field_name: values[field_name]}),
            scenario.member,
            db,
            None,
        ),
    )
    await db.refresh(task)
    assert content_encryption.get_task_title(task) == "Seed issue"
    assert content_encryption.get_task_description(task) == "Seed description"
    assert task.deadline is None
    assert task.assignee_id == scenario.member.id
    assert task.status_id == scenario.columns[IssueStatus.TODO].id


async def test_member_forbidden_multifield_patch_is_fully_atomic(
    db: AsyncSession,
    scenario: ResourceScenario,
) -> None:
    original_deadline = datetime(2030, 1, 1, tzinfo=UTC)
    task = await seed_task(
        db,
        scenario,
        assignee=scenario.member,
        deadline=original_deadline,
    )
    encrypted_before = (
        task.title_ciphertext,
        task.title_nonce,
        task.title_tag,
        task.description_ciphertext,
        task.description_nonce,
        task.description_tag,
    )

    await assert_http_error(
        403,
        update_task(
            task.id,
            TaskUpdate(
                title="Must not persist",
                description="Must not persist",
                deadline=datetime(2040, 1, 1, tzinfo=UTC),
                assignee_id=scenario.peer.id,
                status_id=scenario.columns[IssueStatus.DONE].id,
            ),
            scenario.member,
            db,
            None,
        ),
    )
    await db.refresh(task)

    assert (
        task.title_ciphertext,
        task.title_nonce,
        task.title_tag,
        task.description_ciphertext,
        task.description_nonce,
        task.description_tag,
    ) == encrypted_before
    assert content_encryption.get_task_title(task) == "Seed issue"
    assert content_encryption.get_task_description(task) == "Seed description"
    assert task.deadline is not None
    assert task.deadline.date() == original_deadline.date()
    assert task.assignee_id == scenario.member.id
    assert task.status_id == scenario.columns[IssueStatus.TODO].id


async def test_member_cannot_clear_assignee_or_deadline(
    db: AsyncSession,
    scenario: ResourceScenario,
) -> None:
    original_deadline = datetime(2030, 1, 1, tzinfo=UTC)
    task = await seed_task(
        db,
        scenario,
        assignee=scenario.member,
        deadline=original_deadline,
    )

    await assert_http_error(
        403,
        update_task(
            task.id,
            TaskUpdate(assignee_id=None),
            scenario.member,
            db,
            None,
        ),
    )
    await update_task(
        task.id,
        TaskUpdate(deadline=None),
        scenario.member,
        db,
        None,
    )
    await db.refresh(task)
    assert task.assignee_id == scenario.member.id
    assert task.deadline is None


async def test_member_can_create_but_cannot_delete_issue(
    db: AsyncSession,
    scenario: ResourceScenario,
) -> None:
    created = await create_task(
        scenario.board.id,
        TaskCreate(title="Member issue"),
        scenario.member,
        db,
        None,
    )
    assert created.created_by.id == scenario.member.id
    task = await seed_task(db, scenario, assignee=scenario.member)
    await assert_http_error(
        403,
        delete_task(task.id, scenario.member, db, None),
    )
    assert await db.get(Task, task.id) is not None


@pytest.mark.parametrize("actor_name", ["owner", "admin", "member"])
async def test_direct_team_member_can_claim_free_issue_once(
    db: AsyncSession,
    scenario: ResourceScenario,
    actor_name: str,
) -> None:
    actor = getattr(scenario, actor_name)
    task = await seed_task(db, scenario)

    claimed = await claim_task(task.id, actor, db, None)
    assert claimed.assignee is not None
    assert claimed.assignee.id == actor.id

    in_progress = await update_task_status(
        task.id,
        TaskStatusUpdate(status=IssueStatus.IN_PROGRESS),
        actor,
        db,
        None,
    )
    assert in_progress.status_id == scenario.columns[IssueStatus.IN_PROGRESS].id

    await assert_http_error(409, claim_task(task.id, actor, db, None))
    contender = scenario.peer if actor.id != scenario.peer.id else scenario.member
    await assert_http_error(409, claim_task(task.id, contender, db, None))


async def test_member_cannot_claim_issue_assigned_to_another_user(
    db: AsyncSession,
    scenario: ResourceScenario,
) -> None:
    task = await seed_task(db, scenario, assignee=scenario.peer)
    await assert_http_error(409, claim_task(task.id, scenario.member, db, None))
    await db.refresh(task)
    assert task.assignee_id == scenario.peer.id


async def test_member_can_change_only_own_issue_to_each_system_status(
    db: AsyncSession,
    scenario: ResourceScenario,
) -> None:
    task = await seed_task(db, scenario, assignee=scenario.member)

    for issue_status in (
        IssueStatus.IN_PROGRESS,
        IssueStatus.DONE,
        IssueStatus.TODO,
    ):
        updated = await update_task_status(
            task.id,
            TaskStatusUpdate(status=issue_status),
            scenario.member,
            db,
            None,
        )
        assert updated.status_id == scenario.columns[issue_status].id


async def test_member_cannot_change_status_of_free_or_foreign_issue(
    db: AsyncSession,
    scenario: ResourceScenario,
) -> None:
    free_task = await seed_task(db, scenario, title="Free")
    foreign_task = await seed_task(
        db,
        scenario,
        assignee=scenario.peer,
        title="Foreign",
    )

    await assert_http_error(
        403,
        update_task_status(
            free_task.id,
            TaskStatusUpdate(status=IssueStatus.IN_PROGRESS),
            scenario.member,
            db,
            None,
        ),
    )
    await assert_http_error(
        403,
        update_task_status(
            foreign_task.id,
            TaskStatusUpdate(status=IssueStatus.DONE),
            scenario.member,
            db,
            None,
        ),
    )
    await db.refresh(free_task)
    await db.refresh(foreign_task)
    assert free_task.status_id == scenario.columns[IssueStatus.TODO].id
    assert foreign_task.status_id == scenario.columns[IssueStatus.TODO].id


async def test_member_cannot_move_issue_out_of_custom_status_via_status_endpoint(
    db: AsyncSession,
    scenario: ResourceScenario,
) -> None:
    custom_column = BoardColumn(
        id=uuid4(),
        board_id=scenario.board.id,
        name="Needs triage",
        position=3,
        system_status=None,
    )
    db.add(custom_column)
    await db.commit()
    task = await seed_task(db, scenario, assignee=scenario.member)
    task.status_id = custom_column.id
    await db.commit()

    await assert_http_error(
        403,
        update_task_status(
            task.id,
            TaskStatusUpdate(status=IssueStatus.IN_PROGRESS),
            scenario.member,
            db,
            None,
        ),
    )
    await db.refresh(task)
    assert task.status_id == custom_column.id


@pytest.mark.parametrize("actor_name", ["owner", "admin"])
async def test_owner_and_admin_can_change_status_of_any_team_issue(
    db: AsyncSession,
    scenario: ResourceScenario,
    actor_name: str,
) -> None:
    task = await seed_task(db, scenario, assignee=scenario.peer)
    actor = getattr(scenario, actor_name)

    updated = await update_task_status(
        task.id,
        TaskStatusUpdate(status=IssueStatus.DONE),
        actor,
        db,
        None,
    )
    assert updated.status_id == scenario.columns[IssueStatus.DONE].id


def test_issue_request_schemas_reject_invalid_status_and_extra_fields() -> None:
    with pytest.raises(ValidationError):
        TaskStatusUpdate.model_validate({"status": "blocked"})
    with pytest.raises(ValidationError):
        TaskStatusUpdate.model_validate({})
    with pytest.raises(ValidationError):
        TaskStatusUpdate.model_validate({"status": "todo", "assignee_id": str(uuid4())})
    with pytest.raises(ValidationError):
        TaskUpdate.model_validate({"title": "Valid", "created_by_id": str(uuid4())})
    with pytest.raises(ValidationError):
        TaskUpdate.model_validate({"title": None})
    with pytest.raises(ValidationError):
        TaskUpdate.model_validate({"status_id": None})
    with pytest.raises(ValidationError):
        ColumnDefaultUpdate.model_validate({})
    with pytest.raises(ValidationError):
        ColumnDefaultUpdate.model_validate({"column_id": str(uuid4()), "unexpected": str(uuid4())})


async def test_member_cannot_mutate_board_or_bulk_reorder_tasks(
    db: AsyncSession,
    scenario: ResourceScenario,
) -> None:
    task = await seed_task(db, scenario, assignee=scenario.member)
    todo_status_id = scenario.columns[IssueStatus.TODO].id
    detail = await get_board(scenario.board.id, scenario.member, db)
    assert detail.can_manage_tasks is False
    assert detail.can_claim_tasks is True

    await assert_http_error(
        403,
        create_board(
            scenario.team.id,
            BoardCreate(name="Forbidden", key="NOX"),
            scenario.member,
            db,
            None,
        ),
    )
    await assert_http_error(
        403,
        update_board(
            scenario.board.id,
            BoardUpdate(name="Forbidden rename"),
            scenario.member,
            db,
            None,
        ),
    )
    await assert_http_error(
        403,
        configure_columns(
            scenario.board.id,
            BoardColumnsUpdate(
                columns=[
                    ColumnConfig(id=column.id, name=column.name)
                    for column in scenario.columns.values()
                ]
            ),
            scenario.member,
            db,
            None,
        ),
    )
    await assert_http_error(
        403,
        reorder_tasks(
            scenario.board.id,
            TaskOrderRequest(
                columns=[
                    TaskOrderColumn(
                        column_id=scenario.columns[IssueStatus.TODO].id,
                        task_ids=[task.id],
                    ),
                    TaskOrderColumn(
                        column_id=scenario.columns[IssueStatus.IN_PROGRESS].id,
                        task_ids=[],
                    ),
                    TaskOrderColumn(
                        column_id=scenario.columns[IssueStatus.DONE].id,
                        task_ids=[],
                    ),
                ]
            ),
            scenario.member,
            db,
            None,
        ),
    )
    await assert_http_error(
        403,
        delete_board(scenario.board.id, scenario.member, db, None),
    )

    await db.refresh(scenario.board)
    await db.refresh(task)
    assert task.status_id == todo_status_id
    assert scenario.board.name == "Issues"


async def test_issue_and_board_idor_returns_404_without_mutation(
    db: AsyncSession,
    scenario: ResourceScenario,
) -> None:
    task = await seed_task(db, scenario, assignee=scenario.member)
    foreign_task = await seed_task(
        db,
        scenario,
        created_by=scenario.outsider,
        assignee=scenario.outsider,
        board=scenario.other_board,
        columns=scenario.other_columns,
        title="Private issue",
    )

    await assert_http_error(404, get_board(scenario.board.id, scenario.outsider, db))
    await assert_http_error(
        404,
        create_task(
            scenario.board.id,
            TaskCreate(title="IDOR create"),
            scenario.outsider,
            db,
            None,
        ),
    )
    await assert_http_error(
        404,
        update_task(
            task.id,
            TaskUpdate(title="IDOR update"),
            scenario.outsider,
            db,
            None,
        ),
    )
    await assert_http_error(
        404,
        update_task_status(
            task.id,
            TaskStatusUpdate(status=IssueStatus.DONE),
            scenario.outsider,
            db,
            None,
        ),
    )
    await assert_http_error(404, claim_task(task.id, scenario.outsider, db, None))
    await assert_http_error(404, delete_task(task.id, scenario.outsider, db, None))
    await assert_http_error(
        404,
        update_task_status(
            foreign_task.id,
            TaskStatusUpdate(status=IssueStatus.DONE),
            scenario.member,
            db,
            None,
        ),
    )

    await db.refresh(task)
    await db.refresh(foreign_task)
    assert content_encryption.get_task_title(task) == "Seed issue"
    assert task.status_id == scenario.columns[IssueStatus.TODO].id
    assert foreign_task.status_id == scenario.other_columns[IssueStatus.TODO].id


def editor_document(text: str) -> dict[str, object]:
    return {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text}],
            }
        ],
    }


async def test_member_creates_page_as_backend_author_and_edits_own_page(
    db: AsyncSession,
    scenario: ResourceScenario,
) -> None:
    created = await create_page(
        scenario.team.id,
        PageCreate(title="Member page"),
        scenario.member,
        db,
        None,
    )
    assert created.created_by.id == scenario.member.id
    assert created.can_edit is True
    assert created.can_delete is True
    stored = await db.get(Page, created.id)
    assert stored is not None
    assert stored.created_by_id == scenario.member.id

    document = editor_document("Member content")
    updated = await update_page(
        created.id,
        PageUpdate(
            expected_updated_at=created.updated_at,
            title="Member page updated",
            content=document,
            markdown="Member content",
        ),
        scenario.member,
        db,
        None,
    )
    assert updated.title == "Member page updated"
    assert updated.content == document
    assert updated.markdown == "Member content"

    await delete_page(created.id, scenario.member, db, None)
    stored = await db.get(Page, created.id)
    assert stored is not None
    assert stored.deleted_at is not None


async def test_page_update_rejects_a_stale_version(
    db: AsyncSession,
    scenario: ResourceScenario,
) -> None:
    created = await create_page(
        scenario.team.id,
        PageCreate(title="Concurrent page"),
        scenario.member,
        db,
        None,
    )
    first_update = await update_page(
        created.id,
        PageUpdate(
            expected_updated_at=created.updated_at,
            title="First writer",
        ),
        scenario.member,
        db,
        None,
    )
    assert first_update.title == "First writer"

    await assert_http_error(
        409,
        update_page(
            created.id,
            PageUpdate(
                expected_updated_at=created.updated_at,
                title="Stale writer",
            ),
            scenario.member,
            db,
            None,
        ),
    )
    stored = await db.get(Page, created.id)
    assert stored is not None
    assert content_encryption.get_page_title(stored) == "First writer"


async def test_member_cannot_edit_or_delete_foreign_page(
    db: AsyncSession,
    scenario: ResourceScenario,
) -> None:
    created = await create_page(
        scenario.team.id,
        PageCreate(title="Author page"),
        scenario.member,
        db,
        None,
    )

    visible = await get_page(created.id, scenario.peer, db)
    assert visible.can_edit is False
    assert visible.can_delete is False
    await assert_http_error(
        403,
        update_page(
            created.id,
            PageUpdate(
                expected_updated_at=created.updated_at,
                title="Forbidden",
                content=editor_document("Forbidden content"),
                markdown="Forbidden content",
            ),
            scenario.peer,
            db,
            None,
        ),
    )
    await assert_http_error(
        403,
        delete_page(created.id, scenario.peer, db, None),
    )

    stored = await db.get(Page, created.id)
    assert stored is not None
    assert content_encryption.get_page_title(stored) == "Author page"
    assert content_encryption.get_page_content(stored) == {
        "type": "doc",
        "content": [{"type": "paragraph"}],
    }
    assert content_encryption.get_page_markdown(stored) == ""


@pytest.mark.parametrize("manager_name", ["owner", "admin"])
async def test_owner_and_admin_can_edit_and_delete_member_page(
    db: AsyncSession,
    scenario: ResourceScenario,
    manager_name: str,
) -> None:
    created = await create_page(
        scenario.team.id,
        PageCreate(title="Member page"),
        scenario.member,
        db,
        None,
    )
    manager = getattr(scenario, manager_name)

    updated = await update_page(
        created.id,
        PageUpdate(
            expected_updated_at=created.updated_at,
            title=f"Edited by {manager_name}",
        ),
        manager,
        db,
        None,
    )
    assert updated.title == f"Edited by {manager_name}"
    assert updated.created_by.id == scenario.member.id
    assert updated.can_edit is True

    await delete_page(created.id, manager, db, None)
    stored = await db.get(Page, created.id)
    assert stored is not None
    assert stored.deleted_at is not None


async def test_manager_can_preserve_author_upload_while_editing_page(
    db: AsyncSession,
    scenario: ResourceScenario,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "upload_dir", tmp_path)
    created = await create_page(
        scenario.team.id,
        PageCreate(title="Page with an image"),
        scenario.member,
        db,
        None,
    )
    upload = Upload(
        id=uuid4(),
        filename=f"{uuid4().hex}.webp",
        content_type="image/webp",
        size_bytes=100,
        width=10,
        height=10,
        owner_id=scenario.member.id,
        page_id=created.id,
    )
    content_encryption.set_upload_original_name(upload, "member-image.png")
    db.add(upload)
    await db.commit()
    (tmp_path / upload.filename).write_bytes(b"image")

    document = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
            },
            {
                "type": "image",
                "attrs": {"src": f"/media/images/{upload.filename}"},
            },
        ],
    }
    updated = await update_page(
        created.id,
        PageUpdate(
            expected_updated_at=created.updated_at,
            content=document,
            markdown=f"![image](/media/images/{upload.filename})",
        ),
        scenario.admin,
        db,
        None,
    )

    assert updated.content == document
    await db.refresh(upload)
    assert upload.page_id == created.id


async def test_page_update_cannot_steal_upload_from_another_page(
    db: AsyncSession,
    scenario: ResourceScenario,
) -> None:
    source = await create_page(
        scenario.team.id,
        PageCreate(title="Source page"),
        scenario.member,
        db,
        None,
    )
    target = await create_page(
        scenario.team.id,
        PageCreate(title="Target page"),
        scenario.member,
        db,
        None,
    )
    upload = Upload(
        id=uuid4(),
        filename=f"{uuid4().hex}.webp",
        content_type="image/webp",
        size_bytes=100,
        width=10,
        height=10,
        owner_id=scenario.member.id,
        page_id=source.id,
    )
    content_encryption.set_upload_original_name(upload, "source-image.png")
    db.add(upload)
    await db.commit()
    document = {
        "type": "doc",
        "content": [
            {
                "type": "image",
                "attrs": {"src": f"/media/images/{upload.filename}"},
            }
        ],
    }

    await assert_http_error(
        400,
        update_page(
            target.id,
            PageUpdate(
                expected_updated_at=target.updated_at,
                content=document,
                markdown=f"![image](/media/images/{upload.filename})",
            ),
            scenario.member,
            db,
            None,
        ),
    )
    await db.refresh(upload)
    assert upload.page_id == source.id


async def test_page_idor_returns_404_for_outsider(
    db: AsyncSession,
    scenario: ResourceScenario,
) -> None:
    created = await create_page(
        scenario.team.id,
        PageCreate(title="Private page"),
        scenario.member,
        db,
        None,
    )

    await assert_http_error(
        404,
        create_page(
            scenario.team.id,
            PageCreate(title="IDOR create"),
            scenario.outsider,
            db,
            None,
        ),
    )
    await assert_http_error(404, get_page(created.id, scenario.outsider, db))
    await assert_http_error(
        404,
        update_page(
            created.id,
            PageUpdate(
                expected_updated_at=created.updated_at,
                title="IDOR update",
            ),
            scenario.outsider,
            db,
            None,
        ),
    )
    await assert_http_error(
        404,
        delete_page(created.id, scenario.outsider, db, None),
    )

    stored = await db.get(Page, created.id)
    assert stored is not None
    assert content_encryption.get_page_title(stored) == "Private page"


def test_page_request_schemas_reject_author_fields() -> None:
    author_id = str(uuid4())
    for field_name in ("created_by_id", "author_id"):
        with pytest.raises(ValidationError):
            PageCreate.model_validate({"title": "Page", field_name: author_id})
        with pytest.raises(ValidationError):
            PageUpdate.model_validate(
                {
                    "expected_updated_at": datetime.now(UTC),
                    "title": "Page",
                    field_name: author_id,
                }
            )
