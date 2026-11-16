# Noki — контекст проекта

Noki — таск-трекер с канбан-досками и визуальный редактор страниц.
Структура: Space → Team → Issue board / Page. Есть Kanban, «мои задачи»,
личные todo, комментарии, публичный API с персональными токенами.

## Стек

- **Backend**: Python (`requires-python = ">=3.10,<3.14"`), FastAPI, SQLAlchemy
  2 async, PostgreSQL, Alembic, Redis, Celery. Код в `backend/app`.
- **Frontend**: Next.js 16 App Router, React 19, TypeScript, Tailwind v4,
  shadcn-style UI, dnd-kit, Tiptap. Код в `frontend/src`.
- **Авторизация**: JWT access/refresh в HttpOnly cookies, Argon2, CSRF
  double-submit, Google OAuth. Для публичного API — отдельные Bearer-токены.
- **Шифрование**: содержимое Pages, Issues и исходные имена загрузок шифруются
  AES-256-GCM до записи в PostgreSQL.

## Продакшн

**https://noki.click** — развёрнут 12 сентября 2026. Полное описание состояния,
топологии и эксплуатации: [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).
Пошаговый runbook: [`docs/PRODUCTION.md`](docs/PRODUCTION.md).
Обновление релиза: [`UPDATE.md`](UPDATE.md).

Коротко: сервер `178.105.43.157`, код в `/var/www/noki`, четыре процесса под
PM2 (`noki-api`, `noki-worker`, `noki-beat`, `noki-frontend`) от пользователя
`noki`, backend на **8010**, frontend на **3010** (не 8000/3000 — те заняты
соседним приложением на том же сервере).

## Команды

```bash
make install-backend    # venv + зависимости
make install-frontend
make migrate            # локально; в продакшне только make pm2-migrate
make dev-backend        # uvicorn --reload на :8000
make dev-frontend       # next dev на :3000
make verify             # pytest + ruff + ruff format + frontend verify
make pm2-check          # preflight продакшна: .env, ecosystem, Alembic
```

`make verify` должен быть зелёным перед коммитом: 376 backend-тестов,
ruff без замечаний, frontend typecheck + ESLint + production build.

## Важные инварианты

- **Ревизия БД дублируется в трёх местах** и должна совпадать: значение
  `expected_db_revision` в `backend/app/core/config.py`, `EXPECTED_DB_REVISION`
  в `.env.example` (и в продакшн-`.env`), ассерт в
  `backend/tests/test_security_hardening.py`. Добавили миграцию — обновите все
  три, иначе `make pm2-migrate` откажется работать.
- **`backend/tests/test_deployment_contracts.py` проверяет инфраструктурные
  файлы** (`nginx.conf`, `ecosystem.config.cjs`, `Makefile`,
  `scripts/migrate-production.cjs`). Правки в них могут ломать эти тесты — это
  задумано, контракт нужно осознанно обновлять вместе с конфигом.
- **`NEXT_PUBLIC_API_URL` вмораживается в бандл при `next build`.** По умолчанию
  используется `/api/v1`; для другого значения нужна пересборка.
- `ecosystem.config.cjs` читает один `.env`, но отдаёт frontend-процессу только
  allowlist публичных ключей.
- **`DATA_ENCRYPTION_KEY` нельзя ротировать просто так** — без него
  зашифрованные Pages и Issues не расшифровать.
- `.env` и `.env.local` не коммитятся (см. `.gitignore`).

## Ограничения продукта

- Google-аватары требуют приватного S3 — в продакшне отключено, показываются
  инициалы.
- Регистрация открыта всегда: `is_public_registration_enabled` — computed
  property, возвращает `True` независимо от `PUBLIC_REGISTRATION_ENABLED`.
- Платформенный админ назначается CLI: `python -m app.cli add <email>`.
