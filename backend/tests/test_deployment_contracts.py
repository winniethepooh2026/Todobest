from __future__ import annotations

import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _source(relative_path: str) -> str:
    return (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")


def test_data_integrity_migration_does_not_use_reserved_column_alias() -> None:
    source = _source("backend/alembic/versions/0006_data_integrity.py")

    assert re.search(r"\b(?:AS|JOIN)\s+column\b", source, re.IGNORECASE) is None


def test_nginx_preserves_api_prefix_and_keeps_health_private() -> None:
    source = _source("nginx.conf")
    api_block = source[
        source.index("location /api/") : source.index(
            "location / {", source.index("location /api/")
        )
    ]

    assert "proxy_pass http://127.0.0.1:8010;" in api_block
    assert "proxy_pass http://127.0.0.1:8010/;" not in api_block
    assert "proxy_hide_header Strict-Transport-Security;" in source
    assert "proxy_hide_header Referrer-Policy;" in source
    # Диагностика бэкенда не должна проксироваться наружу; снимается по loopback.
    for private_path in ("/health", "/live", "/docs", "/openapi.json"):
        assert f"location = {private_path} {{ return 404; }}" in source
        assert f"proxy_pass http://127.0.0.1:8010{private_path}" not in source


def test_pm2_uses_one_optional_env_file_and_runtime_defaults() -> None:
    ecosystem = _source("ecosystem.config.cjs")

    assert 'path.join(root, ".env")' in ecosystem
    assert 'env.BACKEND_PORT || "8010"' in ecosystem
    assert 'env.FRONTEND_PORT || env.PORT || "3015"' in ecosystem
    assert 'env.CELERY_MAIL_WORKER_CONCURRENCY || "2"' in ecosystem
    assert "noki-billing-worker" not in ecosystem
    assert "fs.constants.W_OK" not in ecosystem


def test_next_runtime_mode_matches_next_start() -> None:
    next_config = _source("frontend/next.config.ts")
    ecosystem = _source("ecosystem.config.cjs")

    assert 'output: "standalone"' not in next_config
    assert '"start"' in ecosystem
