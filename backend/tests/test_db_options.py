from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.db import options


def _configure(
    monkeypatch: pytest.MonkeyPatch,
    database_url: str,
) -> None:
    monkeypatch.setattr(
        options,
        "settings",
        SimpleNamespace(
            database_url=database_url,
            database_ssl_ca_file=None,
            request_timeout_seconds=30.0,
        ),
    )


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql+asyncpg://noki:password@127.0.0.2:5432/noki",
        "postgresql+asyncpg://noki:password@api.localhost:5432/noki",
        "postgresql+asyncpg://noki:password@[::1]:5432/noki",
        "postgresql+asyncpg://noki:password@db:5432/noki",
        "postgresql+asyncpg://noki:password@postgres:5432/noki",
    ],
)
def test_internal_postgres_hosts_explicitly_disable_tls_defaults(
    monkeypatch: pytest.MonkeyPatch,
    database_url: str,
) -> None:
    _configure(monkeypatch, database_url)

    connect_args = options.postgres_connect_args("noki-test")

    assert connect_args["ssl"] is False
    assert connect_args["command_timeout"] == 30.0
    assert connect_args["server_settings"] == {
        "application_name": "noki-test",
        "statement_timeout": "30000",
        "timezone": "UTC",
    }


def test_migrations_keep_lock_timeout_but_disable_request_timeouts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(
        monkeypatch,
        "postgresql+asyncpg://noki:password@127.0.0.1:5432/noki",
    )

    connect_args = options.postgres_connect_args(
        "noki-migration",
        lock_timeout_seconds=30,
        disable_timeouts=True,
    )

    assert "command_timeout" not in connect_args
    assert connect_args["ssl"] is False
    assert connect_args["server_settings"] == {
        "application_name": "noki-migration",
        "lock_timeout": "30000",
        "timezone": "UTC",
    }


def test_remote_postgres_still_requires_a_ca_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(
        monkeypatch,
        "postgresql+asyncpg://noki:password@db.example.com:5432/noki",
    )

    with pytest.raises(RuntimeError, match="DATABASE_SSL_CA_FILE"):
        options.postgres_connect_args("noki-test")
