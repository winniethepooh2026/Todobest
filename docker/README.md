# Локальный запуск Noki через Docker Compose

Этот набор запускает PostgreSQL, Redis, миграции, API, Celery и frontend для
локальной разработки. Все веб-порты привязаны к 127.0.0.1. Он не предназначен
для production-развёртывания.

## Запуск

Из корня репозитория:

```bash
docker compose -f docker/compose.yml up --build
```

- Приложение: <http://localhost:3000>
- API docs: <http://localhost:8000/docs>
- Healthcheck: <http://localhost:8000/health>

Compose использует отдельные тестовые учётные данные PostgreSQL, JWT secret и
ключ шифрования. Не используйте этот стек для реальных данных: ключ постоянный
и опубликован в репозитории. Корневой `.env` в контейнеры не загружается.

Остановить сервисы, сохранив данные в Docker-томах:

```bash
docker compose -f docker/compose.yml down
```

Полностью удалить локальные тестовые данные:

```bash
docker compose -f docker/compose.yml down --volumes
```

После изменений исходников пересоберите образы через `up --build`.
Production-процедура описана отдельно в [docs/PRODUCTION.md](../docs/PRODUCTION.md).
