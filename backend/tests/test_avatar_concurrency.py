from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.api.routes import issues as issue_routes
from app.schemas import TaskUpdate
from app.services import avatar_processing, avatars


class _SessionContext:
    def __init__(self, db: object) -> None:
        self.db = db

    async def __aenter__(self) -> object:
        return self.db

    async def __aexit__(self, *_args: object) -> None:
        return None


class _SessionSequence:
    def __init__(self, *sessions: object) -> None:
        self.sessions = list(sessions)

    def __call__(self) -> _SessionContext:
        assert self.sessions, "Avatar importer opened an unexpected database session"
        return _SessionContext(self.sessions.pop(0))


class _AvatarDB:
    def __init__(self, user: object, *, commit_error: Exception | None = None) -> None:
        self.user = user
        self.commit_error = commit_error
        self.commits = 0
        self.rollbacks = 0

    async def get(self, _model: object, _user_id: UUID) -> object:
        return self.user

    async def scalar(self, _statement: object) -> object:
        return self.user

    async def commit(self) -> None:
        self.commits += 1
        if self.commit_error is not None:
            raise self.commit_error

    async def rollback(self) -> None:
        self.rollbacks += 1


def _enable_imports(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        avatars,
        "settings",
        SimpleNamespace(avatar_storage_enabled=True, avatar_refresh_days=7),
    )


def _avatar_user(
    picture_url: str,
    *,
    generation: int,
    content_hash: str = "b" * 64,
) -> SimpleNamespace:
    return SimpleNamespace(
        google_sub="google-subject",
        is_active=True,
        avatar_import_generation=generation,
        avatar_requested_source_hash=avatar_processing.avatar_source_hash(picture_url),
        avatar_source_url_hash="old-source-hash",
        avatar_synced_at=datetime.now(UTC),
        avatar_content_hash=content_hash,
        avatar_object_key=f"avatars/old/{content_hash}.webp",
    )


def _install_processing(
    monkeypatch: pytest.MonkeyPatch,
    processed: SimpleNamespace,
) -> None:
    async def download(_picture_url: str) -> bytes:
        return b"raw-image"

    monkeypatch.setattr(avatars, "download_google_avatar", download)
    monkeypatch.setattr(avatars, "scan_avatar_bytes", lambda _data: None)
    monkeypatch.setattr(avatars, "process_avatar", lambda _data: processed)


def test_missing_google_picture_invalidates_pending_import() -> None:
    user = SimpleNamespace(
        avatar_import_generation=4,
        avatar_requested_source_hash="a" * 64,
        avatar_source_url_hash="b" * 64,
        avatar_synced_at=datetime.now(UTC),
    )

    request = avatars.plan_google_avatar_import(user, None)

    assert request.generation == 5
    assert request.picture_url is None
    assert not request.should_enqueue
    assert user.avatar_import_generation == 5
    assert user.avatar_requested_source_hash is None


def test_fresh_google_picture_still_advances_generation_without_enqueue() -> None:
    picture_url = "https://lh3.googleusercontent.com/avatar"
    source_hash = avatar_processing.avatar_source_hash(picture_url)
    user = SimpleNamespace(
        avatar_import_generation=8,
        avatar_requested_source_hash="a" * 64,
        avatar_source_url_hash=source_hash,
        avatar_synced_at=datetime.now(UTC),
    )

    request = avatars.plan_google_avatar_import(user, picture_url)

    assert request.generation == 9
    assert not request.should_enqueue
    assert user.avatar_import_generation == 9
    assert user.avatar_requested_source_hash == source_hash


@pytest.mark.asyncio
async def test_stale_generation_is_rejected_before_download(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_imports(monkeypatch)
    picture_url = "https://lh3.googleusercontent.com/avatar"
    user = _avatar_user(picture_url, generation=2)
    db = _AvatarDB(user)
    sessions = _SessionSequence(db)
    monkeypatch.setattr(avatars, "async_session_factory", sessions)

    async def unexpected_download(_picture_url: str) -> bytes:
        raise AssertionError("A stale import must not download the source")

    monkeypatch.setattr(avatars, "download_google_avatar", unexpected_download)

    result = await avatars.import_google_avatar(uuid4(), picture_url, generation=1)

    assert result.status == "stale"
    assert not result.uploaded
    assert db.commits == 0
    assert sessions.sessions == []


@pytest.mark.asyncio
async def test_generation_is_rechecked_after_processing_before_put(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_imports(monkeypatch)
    picture_url = "https://lh3.googleusercontent.com/avatar"
    processed = SimpleNamespace(data=b"safe-webp", content_hash="c" * 64)
    _install_processing(monkeypatch, processed)
    current = _avatar_user(picture_url, generation=1)
    superseded = _avatar_user(picture_url, generation=2)
    sessions = _SessionSequence(_AvatarDB(current), _AvatarDB(superseded))
    monkeypatch.setattr(avatars, "async_session_factory", sessions)
    monkeypatch.setattr(
        avatars,
        "store_avatar",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("A superseded import must not perform a paid PUT")
        ),
    )

    result = await avatars.import_google_avatar(uuid4(), picture_url, generation=1)

    assert result.status == "stale"
    assert not result.uploaded
    assert sessions.sessions == []


@pytest.mark.asyncio
async def test_stale_generation_after_put_never_mutates_db_or_deletes_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_imports(monkeypatch)
    picture_url = "https://lh3.googleusercontent.com/avatar"
    processed = SimpleNamespace(data=b"safe-webp", content_hash="c" * 64)
    _install_processing(monkeypatch, processed)
    first = _avatar_user(picture_url, generation=1)
    before_put = _AvatarDB(_avatar_user(picture_url, generation=1))
    superseded = _avatar_user(picture_url, generation=2)
    final_db = _AvatarDB(superseded)
    sessions = _SessionSequence(_AvatarDB(first), before_put, final_db)
    monkeypatch.setattr(avatars, "async_session_factory", sessions)
    new_key = f"avatars/{uuid4().hex}/{processed.content_hash}.webp"
    monkeypatch.setattr(avatars, "store_avatar", lambda *_args: new_key)
    deleted: list[str] = []
    monkeypatch.setattr(avatars, "delete_avatar", deleted.append)

    result = await avatars.import_google_avatar(uuid4(), picture_url, generation=1)

    assert result.status == "stale"
    assert not result.uploaded
    assert before_put.rollbacks == 1
    assert final_db.commits == 0
    assert superseded.avatar_content_hash == "b" * 64
    assert deleted == []


@pytest.mark.asyncio
async def test_ambiguous_db_commit_never_compensates_by_deleting_new_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_imports(monkeypatch)
    picture_url = "https://lh3.googleusercontent.com/avatar"
    processed = SimpleNamespace(data=b"safe-webp", content_hash="c" * 64)
    _install_processing(monkeypatch, processed)
    user = _avatar_user(picture_url, generation=3)
    final_db = _AvatarDB(user, commit_error=RuntimeError("commit outcome is unknown"))
    sessions = _SessionSequence(_AvatarDB(user), _AvatarDB(user), final_db)
    monkeypatch.setattr(avatars, "async_session_factory", sessions)
    new_key = f"avatars/{uuid4().hex}/{processed.content_hash}.webp"
    monkeypatch.setattr(avatars, "store_avatar", lambda *_args: new_key)
    deleted: list[str] = []
    monkeypatch.setattr(avatars, "delete_avatar", deleted.append)

    with pytest.raises(RuntimeError, match="outcome is unknown"):
        await avatars.import_google_avatar(uuid4(), picture_url, generation=3)

    assert final_db.commits == 1
    assert user.avatar_object_key == new_key
    assert deleted == []


@pytest.mark.asyncio
async def test_unchanged_inactive_assignee_does_not_block_unrelated_issue_edit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = uuid4()
    board_id = uuid4()
    team_id = uuid4()
    assignee_id = uuid4()
    deadline = datetime(2035, 1, 1, tzinfo=UTC)
    task = SimpleNamespace(
        id=task_id,
        board_id=board_id,
        status_id=uuid4(),
        assignee_id=assignee_id,
        deadline=None,
    )
    board = SimpleNamespace(id=board_id, team_id=team_id)

    class IssueDB:
        committed = False
        activities: list[object] = []

        def add(self, value: object) -> None:
            self.activities.append(value)

        async def get(self, _model: object, _object_id: UUID) -> object:
            return board

        async def scalar(self, _statement: object) -> object:
            return task

        async def commit(self) -> None:
            self.committed = True

    db = IssueDB()

    async def get_task(*_args: object, **_kwargs: object) -> object:
        return task

    async def get_context(*_args: object, **_kwargs: object) -> object:
        return object()

    async def reject_membership_check(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Unchanged assignee must not be revalidated")

    async def load_task(*_args: object, **_kwargs: object) -> object:
        return task

    monkeypatch.setattr(issue_routes, "get_task_for_user", get_task)
    monkeypatch.setattr(issue_routes, "get_team_actor_context", get_context)
    monkeypatch.setattr(issue_routes, "validate_task_update_permissions", lambda *_args: None)
    monkeypatch.setattr(issue_routes, "require_direct_team_member", reject_membership_check)
    monkeypatch.setattr(issue_routes, "load_task_out", load_task)

    result = await issue_routes.update_task(
        task_id,
        TaskUpdate(assignee_id=assignee_id, deadline=deadline),
        SimpleNamespace(id=uuid4()),  # type: ignore[arg-type]
        db,  # type: ignore[arg-type]
        None,  # type: ignore[arg-type]
    )

    assert result is task
    assert db.committed
    assert task.assignee_id == assignee_id
    assert task.deadline == deadline
