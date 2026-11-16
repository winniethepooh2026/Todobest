from __future__ import annotations

import asyncio
import base64
import importlib
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.core.config import settings
from app.services.avatars import AvatarImportResult


@pytest.fixture
def worker_tasks(monkeypatch: pytest.MonkeyPatch):
    from app.core.encryption import get_data_cipher

    monkeypatch.setattr(
        settings,
        "data_encryption_key",
        base64.urlsafe_b64encode(bytes(range(32))).decode(),
    )
    get_data_cipher.cache_clear()
    module = importlib.import_module("app.worker.tasks")
    yield module
    get_data_cipher.cache_clear()


class _FakeEngine:
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.creation_loop = loop
        self.dispose_calls = 0
        self.disposal_loop: asyncio.AbstractEventLoop | None = None

    async def dispose(self) -> None:
        self.dispose_calls += 1
        self.disposal_loop = asyncio.get_running_loop()


def test_sequential_avatar_tasks_isolate_engines_and_event_loops(
    monkeypatch: pytest.MonkeyPatch,
    worker_tasks,
) -> None:
    engines: list[_FakeEngine] = []
    session_factories: list[SimpleNamespace] = []
    import_calls: list[tuple[UUID, object, asyncio.AbstractEventLoop]] = []

    def create_engine(_database_url: str, **_options: object) -> _FakeEngine:
        engine = _FakeEngine(asyncio.get_running_loop())
        engines.append(engine)
        return engine

    def create_session_factory(
        *args: object,
        **kwargs: object,
    ) -> SimpleNamespace:
        engine = kwargs.get("bind", args[0] if args else None)
        factory = SimpleNamespace(engine=engine)
        session_factories.append(factory)
        return factory

    async def import_avatar(
        user_id: UUID,
        _picture_url: str,
        _generation: int,
        *,
        session_factory: object,
    ) -> AvatarImportResult:
        import_calls.append((user_id, session_factory, asyncio.get_running_loop()))
        return AvatarImportResult(status="fresh")

    monkeypatch.setattr(worker_tasks, "create_async_engine", create_engine)
    monkeypatch.setattr(worker_tasks, "async_sessionmaker", create_session_factory)
    monkeypatch.setattr(worker_tasks, "import_google_avatar", import_avatar)

    first_user_id = uuid4()
    second_user_id = uuid4()
    picture_url = "https://lh3.googleusercontent.com/avatar"

    first_result = worker_tasks.import_google_avatar_task.run(
        str(first_user_id),
        picture_url,
        1,
    )
    second_result = worker_tasks.import_google_avatar_task.run(
        str(second_user_id),
        picture_url,
        2,
    )

    assert first_result == {"status": "fresh", "uploaded": False}
    assert second_result == {"status": "fresh", "uploaded": False}
    assert len(engines) == 2
    assert engines[0] is not engines[1]
    assert len(session_factories) == 2
    assert session_factories[0] is not session_factories[1]

    first_call, second_call = import_calls
    first_loop = first_call[2]
    second_loop = second_call[2]
    assert first_call[:2] == (first_user_id, session_factories[0])
    assert second_call[:2] == (second_user_id, session_factories[1])
    assert session_factories[0].engine is engines[0]
    assert session_factories[1].engine is engines[1]
    assert first_loop is not second_loop

    assert engines[0].creation_loop is first_loop
    assert engines[1].creation_loop is second_loop
    assert engines[0].dispose_calls == 1
    assert engines[1].dispose_calls == 1
    assert engines[0].disposal_loop is first_loop
    assert engines[1].disposal_loop is second_loop
    assert first_loop.is_closed()
    assert second_loop.is_closed()
