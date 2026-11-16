# Noki MVP

Noki объединяет лёгкий аналог Linear для задач и визуальный редактор страниц в
стиле Notion: Space → Team → Issue board/Page, Kanban, My issues, Google OAuth,
лимиты, настройка колонок и локальные изображения до 25 МБ.

## Стек

- Backend: Python 3.13, FastAPI 0.140.0, SQLAlchemy 2.0.51 async,
  PostgreSQL 18.4, Alembic 1.18.5, Redis 8.8.1, Celery 5.6.3.
- Frontend: Next.js 16.2.12, React 19.2.8, TypeScript 6.0.3,
  Tailwind CSS 4.3.3, Radix/shadcn-style UI, dnd-kit, Tiptap 3.29.0.
- Авторизация: JWT access/refresh в HttpOnly cookies, Argon2, CSRF
  double-submit token, Google OAuth 2.0; отдельные персональные Bearer-токены
  для public API.
- Данные Pages, Issues и исходные имена загрузок: AES-256-GCM до записи
  в PostgreSQL; уникальный nonce и проверка целостности для каждого поля.

## Локальный запуск

Требуются локально установленные PostgreSQL, Redis, Python 3.13 и Node 24.

```bash
make install-backend
make install-frontend
make migrate
make dev-backend    # отдельным терминалом: uvicorn --reload на :8000
make dev-frontend   # отдельным терминалом: next dev на :3000
```

После запуска:

- приложение: http://localhost:3000
- Swagger: http://localhost:8000/docs
- health check: http://localhost:8000/health

## Локальный запуск через Docker

Если установлены Docker и Compose, можно запустить весь dev-стек одной
командой:

```bash
docker compose -f docker/compose.yml up --build
```

Конфигурация предназначена для локальной разработки. Подробности и порядок
удаления тестовых томов — в [docker/README.md](docker/README.md).

## Public API

Версионированный API для серверных интеграций доступен по адресу
`/api/public/v1`. Он позволяет получать пространства, команды, доски и
участников, читать и изменять задачи, а также читать и добавлять комментарии.
Машиночитаемая схема: `/api/public/v1/openapi.json`.

Авторизация выполняется персональным Bearer-токеном; браузерные cookies и JWT
для этого API не принимаются. Порядок создания токена, описание маршрутов,
управление токенами через Public API и примеры для cURL, Python и Node.js
приведены в [`docs/API.md`](docs/API.md).

Backend читает dev-настройки из `backend/.env` (см. `pydantic-settings`,
`env_file=(".env", "../.env")`) — это отдельный, нестрогий файл, не путать с
корневым production-файлом `.env` ниже.

## Production deployment

Приложение развёрнуто на **https://noki.click**. Фактическое состояние
продакшна — топология, порты, что включено и отключено, риски и диагностика —
в [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md). Пошаговый runbook первого
развёртывания — в [`docs/PRODUCTION.md`](docs/PRODUCTION.md), порядок
обновления релиза — в [`UPDATE.md`](UPDATE.md).

Приложение запускается через PM2 (`ecosystem.config.cjs`): один файл описывает
все четыре процесса — `noki-api`, `noki-worker`, `noki-beat`, `noki-frontend`.
Backend-процессы и frontend читают разные env-файлы — так фронтенд физически
не может получить DB/JWT/encryption secrets, даже если оба процесса работают
под одним Unix-пользователем.

Production migration вынесена в отдельный one-shot шаг и не запускается при
каждом restart.
Для собственного домена задайте `NEXT_PUBLIC_SITE_URL` перед сборкой frontend:
он используется в metadata, sitemap и robots.

Параметры PostgreSQL задаются только в корневом `.env` через
`POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER` и
`POSTGRES_PASSWORD`; `config.py` и ручной `DATABASE_URL` для нового
развёртывания менять не нужно. Роль и сама база PostgreSQL создаются
администратором отдельно; затем явная команда
`make BACKUP_CONFIRMED=YES pm2-migrate` создаёт и обновляет таблицы Alembic.
Обычный запуск PM2 намеренно ничего не создаёт и не мигрирует.

Полный порядок подготовки secrets, backup, build, migration, PM2 start,
reverse proxy, проверки и rollback приведён в
[`docs/PRODUCTION.md`](docs/PRODUCTION.md). `.env.example` — единый
production-шаблон; заполненную копию храните как корневой `.env` с правами
`0600`. PM2 передаёт frontend только явный allowlist публичных значений.

## Ключ шифрования данных

Перед первым запуском один раз сгенерируйте 32 случайных байта в base64:

```bash
python -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

Сохраните результат в `DATA_ENCRYPTION_KEY` внутри защищённого production env
file. Не коммитьте настоящий ключ и не храните его в PostgreSQL или резервной
копии БД. Без этого
ключа backend и миграция намеренно не запускаются. Потеря ключа означает
невозможность восстановить зашифрованные данные.

## Google OAuth

1. Создайте OAuth Client ID типа `Web application` в Google Cloud Console.
2. Добавьте redirect URI:
   `http://localhost:8000/api/v1/auth/google/callback`.
3. Заполните `GOOGLE_CLIENT_ID` и `GOOGLE_CLIENT_SECRET` в `.env`.
4. В development перезапустите backend через dev Compose; в production
   выполните процедуру restart из `docs/PRODUCTION.md`.

Без этих двух переменных Google OAuth отключён.

## Ручная установка

### Backend

Нужны Python 3.13, PostgreSQL 18 и Redis 8.

Linux/macOS:

```bash
cd backend
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
# Настройте отдельный development .env с валидным DATA_ENCRYPTION_KEY
alembic upgrade head
uvicorn app.main:app --reload
```

Windows PowerShell:

```powershell
cd backend
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
# Настройте отдельный development .env с валидным DATA_ENCRYPTION_KEY
alembic upgrade head
uvicorn app.main:app --reload
```

Celery запускается отдельно:

```bash
celery -A app.worker.celery_app:celery_app worker --loglevel=INFO
celery -A app.worker.celery_app:celery_app beat --loglevel=INFO
```

Транзакционная почта работает через отдельную очередь `mail`; production PM2
запускает для неё процесс `noki-mail-worker`. Настройка Resend и DNS описана в
[`docs/EMAIL.md`](docs/EMAIL.md).

### Frontend

```bash
cd frontend
npm ci
npm run dev
```

## Ограничения MVP

- 2 Space на пользователя.
- 3 Team на пользователя суммарно.
- 3 Issue board и 3 Page внутри одной Team.
- 100 задач на пользователя суммарно.
- До 10 колонок на доске.
- Изображения: JPEG/PNG/WebP/GIF, максимум 25 МБ; на сервере они
  нормализуются в WebP и уменьшаются до ширины не более 720 px.
- Текст одной страницы: до 200 000 символов, одного текстового узла:
  до 20 000 символов.

Создатель Issue хранится отдельно от исполнителя и отображается в интерфейсе.
Новое Issue по умолчанию создаётся без исполнителя. Owner/admin назначает только
активного непосредственного участника соответствующей Team. Непосредственный
участник может атомарно взять свободную Issue на себя через
`POST /api/v1/tasks/{task_id}/claim`; занятая Issue возвращает `409`.

Owner/admin управляет Issue полностью. Member видит Issues своей Team, но
generic PATCH, создание, удаление, Board settings и bulk reorder для него
запрещены backend-ом. После claim member может менять только статус собственной
Issue через `PATCH /api/v1/tasks/{task_id}/status` и только между стабильными
системными статусами `todo`, `in_progress`, `done`.

Page создаётся с `created_by_id`, который назначает backend. Owner/admin может
редактировать доступную Page, member — только созданную им самим; чужая Page для
member доступна только на чтение. Эти правила проверяются на backend, а frontend
использует возвращаемые capability-флаги.

В Space и Team доступны роли `owner/admin/member`. Space owner/admin управляют
обычными участниками Team, Team owner/admin — участниками своей Team. Назначать,
понижать и удалять Team owner может только Space owner или Team owner. Последнего
owner Space или Team нельзя удалить или понизить. Удаление пользователя из Space
удаляет его memberships во всех Team этого Space и снимает с назначенных Issues.

## Миграция существующей базы

Миграция `0002_secure_content` сначала шифрует существующие Pages, Issues и
исходные имена загрузок, проверяет заполнение новых колонок и только затем
удаляет plaintext-колонки. Миграция `0003_team_members` добавляет ограничения
ролей Team и переводит `tasks.assignee_id` в nullable FK с `ON DELETE SET NULL`.
Миграция `0004_system_statuses` вводит стабильные системные статусы. Она не
угадывает смысл переименованных custom-колонок, а создаёт недостающие системные
колонки. Если это превысит лимит в 10 колонок, migration безопасно остановится с
UUID проблемных Board: сначала уменьшите число custom-колонок и повторите
upgrade.

Перед миграцией сделайте резервную копию PostgreSQL и отдельно сохраните ключ.
Не помещайте ключ в dump:

```bash
pg_dump --host=localhost --username=noki --dbname=noki \
  --format=custom --file=noki-before-encryption.dump
```

Запускайте миграции только при настроенном неизменном
`DATA_ENCRYPTION_KEY`:

```bash
cd backend
alembic upgrade head
```

## Структура

```text
noki/
├── backend/
│   ├── alembic/                 # миграции PostgreSQL
│   ├── app/
│   │   ├── api/routes/          # HTTP endpoints
│   │   ├── core/                # конфигурация и безопасность
│   │   ├── db/                  # async engine/session
│   │   ├── models/              # SQLAlchemy-модели
│   │   ├── schemas/             # Pydantic-контракты
│   │   ├── services/            # доступ, квоты, OAuth, изображения
│   │   ├── worker/              # Celery
│   │   └── main.py
│   ├── tests/
│   └── pyproject.toml
├── frontend/
│   ├── public/
│   ├── src/
│   │   ├── app/                 # Next.js App Router
│   │   ├── components/
│   │   │   ├── editor/
│   │   │   ├── kanban/
│   │   │   ├── layout/
│   │   │   ├── modals/
│   │   │   └── ui/
│   │   └── lib/
│   └── package.json
├── ecosystem.config.cjs
├── .env.example
└── Makefile
```

## Проверки

```bash
cd backend
pytest
ruff check .
ruff format --check .

cd ../frontend
npm run typecheck
npm run lint
npm run build
```

Raw PostgreSQL-проверка создаёт и затем удаляет отдельную случайную schema,
не затрагивая рабочие таблицы:

```bash
cd backend
NOKI_TEST_DATABASE_URL='postgresql+asyncpg://...' pytest -q -m postgres
```

Используйте только выделенную тестовую БД. Полная матрица изменений,
фактических запусков и ограничений среды приведена в `NOKI_FIX_REPORT.md`.
