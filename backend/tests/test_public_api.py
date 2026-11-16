from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import CheckConstraint, event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

pytest.importorskip("aiosqlite")

from app.api.deps import get_redis
from app.api.public_deps import get_api_principal
from app.api.routes.api_tokens import create_api_token, list_api_tokens, revoke_api_token
from app.core.config import settings
from app.core.encryption import DataCipher
from app.core.security import create_access_token
from app.db.session import get_db
from app.main import SMALL_REQUEST_BODY_BYTES, app
from app.models import (
    ApiToken,
    BoardColumn,
    Comment,
    IssueBoard,
    IssueStatus,
    Space,
    SpaceMember,
    Task,
    TaskActivity,
    TaskLabel,
    TaskLabelLink,
    Team,
    TeamMember,
    Todo,
    User,
)
from app.schemas import ApiTokenCreate
from app.services import content_encryption
from app.services.api_tokens import generate_api_token, hash_api_token, is_api_token

TEST_KEY = base64.urlsafe_b64encode(bytes(range(32))).decode()
PUBLIC_API_PREFIX = settings.public_api_v1_prefix


class FakeRedis:
    def __init__(self) -> None:
        self.eval_calls: list[tuple[object, ...]] = []
        self.results: list[list[int]] = []

    async def eval(self, *arguments: object) -> list[int]:
        self.eval_calls.append(arguments)
        if self.results:
            return self.results.pop(0)
        window_seconds = int(arguments[-1])
        return [1, window_seconds]


@dataclass(slots=True)
class PublicApiScenario:
    owner: User
    member: User
    outsider: User
    space: Space
    team: Team
    board: IssueBoard
    default_column: BoardColumn
    done_column: BoardColumn
    tasks: list[Task]
    other_task: Task


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
                        ApiToken.__table__,
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
                        Comment.__table__,
                        Todo.__table__,
                    ],
                )
            )
    finally:
        for table, constraint in regex_constraints:
            table.constraints.add(constraint)

    monkeypatch.setattr(content_encryption, "get_data_cipher", lambda: DataCipher(TEST_KEY))
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


def _new_user(email: str, name: str) -> User:
    return User(
        id=uuid4(),
        email=email,
        name=name,
        is_active=True,
        auth_version=0,
        timezone="UTC",
    )


def _new_task(
    *,
    board: IssueBoard,
    column: BoardColumn,
    creator: User,
    number: int,
    title: str,
    updated_at: datetime,
) -> Task:
    task = Task(
        id=uuid4(),
        board_id=board.id,
        status_id=column.id,
        created_by_id=creator.id,
        number=number,
        position=number,
        created_at=updated_at,
        updated_at=updated_at,
    )
    content_encryption.set_task_title(task, title)
    content_encryption.set_task_description(task, f"Description for {title}")
    return task


@pytest.fixture
async def scenario(db: AsyncSession) -> PublicApiScenario:
    owner = _new_user("owner@example.com", "Owner")
    member = _new_user("member@example.com", "Member")
    outsider = _new_user("outsider@example.com", "Outsider")

    space = Space(id=uuid4(), name="Noki", created_by_id=owner.id)
    team = Team(id=uuid4(), space_id=space.id, name="Development", created_by_id=owner.id)
    board = IssueBoard(
        id=uuid4(),
        team_id=team.id,
        name="Issues",
        key="DEV",
        created_by_id=owner.id,
        next_task_number=4,
    )
    default_column = BoardColumn(
        id=uuid4(),
        board_id=board.id,
        name="Todo",
        position=0,
        system_status=IssueStatus.TODO,
        is_default=True,
    )
    done_column = BoardColumn(
        id=uuid4(),
        board_id=board.id,
        name="Done",
        position=1,
        system_status=IssueStatus.DONE,
        is_default=False,
    )

    other_space = Space(id=uuid4(), name="Other", created_by_id=outsider.id)
    other_team = Team(
        id=uuid4(),
        space_id=other_space.id,
        name="Private",
        created_by_id=outsider.id,
    )
    other_board = IssueBoard(
        id=uuid4(),
        team_id=other_team.id,
        name="Private issues",
        key="EXT",
        created_by_id=outsider.id,
        next_task_number=2,
    )
    other_column = BoardColumn(
        id=uuid4(),
        board_id=other_board.id,
        name="Todo",
        position=0,
        system_status=IssueStatus.TODO,
        is_default=True,
    )

    base_time = datetime(2030, 1, 1, tzinfo=UTC)
    tasks = [
        _new_task(
            board=board,
            column=default_column,
            creator=owner,
            number=index + 1,
            title=f"Visible task {index + 1}",
            updated_at=base_time + timedelta(minutes=index),
        )
        for index in range(3)
    ]
    other_task = _new_task(
        board=other_board,
        column=other_column,
        creator=outsider,
        number=1,
        title="Private task",
        updated_at=base_time - timedelta(days=1),
    )

    db.add_all(
        [
            owner,
            member,
            outsider,
            space,
            SpaceMember(space_id=space.id, user_id=owner.id, role="owner"),
            SpaceMember(space_id=space.id, user_id=member.id, role="member"),
            team,
            TeamMember(team_id=team.id, user_id=owner.id, role="owner"),
            TeamMember(team_id=team.id, user_id=member.id, role="member"),
            board,
            default_column,
            done_column,
            *tasks,
            other_space,
            SpaceMember(space_id=other_space.id, user_id=outsider.id, role="owner"),
            other_team,
            TeamMember(team_id=other_team.id, user_id=outsider.id, role="owner"),
            other_board,
            other_column,
            other_task,
        ]
    )
    await db.commit()
    return PublicApiScenario(
        owner=owner,
        member=member,
        outsider=outsider,
        space=space,
        team=team,
        board=board,
        default_column=default_column,
        done_column=done_column,
        tasks=tasks,
        other_task=other_task,
    )


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
async def api_client(
    db: AsyncSession,
    fake_redis: FakeRedis,
) -> AsyncIterator[AsyncClient]:
    async def override_db() -> AsyncIterator[AsyncSession]:
        yield db

    def override_redis() -> FakeRedis:
        return fake_redis

    overrides = {
        get_db: override_db,
        get_redis: override_redis,
    }
    previous = {dependency: app.dependency_overrides.get(dependency) for dependency in overrides}
    app.dependency_overrides.update(overrides)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            yield client
    finally:
        for dependency, old_override in previous.items():
            if old_override is None:
                app.dependency_overrides.pop(dependency, None)
            else:
                app.dependency_overrides[dependency] = old_override


async def issue_pat(
    db: AsyncSession,
    user: User,
    *,
    scopes: str = "read",
    expires_at: datetime | None = None,
    revoked_at: datetime | None = None,
) -> tuple[str, ApiToken]:
    raw_token, token_hash, token_prefix = generate_api_token()
    now = datetime.now(UTC)
    token = ApiToken(
        id=uuid4(),
        user_id=user.id,
        name="Integration token",
        token_hash=token_hash,
        token_prefix=token_prefix,
        scopes=scopes,
        auth_version=user.auth_version,
        expires_at=expires_at or now + timedelta(days=30),
        revoked_at=revoked_at,
        created_at=now,
    )
    db.add(token)
    await db.commit()
    return raw_token, token


def bearer_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def nested_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(nested_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(nested_keys(item) for item in value))
    return set()


async def test_pat_create_list_and_revoke_is_one_time_and_hashed(
    db: AsyncSession,
    scenario: PublicApiScenario,
    api_client: AsyncClient,
) -> None:
    _, stale_revoked = await issue_pat(
        db,
        scenario.owner,
        revoked_at=datetime.now(UTC),
    )
    _, stale_expired = await issue_pat(
        db,
        scenario.owner,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    _, stale_auth_version = await issue_pat(db, scenario.owner)
    stale_auth_version.auth_version = scenario.owner.auth_version + 1
    await db.commit()

    created = await create_api_token(
        ApiTokenCreate(name="  Bitrix   integration  ", scopes=["write"], expires_in_days=30),
        scenario.owner,
        db,
        None,
    )

    assert created.name == "Bitrix integration"
    assert created.scopes == ["read", "write"]
    assert is_api_token(created.token)
    stored = await db.get(ApiToken, created.id)
    assert stored is not None
    assert stored.token_hash == hash_api_token(created.token)
    assert stored.token_hash != created.token
    assert stored.token_prefix == created.prefix
    for stale_token in (stale_revoked, stale_expired, stale_auth_version):
        assert await db.get(ApiToken, stale_token.id) is None

    listed = await list_api_tokens(scenario.owner, db)
    assert [token.id for token in listed] == [created.id]
    assert "token" not in listed[0].model_dump()
    assert created.token not in str(listed[0].model_dump())

    revoked = await revoke_api_token(created.id, scenario.owner, db, None)
    assert revoked.message == "API token revoked"
    assert await db.get(ApiToken, created.id) is None
    assert await list_api_tokens(scenario.owner, db) == []

    response = await api_client.get(
        f"{PUBLIC_API_PREFIX}/me",
        headers=bearer_headers(created.token),
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


async def test_token_owner_cannot_revoke_another_users_pat(
    db: AsyncSession,
    scenario: PublicApiScenario,
) -> None:
    _, outsider_token = await issue_pat(db, scenario.outsider)

    with pytest.raises(HTTPException) as captured:
        await revoke_api_token(outsider_token.id, scenario.owner, db, None)

    assert captured.value.status_code == 404
    await db.refresh(outsider_token)
    assert outsider_token.revoked_at is None


async def test_web_api_token_lifecycle_requires_session_and_csrf(
    db: AsyncSession,
    scenario: PublicApiScenario,
    api_client: AsyncClient,
) -> None:
    access_token = create_access_token(
        scenario.owner.id,
        auth_version=scenario.owner.auth_version,
    )
    csrf_token = uuid4().hex
    cookie_header = (
        f"{settings.access_cookie_name}={access_token}; {settings.csrf_cookie_name}={csrf_token}"
    )

    created = await api_client.post(
        f"{settings.api_v1_prefix}/api-tokens",
        headers={"Cookie": cookie_header, "X-CSRF-Token": csrf_token},
        json={
            "name": "Telegram integration",
            "scopes": ["write"],
            "expires_in_days": 30,
        },
    )
    assert created.status_code == 201
    created_payload = created.json()
    raw_token = created_payload["token"]
    token_id = created_payload["id"]
    assert is_api_token(raw_token)

    listed = await api_client.get(
        f"{settings.api_v1_prefix}/api-tokens",
        headers={"Cookie": cookie_header},
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [token_id]
    assert all("token" not in item for item in listed.json())
    assert raw_token not in listed.text

    revoked = await api_client.delete(
        f"{settings.api_v1_prefix}/api-tokens/{token_id}",
        headers={"Cookie": cookie_header, "X-CSRF-Token": csrf_token},
    )
    assert revoked.status_code == 200
    assert await db.get(ApiToken, UUID(token_id)) is None

    rejected = await api_client.get(
        f"{PUBLIC_API_PREFIX}/me",
        headers=bearer_headers(raw_token),
    )
    assert rejected.status_code == 401


async def test_valid_pat_can_read_and_write_without_csrf_and_secrets_do_not_leak(
    db: AsyncSession,
    scenario: PublicApiScenario,
    api_client: AsyncClient,
) -> None:
    raw_token, _ = await issue_pat(db, scenario.owner, scopes="read,write")

    me_response = await api_client.get(
        f"{PUBLIC_API_PREFIX}/me",
        headers=bearer_headers(raw_token),
    )
    assert me_response.status_code == 200
    assert me_response.json()["id"] == str(scenario.owner.id)

    create_response = await api_client.post(
        f"{PUBLIC_API_PREFIX}/tasks",
        headers=bearer_headers(raw_token),
        json={
            "board_id": str(scenario.board.id),
            "title": "Created through API",
            "description": "No CSRF header is required",
        },
    )
    assert create_response.status_code == 201
    payload = create_response.json()
    assert payload["title"] == "Created through API"
    assert payload["code"] == "DEV-4"
    assert payload["created_by"]["id"] == str(scenario.owner.id)

    stored = await db.get(Task, UUID(payload["id"]))
    assert stored is not None
    assert stored.title_ciphertext != b"Created through API"
    assert stored.description_ciphertext != b"No CSRF header is required"
    assert raw_token not in create_response.text
    assert {
        "title_ciphertext",
        "title_nonce",
        "title_tag",
        "description_ciphertext",
        "description_nonce",
        "description_tag",
        "encryption_key_version",
        "token_hash",
    }.isdisjoint(nested_keys(payload))


async def test_read_scope_cannot_write(
    db: AsyncSession,
    scenario: PublicApiScenario,
    api_client: AsyncClient,
) -> None:
    raw_token, _ = await issue_pat(db, scenario.owner, scopes="read")
    before = int(
        await db.scalar(select(func.count(Task.id)).where(Task.board_id == scenario.board.id)) or 0
    )

    response = await api_client.post(
        f"{PUBLIC_API_PREFIX}/tasks",
        headers=bearer_headers(raw_token),
        json={"board_id": str(scenario.board.id), "title": "Must not be created"},
    )

    assert response.status_code == 403
    assert response.json()["error"] == {
        "code": "forbidden",
        "message": "API token requires the 'write' scope",
        "request_id": response.headers["X-Request-ID"],
    }
    after = int(
        await db.scalar(select(func.count(Task.id)).where(Task.board_id == scenario.board.id)) or 0
    )
    assert after == before


async def test_public_pat_and_web_cookie_authentication_remain_isolated(
    db: AsyncSession,
    scenario: PublicApiScenario,
    api_client: AsyncClient,
) -> None:
    raw_pat, _ = await issue_pat(db, scenario.owner)
    pat_on_web = await api_client.get(
        f"{settings.api_v1_prefix}/users/me",
        headers=bearer_headers(raw_pat),
    )
    assert pat_on_web.status_code == 401

    access_token = create_access_token(
        scenario.owner.id,
        auth_version=scenario.owner.auth_version,
    )
    cookie = f"{settings.access_cookie_name}={access_token}"
    token_payload = {"name": "Must not be created", "expires_in_days": 30}

    cookie_without_csrf = await api_client.post(
        f"{settings.api_v1_prefix}/api-tokens",
        headers={"Cookie": cookie},
        json=token_payload,
    )
    assert cookie_without_csrf.status_code == 403

    junk_authorization_with_cookie = await api_client.post(
        f"{settings.api_v1_prefix}/api-tokens",
        headers={
            "Cookie": cookie,
            "Authorization": "Bearer definitely-not-a-valid-token",
        },
        json=token_payload,
    )
    assert junk_authorization_with_cookie.status_code == 401

    stored_count = int(
        await db.scalar(
            select(func.count(ApiToken.id)).where(ApiToken.user_id == scenario.owner.id)
        )
        or 0
    )
    assert stored_count == 1


@pytest.mark.parametrize(
    "credential_case",
    [
        "missing",
        "jwt",
        "unknown",
        "revoked",
        "expired",
        "inactive",
        "auth_version",
        "cookie",
    ],
)
async def test_public_auth_rejects_non_pat_credentials_and_unusable_tokens(
    credential_case: str,
    db: AsyncSession,
    scenario: PublicApiScenario,
    api_client: AsyncClient,
) -> None:
    headers: dict[str, str] = {}
    exposed_credential = ""

    if credential_case == "jwt":
        exposed_credential = create_access_token(
            scenario.owner.id,
            auth_version=scenario.owner.auth_version,
        )
        headers = bearer_headers(exposed_credential)
    elif credential_case == "unknown":
        exposed_credential, _, _ = generate_api_token()
        headers = bearer_headers(exposed_credential)
    elif credential_case == "revoked":
        exposed_credential, _ = await issue_pat(
            db,
            scenario.owner,
            revoked_at=datetime.now(UTC),
        )
        headers = bearer_headers(exposed_credential)
    elif credential_case == "expired":
        exposed_credential, _ = await issue_pat(
            db,
            scenario.owner,
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        headers = bearer_headers(exposed_credential)
    elif credential_case == "inactive":
        exposed_credential, _ = await issue_pat(db, scenario.owner)
        scenario.owner.is_active = False
        await db.commit()
        headers = bearer_headers(exposed_credential)
    elif credential_case == "auth_version":
        exposed_credential, _ = await issue_pat(db, scenario.owner)
        scenario.owner.auth_version += 1
        await db.commit()
        headers = bearer_headers(exposed_credential)
    elif credential_case == "cookie":
        exposed_credential = create_access_token(
            scenario.owner.id,
            auth_version=scenario.owner.auth_version,
        )
        headers = {"Cookie": f"{settings.access_cookie_name}={exposed_credential}"}

    response = await api_client.get(f"{PUBLIC_API_PREFIX}/me", headers=headers)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "invalid_token"
    if exposed_credential:
        assert exposed_credential not in response.text


async def test_task_pagination_enforces_rbac_and_does_not_expose_encrypted_columns(
    db: AsyncSession,
    scenario: PublicApiScenario,
    api_client: AsyncClient,
) -> None:
    raw_token, _ = await issue_pat(db, scenario.owner)
    headers = bearer_headers(raw_token)

    response = await api_client.get(
        f"{PUBLIC_API_PREFIX}/tasks",
        headers=headers,
        params={"limit": 1, "offset": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 3
    assert payload["limit"] == 1
    assert payload["offset"] == 1
    assert [item["id"] for item in payload["items"]] == [str(scenario.tasks[1].id)]
    assert {
        "title_ciphertext",
        "title_nonce",
        "title_tag",
        "description_ciphertext",
        "description_nonce",
        "description_tag",
        "encryption_key_version",
    }.isdisjoint(nested_keys(payload))

    updated_after = scenario.tasks[0].updated_at + timedelta(seconds=30)
    filtered = await api_client.get(
        f"{PUBLIC_API_PREFIX}/tasks",
        headers=headers,
        params={"updated_after": updated_after.isoformat()},
    )
    assert filtered.status_code == 200
    filtered_payload = filtered.json()
    assert filtered_payload["total"] == 2
    assert [item["id"] for item in filtered_payload["items"]] == [
        str(scenario.tasks[1].id),
        str(scenario.tasks[2].id),
    ]

    cursor_page = await api_client.get(
        f"{PUBLIC_API_PREFIX}/tasks",
        headers=headers,
        params={
            "updated_after": scenario.tasks[1].updated_at.isoformat(),
            "updated_after_id": str(scenario.tasks[1].id),
        },
    )
    assert cursor_page.status_code == 200
    assert [item["id"] for item in cursor_page.json()["items"]] == [str(scenario.tasks[2].id)]

    invalid_cursor = await api_client.get(
        f"{PUBLIC_API_PREFIX}/tasks",
        headers=headers,
        params={"updated_after_id": str(scenario.tasks[0].id)},
    )
    assert invalid_cursor.status_code == 422
    assert invalid_cursor.json()["error"]["code"] == "validation_error"

    inaccessible = await api_client.get(
        f"{PUBLIC_API_PREFIX}/tasks/{scenario.other_task.id}",
        headers=headers,
    )
    assert inaccessible.status_code == 404
    assert inaccessible.json()["error"]["code"] == "not_found"

    invalid_page = await api_client.get(
        f"{PUBLIC_API_PREFIX}/tasks",
        headers=headers,
        params={"limit": 101},
    )
    assert invalid_page.status_code == 422
    assert invalid_page.json()["error"]["code"] == "validation_error"


async def test_structure_and_task_endpoints_return_accessible_resources(
    db: AsyncSession,
    scenario: PublicApiScenario,
    api_client: AsyncClient,
) -> None:
    raw_token, _ = await issue_pat(db, scenario.owner, scopes="read,write")
    headers = bearer_headers(raw_token)

    spaces = await api_client.get(f"{PUBLIC_API_PREFIX}/spaces", headers=headers)
    assert spaces.status_code == 200
    assert [item["id"] for item in spaces.json()] == [str(scenario.space.id)]

    teams = await api_client.get(
        f"{PUBLIC_API_PREFIX}/spaces/{scenario.space.id}/teams",
        headers=headers,
    )
    assert teams.status_code == 200
    assert [item["id"] for item in teams.json()] == [str(scenario.team.id)]

    members = await api_client.get(
        f"{PUBLIC_API_PREFIX}/teams/{scenario.team.id}/members",
        headers=headers,
    )
    assert members.status_code == 200
    assert {item["user_id"] for item in members.json()["members"]} == {
        str(scenario.owner.id),
        str(scenario.member.id),
    }

    boards = await api_client.get(
        f"{PUBLIC_API_PREFIX}/teams/{scenario.team.id}/boards",
        headers=headers,
    )
    assert boards.status_code == 200
    assert [item["id"] for item in boards.json()] == [str(scenario.board.id)]

    board = await api_client.get(
        f"{PUBLIC_API_PREFIX}/boards/{scenario.board.id}",
        headers=headers,
    )
    assert board.status_code == 200
    assert board.json()["id"] == str(scenario.board.id)
    assert [item["id"] for item in board.json()["columns"]] == [
        str(scenario.default_column.id),
        str(scenario.done_column.id),
    ]

    task = scenario.tasks[0]
    fetched = await api_client.get(
        f"{PUBLIC_API_PREFIX}/tasks/{task.id}",
        headers=headers,
    )
    assert fetched.status_code == 200
    assert fetched.json()["id"] == str(task.id)

    updated = await api_client.patch(
        f"{PUBLIC_API_PREFIX}/tasks/{task.id}",
        headers=headers,
        json={"title": "Updated through public API", "deadline": None},
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "Updated through public API"
    assert updated.json()["deadline"] is None


async def test_status_wrapper_updates_an_accessible_task(
    db: AsyncSession,
    scenario: PublicApiScenario,
    api_client: AsyncClient,
) -> None:
    raw_token, _ = await issue_pat(db, scenario.owner, scopes="read,write")

    response = await api_client.patch(
        f"{PUBLIC_API_PREFIX}/tasks/{scenario.tasks[0].id}/status",
        headers=bearer_headers(raw_token),
        json={"status": "done"},
    )

    assert response.status_code == 200
    assert response.json()["status_id"] == str(scenario.done_column.id)
    await db.refresh(scenario.tasks[0])
    assert scenario.tasks[0].status_id == scenario.done_column.id


async def test_comment_wrappers_encrypt_storage_and_paginate_without_cipher_leaks(
    db: AsyncSession,
    scenario: PublicApiScenario,
    api_client: AsyncClient,
) -> None:
    raw_token, _ = await issue_pat(db, scenario.owner, scopes="read,write")
    headers = bearer_headers(raw_token)
    bodies = ["First integration comment", "Second integration comment"]
    created_ids: list[UUID] = []

    for body in bodies:
        created = await api_client.post(
            f"{PUBLIC_API_PREFIX}/tasks/{scenario.tasks[0].id}/comments",
            headers=headers,
            json={"body": body},
        )
        assert created.status_code == 201
        created_payload = created.json()
        assert created_payload["body"] == body
        assert {
            "body_ciphertext",
            "body_nonce",
            "body_tag",
            "encryption_key_version",
        }.isdisjoint(nested_keys(created_payload))
        created_ids.append(UUID(created_payload["id"]))

    stored_comments = list(
        await db.scalars(
            select(Comment).where(Comment.id.in_(created_ids)).order_by(Comment.created_at)
        )
    )
    assert [content_encryption.get_comment_body(comment) for comment in stored_comments] == bodies
    assert all(
        comment.body_ciphertext != body.encode()
        for comment, body in zip(stored_comments, bodies, strict=True)
    )

    listed = await api_client.get(
        f"{PUBLIC_API_PREFIX}/tasks/{scenario.tasks[0].id}/comments",
        headers=headers,
        params={"limit": 1, "offset": 1},
    )
    assert listed.status_code == 200
    listed_payload = listed.json()
    assert listed_payload["total"] == 2
    assert listed_payload["limit"] == 1
    assert listed_payload["offset"] == 1
    assert [item["body"] for item in listed_payload["items"]] == [bodies[1]]
    assert {
        "body_ciphertext",
        "body_nonce",
        "body_tag",
        "encryption_key_version",
    }.isdisjoint(nested_keys(listed_payload))


async def test_member_pat_obeys_task_rbac_but_can_claim_and_move_own_task(
    db: AsyncSession,
    scenario: PublicApiScenario,
    api_client: AsyncClient,
) -> None:
    raw_token, _ = await issue_pat(db, scenario.member, scopes="read,write")
    headers = bearer_headers(raw_token)
    task = scenario.tasks[0]

    create_response = await api_client.post(
        f"{PUBLIC_API_PREFIX}/tasks",
        headers=headers,
        json={"board_id": str(scenario.board.id), "title": "Member task"},
    )
    assert create_response.status_code == 201

    generic_patch = await api_client.patch(
        f"{PUBLIC_API_PREFIX}/tasks/{task.id}",
        headers=headers,
        json={"title": "Forbidden member edit"},
    )
    assert generic_patch.status_code == 403

    claimed = await api_client.post(
        f"{PUBLIC_API_PREFIX}/tasks/{task.id}/claim",
        headers=headers,
    )
    assert claimed.status_code == 200
    assert claimed.json()["assignee"]["id"] == str(scenario.member.id)

    moved = await api_client.patch(
        f"{PUBLIC_API_PREFIX}/tasks/{task.id}/status",
        headers=headers,
        json={"status": "done"},
    )
    assert moved.status_code == 200
    assert moved.json()["status_id"] == str(scenario.done_column.id)
    await db.refresh(task)
    assert task.assignee_id == scenario.member.id
    assert task.status_id == scenario.done_column.id


async def test_last_used_at_is_written_once_inside_the_five_minute_window(
    db: AsyncSession,
    scenario: PublicApiScenario,
    api_client: AsyncClient,
) -> None:
    raw_token, token = await issue_pat(db, scenario.owner)
    headers = bearer_headers(raw_token)
    assert token.last_used_at is None

    first_response = await api_client.get(f"{PUBLIC_API_PREFIX}/me", headers=headers)
    assert first_response.status_code == 200
    await db.refresh(token)
    first_used_at = token.last_used_at
    assert first_used_at is not None

    second_response = await api_client.get(f"{PUBLIC_API_PREFIX}/me", headers=headers)
    assert second_response.status_code == 200
    await db.refresh(token)
    assert token.last_used_at == first_used_at


async def test_public_api_method_not_allowed_uses_public_error_envelope(
    api_client: AsyncClient,
) -> None:
    response = await api_client.delete(f"{PUBLIC_API_PREFIX}/tasks/{uuid4()}")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


async def test_public_api_rate_limit_returns_retry_after(
    fake_redis: FakeRedis,
    api_client: AsyncClient,
) -> None:
    retry_after = 17
    fake_redis.results.append([settings.public_api_ip_rate_limit_requests + 1, retry_after])

    response = await api_client.get(f"{PUBLIC_API_PREFIX}/me")

    assert response.status_code == 429
    assert response.headers["Retry-After"] == str(retry_after)
    assert response.json()["error"]["code"] == "rate_limit_exceeded"


async def test_public_api_oversized_body_uses_public_error_envelope(
    api_client: AsyncClient,
) -> None:
    response = await api_client.post(
        f"{PUBLIC_API_PREFIX}/tasks",
        content=b"x" * (SMALL_REQUEST_BODY_BYTES + 1),
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


async def test_public_api_unhandled_error_uses_public_error_envelope() -> None:
    async def raise_unhandled_error() -> None:
        raise RuntimeError("private database error")

    previous = app.dependency_overrides.get(get_api_principal)
    app.dependency_overrides[get_api_principal] = raise_unhandled_error
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://testserver",
        ) as client:
            response = await client.get(
                f"{PUBLIC_API_PREFIX}/me",
                headers={"X-Request-ID": "public-error-test"},
            )
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_api_principal, None)
        else:
            app.dependency_overrides[get_api_principal] = previous

    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "public-error-test"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json() == {
        "error": {
            "code": "internal_error",
            "message": "Internal server error",
            "request_id": "public-error-test",
        }
    }
    assert "private database error" not in response.text


async def test_public_openapi_contains_only_public_bearer_contract(
    api_client: AsyncClient,
) -> None:
    info_response = await api_client.get(PUBLIC_API_PREFIX)
    assert info_response.status_code == 200
    assert info_response.json() == {
        "name": "Noki Public API",
        "version": "1.0.0",
        "openapi_url": f"{PUBLIC_API_PREFIX}/openapi.json",
    }

    response = await api_client.get(f"{PUBLIC_API_PREFIX}/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    paths = schema["paths"]
    expected_methods = {
        f"{PUBLIC_API_PREFIX}/me": {"get"},
        f"{PUBLIC_API_PREFIX}/spaces": {"get"},
        f"{PUBLIC_API_PREFIX}/spaces/{{space_id}}/teams": {"get"},
        f"{PUBLIC_API_PREFIX}/teams/{{team_id}}/members": {"get"},
        f"{PUBLIC_API_PREFIX}/teams/{{team_id}}/boards": {"get"},
        f"{PUBLIC_API_PREFIX}/boards/{{board_id}}": {"get"},
        f"{PUBLIC_API_PREFIX}/tasks": {"get", "post"},
        f"{PUBLIC_API_PREFIX}/tasks/{{task_id}}": {"get", "patch"},
        f"{PUBLIC_API_PREFIX}/tasks/{{task_id}}/status": {"patch"},
        f"{PUBLIC_API_PREFIX}/tasks/{{task_id}}/claim": {"post"},
        f"{PUBLIC_API_PREFIX}/tasks/{{task_id}}/comments": {"get", "post"},
        f"{PUBLIC_API_PREFIX}/todos": {"get", "post"},
        f"{PUBLIC_API_PREFIX}/todos/{{todo_id}}": {"get", "patch", "delete"},
        f"{PUBLIC_API_PREFIX}/api-tokens": {"get", "post"},
        f"{PUBLIC_API_PREFIX}/api-tokens/{{token_id}}": {"delete"},
    }
    assert {path: set(operations) for path, operations in paths.items()} == expected_methods
    assert f"{settings.api_v1_prefix}/auth/login" not in paths
    assert f"{settings.api_v1_prefix}/api-tokens" not in paths
    assert f"{PUBLIC_API_PREFIX}/openapi.json" not in paths

    security_scheme = schema["components"]["securitySchemes"]["NokiApiToken"]
    assert security_scheme["type"] == "http"
    assert security_scheme["scheme"] == "bearer"
    assert security_scheme["bearerFormat"] == "noki_pat_..."

    operation_ids: list[str] = []
    for operations in paths.values():
        for operation in operations.values():
            operation_ids.append(operation["operationId"])
            assert operation["security"] == [{"NokiApiToken": []}]
    assert len(operation_ids) == len(set(operation_ids))

    serialized_schema = response.text
    assert "token_hash" not in serialized_schema
    assert '"ApiTokenCreated"' not in serialized_schema


async def test_public_api_token_lifecycle_via_public_endpoints(
    db: AsyncSession,
    scenario: PublicApiScenario,
    api_client: AsyncClient,
) -> None:
    raw_token, existing_pat = await issue_pat(db, scenario.owner, scopes="read,write")
    headers = bearer_headers(raw_token)

    listed = await api_client.get(
        f"{PUBLIC_API_PREFIX}/api-tokens",
        headers=headers,
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [str(existing_pat.id)]

    created = await api_client.post(
        f"{PUBLIC_API_PREFIX}/api-tokens",
        headers=headers,
        json={
            "name": "  Public API token  ",
            "scopes": ["write"],
            "expires_in_days": 30,
        },
    )
    assert created.status_code == 201
    created_payload = created.json()
    assert created_payload["name"] == "Public API token"
    assert created_payload["scopes"] == ["read", "write"]
    assert is_api_token(created_payload["token"])
    token_id = created_payload["id"]

    listed_after = await api_client.get(
        f"{PUBLIC_API_PREFIX}/api-tokens",
        headers=headers,
    )
    assert listed_after.status_code == 200
    assert [item["id"] for item in listed_after.json()] == [token_id, str(existing_pat.id)]
    assert "token" not in listed_after.json()[0]
    assert created_payload["token"] not in listed_after.text

    me_after = await api_client.get(
        f"{PUBLIC_API_PREFIX}/me",
        headers=headers,
    )
    assert me_after.status_code == 200

    new_token_headers = bearer_headers(created_payload["token"])
    me_new = await api_client.get(
        f"{PUBLIC_API_PREFIX}/me",
        headers=new_token_headers,
    )
    assert me_new.status_code == 200

    revoked = await api_client.delete(
        f"{PUBLIC_API_PREFIX}/api-tokens/{token_id}",
        headers=headers,
    )
    assert revoked.status_code == 200
    assert revoked.json()["message"] == "API token revoked"

    rejected = await api_client.get(
        f"{PUBLIC_API_PREFIX}/me",
        headers=new_token_headers,
    )
    assert rejected.status_code == 401
    assert rejected.json()["error"]["code"] == "invalid_token"


async def test_public_api_token_management_respects_scope_and_isolation(
    db: AsyncSession,
    scenario: PublicApiScenario,
    api_client: AsyncClient,
) -> None:
    raw_read_token, _ = await issue_pat(db, scenario.owner, scopes="read")
    read_headers = bearer_headers(raw_read_token)

    read_list = await api_client.get(
        f"{PUBLIC_API_PREFIX}/api-tokens",
        headers=read_headers,
    )
    assert read_list.status_code == 200

    read_create = await api_client.post(
        f"{PUBLIC_API_PREFIX}/api-tokens",
        headers=read_headers,
        json={"name": "Read scope create", "scopes": ["read"], "expires_in_days": 30},
    )
    assert read_create.status_code == 403

    raw_owner_token, owner_token = await issue_pat(db, scenario.owner, scopes="read,write")
    raw_member_token, member_token = await issue_pat(db, scenario.member, scopes="read,write")

    member_list = await api_client.get(
        f"{PUBLIC_API_PREFIX}/api-tokens",
        headers=bearer_headers(raw_member_token),
    )
    assert member_list.status_code == 200
    assert [item["id"] for item in member_list.json()] == [str(member_token.id)]

    member_revoke = await api_client.delete(
        f"{PUBLIC_API_PREFIX}/api-tokens/{owner_token.id}",
        headers=bearer_headers(raw_member_token),
    )
    assert member_revoke.status_code == 404

    await db.refresh(owner_token)
    assert owner_token.revoked_at is None


async def test_todo_crud_and_completed_by_tracking(
    db: AsyncSession,
    scenario: PublicApiScenario,
    api_client: AsyncClient,
) -> None:
    raw_token, _ = await issue_pat(db, scenario.owner, scopes="read,write")
    headers = bearer_headers(raw_token)

    created = await api_client.post(
        f"{PUBLIC_API_PREFIX}/todos",
        headers=headers,
        json={
            "title": "Public API todo",
            "description": "Track completion",
            "status": "todo",
            "position": 0,
        },
    )
    assert created.status_code == 201
    todo_id = created.json()["id"]
    assert created.json()["title"] == "Public API todo"
    assert created.json()["status"] == "todo"
    assert created.json()["completed_by"] is None

    fetched = await api_client.get(
        f"{PUBLIC_API_PREFIX}/todos/{todo_id}",
        headers=headers,
    )
    assert fetched.status_code == 200
    assert fetched.json()["id"] == todo_id
    assert fetched.json()["completed_by"] is None

    listed = await api_client.get(
        f"{PUBLIC_API_PREFIX}/todos",
        headers=headers,
    )
    assert listed.status_code == 200
    assert any(item["id"] == todo_id for item in listed.json())

    updated = await api_client.patch(
        f"{PUBLIC_API_PREFIX}/todos/{todo_id}",
        headers=headers,
        json={"status": "done"},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "done"
    assert updated.json()["completed_by"]["id"] == str(scenario.owner.id)
    assert updated.json()["completed_by"]["name"] == scenario.owner.name

    reopened = await api_client.patch(
        f"{PUBLIC_API_PREFIX}/todos/{todo_id}",
        headers=headers,
        json={"status": "todo"},
    )
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "todo"
    assert reopened.json()["completed_by"] is None

    deleted = await api_client.delete(
        f"{PUBLIC_API_PREFIX}/todos/{todo_id}",
        headers=headers,
    )
    assert deleted.status_code == 200
    assert deleted.json()["message"] == "Todo deleted"

    missing = await api_client.get(
        f"{PUBLIC_API_PREFIX}/todos/{todo_id}",
        headers=headers,
    )
    assert missing.status_code == 404


async def test_todo_endpoints_are_isolated_per_user(
    db: AsyncSession,
    scenario: PublicApiScenario,
    api_client: AsyncClient,
) -> None:
    owner_token, _ = await issue_pat(db, scenario.owner, scopes="read,write")
    member_token, _ = await issue_pat(db, scenario.member, scopes="read,write")

    owner_todo = await api_client.post(
        f"{PUBLIC_API_PREFIX}/todos",
        headers=bearer_headers(owner_token),
        json={"title": "Owner todo", "status": "todo"},
    )
    assert owner_todo.status_code == 201
    owner_todo_id = owner_todo.json()["id"]

    member_todo = await api_client.post(
        f"{PUBLIC_API_PREFIX}/todos",
        headers=bearer_headers(member_token),
        json={"title": "Member todo", "status": "todo"},
    )
    assert member_todo.status_code == 201
    member_todo_id = member_todo.json()["id"]

    member_sees_own = await api_client.get(
        f"{PUBLIC_API_PREFIX}/todos/{member_todo_id}",
        headers=bearer_headers(member_token),
    )
    assert member_sees_own.status_code == 200

    member_cannot_see_owner = await api_client.get(
        f"{PUBLIC_API_PREFIX}/todos/{owner_todo_id}",
        headers=bearer_headers(member_token),
    )
    assert member_cannot_see_owner.status_code == 404

    owner_cannot_see_member = await api_client.get(
        f"{PUBLIC_API_PREFIX}/todos/{member_todo_id}",
        headers=bearer_headers(owner_token),
    )
    assert owner_cannot_see_member.status_code == 404

    member_list = await api_client.get(
        f"{PUBLIC_API_PREFIX}/todos",
        headers=bearer_headers(member_token),
    )
    assert member_list.status_code == 200
    assert all(item["id"] != owner_todo_id for item in member_list.json())
