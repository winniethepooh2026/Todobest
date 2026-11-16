# ruff: noqa: S608
# Test schema names are generated exclusively from UUID hex values.

from __future__ import annotations

import base64
import os
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.schema import CreateSchema, DropSchema

from app.api.deps import get_current_user, verify_csrf
from app.core.encryption import DataCipher
from app.db.session import get_db
from app.main import app
from app.models import (
    Base,
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
)
from app.services import content_encryption

POSTGRES_TEST_URL = os.getenv("NOKI_TEST_DATABASE_URL", "")
TEST_KEY = base64.urlsafe_b64encode(bytes(range(32))).decode()
WRONG_TEST_KEY = base64.urlsafe_b64encode(bytes(reversed(range(32)))).decode()

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        not POSTGRES_TEST_URL.startswith("postgresql+asyncpg://"),
        reason="NOKI_TEST_DATABASE_URL must point to a dedicated PostgreSQL database",
    ),
]


async def api_request(
    db: AsyncSession,
    user: User,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> Response:
    async def override_db() -> AsyncIterator[AsyncSession]:
        yield db

    async def override_user() -> User:
        return user

    async def override_csrf() -> None:
        return None

    dependencies = {
        get_db: override_db,
        get_current_user: override_user,
        verify_csrf: override_csrf,
    }
    previous = {dependency: app.dependency_overrides.get(dependency) for dependency in dependencies}
    app.dependency_overrides.update(dependencies)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://noki.test",
        ) as client:
            return await client.request(method, path, json=payload)
    finally:
        for dependency, old_override in previous.items():
            if old_override is None:
                app.dependency_overrides.pop(dependency, None)
            else:
                app.dependency_overrides[dependency] = old_override


@pytest.fixture
async def postgres_db(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[AsyncSession, str, AsyncEngine]]:
    schema = f"noki_test_{uuid4().hex}"
    engine = create_async_engine(
        POSTGRES_TEST_URL,
        execution_options={"schema_translate_map": {None: schema}},
    )
    monkeypatch.setattr(
        content_encryption,
        "get_data_cipher",
        lambda: DataCipher(TEST_KEY),
    )

    schema_created = False
    try:
        try:
            async with engine.begin() as connection:
                await connection.execute(CreateSchema(schema))
                await connection.run_sync(Base.metadata.create_all)
        except Exception as exc:
            raise RuntimeError(
                "Dedicated PostgreSQL encryption test database is unavailable "
                f"or cannot create an isolated schema ({type(exc).__name__})"
            ) from None
        schema_created = True

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            yield session, schema, engine
    finally:
        try:
            if schema_created:
                try:
                    async with engine.begin() as connection:
                        await connection.execute(DropSchema(schema, cascade=True, if_exists=True))
                except Exception as exc:
                    raise RuntimeError(
                        "Could not remove the isolated PostgreSQL test schema "
                        f"({type(exc).__name__})"
                    ) from None
        finally:
            await engine.dispose()


async def test_private_content_is_ciphertext_in_raw_postgresql(
    postgres_db: tuple[AsyncSession, str, AsyncEngine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, schema, engine = postgres_db
    user_id = uuid4()
    space_id = uuid4()
    team_id = uuid4()
    board_id = uuid4()
    column_id = uuid4()

    page_title = "NOKI_ENCRYPTION_TEST_PAGE_7f28c1"
    page_text = "NOKI_ENCRYPTION_TEST_PAGE_CONTENT_7f28c1"
    issue_title = "NOKI_ENCRYPTION_TEST_ISSUE_9a41d3"
    issue_description = "NOKI_ENCRYPTION_TEST_ISSUE_DESCRIPTION_9a41d3"
    upload_name = "NOKI_ENCRYPTION_TEST_UPLOAD_6d8e2a.png"
    updated_description = "NOKI_ENCRYPTION_TEST_ISSUE_UPDATED_b87e20"
    updated_page_text = "NOKI_ENCRYPTION_TEST_PAGE_UPDATED_c18a72"

    user = User(
        id=user_id,
        email="postgres-encryption@example.com",
        name="Tester",
    )
    db.add_all(
        [
            user,
            Space(id=space_id, name="Encryption", created_by_id=user_id),
            SpaceMember(space_id=space_id, user_id=user_id, role="owner"),
            Team(
                id=team_id,
                space_id=space_id,
                name="Security",
                created_by_id=user_id,
            ),
            TeamMember(team_id=team_id, user_id=user_id, role="owner"),
            IssueBoard(
                id=board_id,
                team_id=team_id,
                name="Issues",
                key="SEC",
                created_by_id=user_id,
            ),
            BoardColumn(
                id=column_id,
                board_id=board_id,
                name="Todo",
                position=0,
                system_status=IssueStatus.TODO,
            ),
        ]
    )
    await db.commit()

    created_task_response = await api_request(
        db,
        user,
        "POST",
        f"/api/v1/boards/{board_id}/tasks",
        {"title": issue_title, "description": issue_description},
    )
    assert created_task_response.status_code == 201
    created_task = created_task_response.json()
    task_id = UUID(created_task["id"])

    created_page_response = await api_request(
        db,
        user,
        "POST",
        f"/api/v1/teams/{team_id}/pages",
        {"title": page_title},
    )
    assert created_page_response.status_code == 201
    created_page = created_page_response.json()
    page_id = UUID(created_page["id"])
    page_document = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": page_text}],
            }
        ],
    }
    page_response = await api_request(
        db,
        user,
        "PATCH",
        f"/api/v1/pages/{page_id}",
        {
            "expected_updated_at": created_page["updated_at"],
            "content": page_document,
            "markdown": page_text,
        },
    )
    assert page_response.status_code == 200
    page_payload = page_response.json()

    upload = Upload(
        id=uuid4(),
        filename=f"{uuid4().hex}.webp",
        content_type="image/webp",
        size_bytes=100,
        width=10,
        height=10,
        owner_id=user_id,
    )
    content_encryption.set_upload_original_name(upload, upload_name)
    db.add(upload)
    await db.commit()

    assert created_task["title"] == issue_title
    assert created_task["description"] == issue_description
    assert created_page["title"] == page_title
    assert page_payload["content"] == page_document
    assert page_payload["markdown"] == page_text

    async with engine.connect() as connection:
        raw_task = (
            (
                await connection.execute(
                    text(
                        f"SELECT title_ciphertext, title_nonce, "
                        f"description_ciphertext, description_nonce "
                        f'FROM "{schema}".tasks WHERE id = :task_id'
                    ),
                    {"task_id": task_id},
                )
            )
            .mappings()
            .one()
        )
        raw_page = (
            (
                await connection.execute(
                    text(
                        f"SELECT title_ciphertext, title_nonce, "
                        f"content_ciphertext, content_nonce, "
                        f"markdown_ciphertext, markdown_nonce "
                        f'FROM "{schema}".pages WHERE id = :page_id'
                    ),
                    {"page_id": page_id},
                )
            )
            .mappings()
            .one()
        )
        raw_upload = (
            await connection.execute(
                text(
                    f'SELECT original_name_ciphertext FROM "{schema}".uploads WHERE id = :upload_id'
                ),
                {"upload_id": upload.id},
            )
        ).scalar_one()
        columns = set(
            (
                await connection.execute(
                    text(
                        """
                        SELECT table_name, column_name
                        FROM information_schema.columns
                        WHERE table_schema = :schema
                          AND table_name IN ('tasks', 'pages', 'uploads')
                        """
                    ),
                    {"schema": schema},
                )
            ).all()
        )

    for plaintext, raw_value in (
        (issue_title, raw_task["title_ciphertext"]),
        (issue_description, raw_task["description_ciphertext"]),
        (page_title, raw_page["title_ciphertext"]),
        (page_text, raw_page["content_ciphertext"]),
        (page_text, raw_page["markdown_ciphertext"]),
        (upload_name, raw_upload),
    ):
        assert plaintext.encode() not in bytes(raw_value)

    assert ("tasks", "title") not in columns
    assert ("tasks", "description") not in columns
    assert ("pages", "title") not in columns
    assert ("pages", "content") not in columns
    assert ("pages", "markdown") not in columns
    assert ("uploads", "original_name") not in columns
    assert content_encryption.get_upload_original_name(upload) == upload_name

    # Re-saving identical plaintext must still rotate nonce/ciphertext in PostgreSQL.
    same_task_response = await api_request(
        db,
        user,
        "PATCH",
        f"/api/v1/tasks/{task_id}",
        {"description": issue_description},
    )
    same_page_response = await api_request(
        db,
        user,
        "PATCH",
        f"/api/v1/pages/{page_id}",
        {
            "expected_updated_at": page_payload["updated_at"],
            "content": page_document,
            "markdown": page_text,
        },
    )
    assert same_task_response.status_code == 200
    assert same_page_response.status_code == 200
    assert same_task_response.json()["description"] == issue_description
    assert same_page_response.json()["content"] == page_document

    async with engine.connect() as connection:
        same_raw_task = (
            (
                await connection.execute(
                    text(
                        f"SELECT description_ciphertext, description_nonce "
                        f'FROM "{schema}".tasks WHERE id = :task_id'
                    ),
                    {"task_id": task_id},
                )
            )
            .mappings()
            .one()
        )
        same_raw_page = (
            (
                await connection.execute(
                    text(
                        f"SELECT content_ciphertext, content_nonce "
                        f'FROM "{schema}".pages WHERE id = :page_id'
                    ),
                    {"page_id": page_id},
                )
            )
            .mappings()
            .one()
        )

    assert bytes(same_raw_task["description_ciphertext"]) != bytes(
        raw_task["description_ciphertext"]
    )
    assert bytes(same_raw_task["description_nonce"]) != bytes(raw_task["description_nonce"])
    assert bytes(same_raw_page["content_ciphertext"]) != bytes(raw_page["content_ciphertext"])
    assert bytes(same_raw_page["content_nonce"]) != bytes(raw_page["content_nonce"])

    updated_document = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": updated_page_text}],
            }
        ],
    }
    updated_task_response = await api_request(
        db,
        user,
        "PATCH",
        f"/api/v1/tasks/{task_id}",
        {"description": updated_description},
    )
    updated_page_response = await api_request(
        db,
        user,
        "PATCH",
        f"/api/v1/pages/{page_id}",
        {
            "expected_updated_at": same_page_response.json()["updated_at"],
            "content": updated_document,
            "markdown": updated_page_text,
        },
    )
    assert updated_task_response.status_code == 200
    assert updated_page_response.status_code == 200
    assert updated_task_response.json()["description"] == updated_description
    assert updated_page_response.json()["content"] == updated_document

    async with engine.connect() as connection:
        updated_raw_task = (
            await connection.execute(
                text(f'SELECT description_ciphertext FROM "{schema}".tasks WHERE id = :task_id'),
                {"task_id": task_id},
            )
        ).scalar_one()
        updated_raw_page = (
            await connection.execute(
                text(
                    f"SELECT content_ciphertext, markdown_ciphertext "
                    f'FROM "{schema}".pages WHERE id = :page_id'
                ),
                {"page_id": page_id},
            )
        ).one()

    assert updated_description.encode() not in bytes(updated_raw_task)
    assert updated_page_text.encode() not in bytes(updated_raw_page[0])
    assert updated_page_text.encode() not in bytes(updated_raw_page[1])

    # A wrong key and corrupted PostgreSQL bytes both fail closed.
    monkeypatch.setattr(
        content_encryption,
        "get_data_cipher",
        lambda: DataCipher(WRONG_TEST_KEY),
    )
    db.expire_all()
    await db.refresh(user)
    wrong_key_response = await api_request(
        db,
        user,
        "GET",
        f"/api/v1/pages/{page_id}",
    )
    assert wrong_key_response.status_code == 500
    assert wrong_key_response.json() == {
        "detail": "Encrypted data is unavailable or failed integrity verification"
    }

    monkeypatch.setattr(
        content_encryption,
        "get_data_cipher",
        lambda: DataCipher(TEST_KEY),
    )
    db.expire_all()
    await db.refresh(user)
    valid_response = await api_request(
        db,
        user,
        "GET",
        f"/api/v1/pages/{page_id}",
    )
    assert valid_response.status_code == 200
    assert valid_response.json()["content"] == updated_document

    async with engine.begin() as connection:
        await connection.execute(
            text(
                f'UPDATE "{schema}".pages '
                "SET title_ciphertext = set_byte("
                "title_ciphertext, 0, mod(get_byte(title_ciphertext, 0) + 1, 256)"
                ") WHERE id = :page_id"
            ),
            {"page_id": page_id},
        )
    db.expire_all()
    await db.refresh(user)
    corrupted_response = await api_request(
        db,
        user,
        "GET",
        f"/api/v1/pages/{page_id}",
    )
    assert corrupted_response.status_code == 500
    assert corrupted_response.json() == {
        "detail": "Encrypted data is unavailable or failed integrity verification"
    }

    stored_task = await db.scalar(select(Task).where(Task.id == task_id))
    stored_page = await db.scalar(select(Page).where(Page.id == page_id))
    assert stored_task is not None
    assert stored_page is not None
