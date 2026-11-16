from __future__ import annotations

import ssl

from sqlalchemy.engine import make_url

from app.core.config import is_loopback_host, settings


def postgres_connect_args(
    application_name: str,
    *,
    lock_timeout_seconds: float | None = None,
    disable_timeouts: bool = False,
) -> dict[str, object]:
    server_settings = {
        "application_name": application_name,
        "timezone": "UTC",
    }
    args: dict[str, object] = {"server_settings": server_settings}
    if not disable_timeouts:
        server_settings["statement_timeout"] = str(int(settings.request_timeout_seconds * 1000))
        args["command_timeout"] = settings.request_timeout_seconds
    if lock_timeout_seconds is not None:
        server_settings["lock_timeout"] = str(int(lock_timeout_seconds * 1000))
    url = make_url(settings.database_url)
    host = (url.host or "").rstrip(".").casefold()
    if is_loopback_host(host) or host in {"db", "postgres"}:
        # asyncpg otherwise consults host-level TLS defaults, which makes an
        # explicitly trusted loopback/Docker connection environment-dependent.
        args["ssl"] = False
    else:
        ca_file = settings.database_ssl_ca_file
        if ca_file is None:
            raise RuntimeError("Remote PostgreSQL requires DATABASE_SSL_CA_FILE")
        context = ssl.create_default_context(cafile=str(ca_file))
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        args["ssl"] = context
    return args
