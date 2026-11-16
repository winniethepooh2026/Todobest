from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.models import IssueStatus
from app.schemas import TodoCreate, TodoUpdate


def test_todo_create_normalizes_fields_and_accepts_aware_deadline() -> None:
    deadline = datetime(2026, 8, 3, 18, 0, tzinfo=UTC)

    payload = TodoCreate(
        title="  Подготовить   отчёт  ",
        description="Данные за неделю",
        deadline=deadline,
    )

    assert payload.title == "Подготовить отчёт"
    assert payload.deadline == deadline
    assert payload.status is IssueStatus.TODO
    assert payload.position == 0


def test_todo_deadline_must_include_timezone() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        TodoCreate(
            title="Задача",
            deadline=datetime(2026, 8, 3, 18, 0),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", None),
        ("description", None),
        ("status", None),
        ("position", None),
    ],
)
def test_todo_update_rejects_null_for_required_stored_fields(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError, match=f"Todo {field} cannot be null"):
        TodoUpdate.model_validate({field: value})


def test_todo_update_allows_clearing_deadline() -> None:
    payload = TodoUpdate.model_validate({"deadline": None})

    assert payload.deadline is None
    assert payload.model_fields_set == {"deadline"}


@pytest.mark.parametrize(
    "payload",
    [
        {"title": "Задача", "status": "blocked"},
        {"title": "Задача", "position": -1},
        {"title": "Задача", "assignee_id": "someone-else"},
    ],
)
def test_todo_create_rejects_invalid_or_external_ownership_fields(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        TodoCreate.model_validate(payload)
