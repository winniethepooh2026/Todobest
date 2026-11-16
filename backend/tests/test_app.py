from pathlib import Path

from alembic.script import ScriptDirectory
from pytest import MonkeyPatch

from app import main
from app.core.config import Settings
from app.main import _database_revision_is_ready, app


def test_openapi_exposes_mvp_routes() -> None:
    paths = app.openapi()["paths"]

    assert "/api/v1/spaces" in paths
    assert "/api/v1/spaces/{space_id}/members" in paths
    assert "/api/v1/spaces/{space_id}/members/{user_id}" in paths
    assert "/api/v1/teams/{team_id}/members" in paths
    assert "/api/v1/teams/{team_id}/members/{user_id}" in paths
    assert "/api/v1/tasks/{task_id}/claim" in paths
    assert "/api/v1/tasks/{task_id}/status" in paths
    assert "/api/v1/boards/{board_id}" in paths
    assert "/api/v1/pages/{page_id}" in paths
    assert "/api/v1/todos" in paths
    assert "/api/v1/todos/{todo_id}" in paths
    assert "/api/v1/uploads/images" in paths
    assert "/api/v1/api-tokens" in paths
    assert "/api/v1/api-tokens/{token_id}" in paths
    assert "/api/public/v1/me" in paths
    assert "/api/public/v1/tasks" in paths
    assert "/api/public/v1/tasks/{task_id}/comments" in paths


def test_database_revision_gate_requires_exactly_one_expected_head(
    monkeypatch: MonkeyPatch,
) -> None:
    expected = Settings(_env_file=None).expected_db_revision
    monkeypatch.setattr(main.settings, "expected_db_revision", expected)

    assert _database_revision_is_ready([expected])
    assert not _database_revision_is_ready([])
    assert not _database_revision_is_ready([expected, "unexpected_branch"])


def test_expected_database_revision_matches_the_migration_head() -> None:
    migrations = ScriptDirectory(str(Path(__file__).parents[1] / "alembic"))

    assert migrations.get_heads() == [Settings(_env_file=None).expected_db_revision]


def test_migration_revision_ids_fit_the_alembic_version_column() -> None:
    migrations = ScriptDirectory(str(Path(__file__).parents[1] / "alembic"))

    for revision in migrations.walk_revisions():
        assert len(revision.revision) <= 32, revision.revision
