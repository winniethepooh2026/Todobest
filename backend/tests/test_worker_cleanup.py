from __future__ import annotations

import base64
import importlib
import os
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from app.core.config import settings


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


class FakeCleanupDB:
    def __init__(
        self,
        uploads: list[object],
        *,
        fail_commit: bool = False,
    ) -> None:
        self.uploads = uploads
        self.fail_commit = fail_commit
        self.deleted: list[object] = []
        self.committed = False
        self.rolled_back = False

    async def scalars(self, _statement):
        return self.uploads

    async def delete(self, upload: object) -> None:
        self.deleted.append(upload)

    async def commit(self) -> None:
        if self.fail_commit:
            raise RuntimeError("commit failed")
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


def test_cleanup_engine_reuses_verified_postgres_connect_args(
    monkeypatch: pytest.MonkeyPatch,
    worker_tasks,
) -> None:
    sentinel = {"ssl": object()}
    captured: dict[str, object] = {}

    def fake_connect_args(
        application_name: str,
        *,
        lock_timeout_seconds: float | None = None,
    ) -> dict[str, object]:
        captured["application_name"] = application_name
        captured["lock_timeout_seconds"] = lock_timeout_seconds
        return sentinel

    monkeypatch.setattr(worker_tasks, "postgres_connect_args", fake_connect_args)
    monkeypatch.setattr(
        settings,
        "database_url_override",
        SecretStr("postgresql+asyncpg://noki:password@db.example/noki"),
    )

    options = worker_tasks._cleanup_engine_options()

    assert options["connect_args"] is sentinel
    assert captured == {
        "application_name": "noki-cleanup",
        "lock_timeout_seconds": 5,
    }


async def test_cleanup_finalizes_file_only_after_database_commit(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    worker_tasks,
) -> None:
    monkeypatch.setattr(settings, "upload_dir", tmp_path)
    filename = f"{'d' * 32}.webp"
    path = tmp_path / filename
    path.write_bytes(b"image")
    upload = SimpleNamespace(filename=filename)
    db = FakeCleanupDB([upload])

    cleaned = await worker_tasks._cleanup_upload_batch(
        db,
        threshold=datetime.now(UTC),
    )

    assert cleaned == 1
    assert db.deleted == [upload]
    assert db.committed
    assert not path.exists()
    assert list(tmp_path.iterdir()) == []


async def test_cleanup_restores_staged_file_when_database_commit_fails(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    worker_tasks,
) -> None:
    monkeypatch.setattr(settings, "upload_dir", tmp_path)
    filename = f"{'e' * 32}.webp"
    path = tmp_path / filename
    path.write_bytes(b"image")
    db = FakeCleanupDB(
        [SimpleNamespace(filename=filename)],
        fail_commit=True,
    )

    with pytest.raises(RuntimeError, match="commit failed"):
        await worker_tasks._cleanup_upload_batch(
            db,
            threshold=datetime.now(UTC),
        )

    assert db.rolled_back
    assert path.read_bytes() == b"image"
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("tracked", [False, True])
async def test_old_untracked_final_image_is_reconciled_conservatively(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    tracked: bool,
    worker_tasks,
) -> None:
    monkeypatch.setattr(settings, "upload_dir", tmp_path)
    filename = f"{'f' * 32}.webp"
    path = tmp_path / filename
    path.write_bytes(b"image")
    os.utime(path, (0, 0))
    db = FakeCleanupDB([filename] if tracked else [])

    await worker_tasks._reconcile_untracked_images(db)

    assert path.exists() is tracked
