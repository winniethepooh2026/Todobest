from __future__ import annotations

import json

import pytest
from fastapi import Request
from fastapi.exceptions import RequestValidationError

from app.main import MAX_VALIDATION_ERRORS, request_validation_error_handler


@pytest.mark.asyncio
async def test_validation_errors_do_not_echo_rejected_input() -> None:
    rejected_input = "never-echo-this-sensitive-value"
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/register",
            "headers": [],
        }
    )
    error = RequestValidationError(
        [
            {
                "type": "string_too_short",
                "loc": ("body", "password"),
                "msg": "String should have at least 12 characters",
                "input": rejected_input,
                "ctx": {"min_length": 12},
            }
        ]
    )

    response = await request_validation_error_handler(request, error)
    payload = json.loads(response.body)

    assert response.status_code == 422
    assert rejected_input not in response.body.decode()
    assert payload["detail"] == [
        {
            "type": "string_too_short",
            "loc": ["body", "password"],
            "msg": "String should have at least 12 characters",
        }
    ]


@pytest.mark.asyncio
async def test_validation_error_response_is_bounded() -> None:
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/login",
            "headers": [],
        }
    )
    errors = [
        {
            "type": "extra_forbidden",
            "loc": ("body", f"attacker-field-{index}-" + ("x" * 500)),
            "msg": "Extra inputs are not permitted" + ("y" * 500),
            "input": "never-echo-" + ("z" * 500),
        }
        for index in range(MAX_VALIDATION_ERRORS * 4)
    ]

    response = await request_validation_error_handler(
        request,
        RequestValidationError(errors),
    )
    payload = json.loads(response.body)

    assert len(payload["detail"]) == MAX_VALIDATION_ERRORS + 1
    assert payload["detail"][-1]["type"] == "too_many_validation_errors"
    assert len(response.body) < 20_000
    assert "never-echo" not in response.body.decode()
