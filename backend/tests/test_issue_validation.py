from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.schemas.issues import MAX_TASK_ORDER_ITEMS, TaskOrderRequest


def _ids(start: int, count: int) -> list[UUID]:
    return [UUID(int=value) for value in range(start, start + count)]


def test_task_order_rejects_oversized_column_before_route_work() -> None:
    with pytest.raises(ValidationError, match="List should have at most"):
        TaskOrderRequest.model_validate(
            {
                "columns": [
                    {
                        "column_id": uuid4(),
                        "task_ids": _ids(1, MAX_TASK_ORDER_ITEMS + 1),
                    }
                ]
            }
        )


def test_task_order_rejects_oversized_aggregate() -> None:
    with pytest.raises(ValidationError, match="cannot contain more"):
        TaskOrderRequest.model_validate(
            {
                "columns": [
                    {
                        "column_id": uuid4(),
                        "task_ids": _ids(1, MAX_TASK_ORDER_ITEMS // 2 + 1),
                    },
                    {
                        "column_id": uuid4(),
                        "task_ids": _ids(
                            MAX_TASK_ORDER_ITEMS // 2 + 2,
                            MAX_TASK_ORDER_ITEMS // 2,
                        ),
                    },
                ]
            }
        )


@pytest.mark.parametrize("duplicate_kind", ["column", "task"])
def test_task_order_rejects_duplicate_identifiers(duplicate_kind: str) -> None:
    first_column = uuid4()
    second_column = first_column if duplicate_kind == "column" else uuid4()
    first_task = uuid4()
    second_task = first_task if duplicate_kind == "task" else uuid4()

    with pytest.raises(ValidationError, match="appears more than once"):
        TaskOrderRequest.model_validate(
            {
                "columns": [
                    {"column_id": first_column, "task_ids": [first_task]},
                    {"column_id": second_column, "task_ids": [second_task]},
                ]
            }
        )
