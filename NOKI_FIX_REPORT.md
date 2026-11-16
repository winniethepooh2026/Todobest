# Noki — отчёт по RBAC, memberships и шифрованию

Дата проверки: 28 июля 2026 года.

## 1. Итог

В проект внесены реальные backend/frontend/infra-изменения без переписывания
приложения и без замены стека. Закрыты обнаруженные нарушения RBAC для Issues и
Pages, добавлены безопасные claim/status-операции, доведены Team memberships,
введено AES-256-GCM шифрование пользовательского контента перед записью в БД и
добавлены Alembic-миграции.

Локальный результат:

- backend: `95 passed, 1 skipped`;
- Ruff и Python compileall: успешно;
- frontend typecheck, ESLint и production build: успешно;
- Alembic topology: одна линейная head `0004_system_statuses`;
- Docker runtime: не проверен — Docker CLI отсутствует;
- raw PostgreSQL proof: тест запущен отдельно, но упал на setup из-за сброса
  соединения локальным PostgreSQL; отсутствие plaintext в реальной БД **не
  заявляется как подтверждённое**.

## 2. Что было найдено

### Issues

- Visibility helper использовался как mutation permission: обычный Team member
  мог создавать, полностью PATCH-ить и удалять Issue.
- Member мог менять `assignee_id`, deadline и status через generic PATCH.
- Board/columns/bulk reorder также не имели action-level RBAC.
- Pydantic-модели молча игнорировали лишние поля.
- Статусы зависели только от произвольных UUID колонок и не имели стабильного
  ключа `todo/in_progress/done`.
- Claim был атомарным условным UPDATE, но повторный self-claim мог выглядеть
  успешным вместо `409`.
- Проверка assignee не доказывала одновременно active User, прямой Team
  membership и membership в родительском Space.
- Повторный `SELECT ... FOR UPDATE` мог вернуть stale ORM instance из identity
  map; это создавало TOCTOU для assignee/status и PATCH atomicity.

### Pages

- Любой участник Team мог PATCH/DELETE чужую Page.
- Авторство не возвращалось как capability-контракт frontend-у.
- Чужая Page оставалась полностью редактируемой в интерфейсе.
- Manager не мог сохранить Page с уже прикреплённым изображением автора.
- Владелец Upload мог перепривязать файл от другой Page без проверки текущей
  ассоциации.

### Team memberships

- Модель memberships была неполной на уровне CRUD/API и frontend.
- Не было единого permission service для Space/Team hierarchy.
- Требовалась защита последнего owner и очистка assignee при удалении
  membership.
- Создание Team могло конкурировать с удалением Space membership и оставить
  TeamMember без родительского SpaceMember.

### Состояние шифрования до изменений

В базовой ревизии `0001_initial` чувствительный контент хранился как plaintext:

- `tasks.title`, `tasks.description`;
- `pages.title`, `pages.content` (JSONB), `pages.markdown`;
- `uploads.original_name`.

Отдельного authenticated-encryption service, обязательного
`DATA_ENCRYPTION_KEY` и backfill-миграции не было. Следовательно, до
`0002_secure_content` PostgreSQL логически содержал открытый пользовательский
текст.

## 3. Реализованные правила

### Issues

- Полное управление Issue, Board, columns и bulk reorder разрешено только
  Team owner/admin или унаследованному Space owner/admin.
- Generic `PATCH /api/v1/tasks/{task_id}` использует `model_fields_set`,
  `extra="forbid"` и централизованную field-level проверку до мутации.
- Если member передаёт хотя бы одно поле generic PATCH, возвращается `403`;
  поле не игнорируется и никакая часть payload не сохраняется.
- `assignee_id` различает omitted, UUID и `null`.
- Assignee должен быть active User, прямым участником Team и участником
  родительского Space.
- Новый Issue по умолчанию не имеет assignee.
- `POST /api/v1/tasks/{task_id}/claim` не принимает `user_id`, назначает только
  текущего прямого участника и использует
  `UPDATE ... WHERE assignee_id IS NULL RETURNING`; занятая Issue возвращает
  `409`.
- `PATCH /api/v1/tasks/{task_id}/status` принимает только enum
  `todo/in_progress/done`.
- Member меняет status только назначенной себе Issue и только если и исходная,
  и целевая колонки являются системными.
- Owner/admin может менять произвольную колонку через manager-only generic
  PATCH/reorder.
- IDOR к чужой Team/Space маскируется `404`.
- Locked rows перечитываются с `populate_existing=True`, поэтому permission
  check работает с текущими assignee/status/deadline.

### Pages

- `created_by_id` задаётся backend-ом из authenticated User и не принимается в
  payload.
- Owner/admin редактирует и удаляет любую доступную Page.
- Member создаёт Page и редактирует/удаляет только собственную.
- Чужая Page доступна member только на чтение; mutation возвращает `403`.
- Outsider/UUID другой Space получает `404`.
- API возвращает `created_by`, `can_edit`, `can_delete`.
- Existing Upload текущей Page разрешён manager-у; новый Upload должен
  принадлежать actor и быть ещё не привязан. Upload другой Page нельзя
  «украсть» PATCH-запросом.

### Team memberships

- Создатель Team получает role `owner`.
- Добавляется только active User из родительского Space.
- Duplicate membership возвращает `409`.
- Роли ограничены `owner/admin/member`.
- Member не управляет memberships.
- Admin не управляет owner; Team owner или Space owner может управлять owner в
  разрешённых границах.
- Последнего owner нельзя удалить/понизить.
- Удаление Space member удаляет его Team memberships этого Space и снимает
  assignee; если он последний owner Team, операция блокируется `409`.
- Parent Space и Team блокируются в едином порядке, включая create Team, чтобы
  не оставить orphan TeamMember при конкурирующем удалении.

## 4. Матрица ролей

| Действие | Owner | Admin | Member |
| --- | :---: | :---: | :---: |
| Просматривать Issues своей Team | Да | Да | Да |
| Создавать Issue | Да | Да | Нет |
| Полностью редактировать Issue | Да | Да | Нет |
| Менять assignee | Да | Да | Нет |
| Менять deadline | Да | Да | Нет |
| Менять title/description | Да | Да | Нет |
| Удалять Issue | Да | Да | Нет |
| Настраивать Board/columns/reorder | Да | Да | Нет |
| Claim свободной Issue на себя | Да* | Да* | Да* |
| Claim занятой Issue | Нет | Нет | Нет |
| Переназначить обычным PATCH | Да | Да | Нет |
| Менять status любой Issue Team | Да | Да | Нет |
| Менять status своей Issue | Да | Да | Да |
| Создавать Page | Да | Да | Да |
| Редактировать свою Page | Да | Да | Да |
| Редактировать чужую Page | Да | Да | Нет |
| Удалять чужую Page | Да | Да | Нет |

`*` Claim требует прямого active membership в Team даже для Space
owner/admin. Space owner/admin без прямого Team membership сохраняет полное
административное управление, но не может назначить claim самому себе.

## 5. Таблица шифрования

| Модель | Поле | INSERT | UPDATE | Чтение API | Логическая plaintext-колонка после `0002` |
| --- | --- | :---: | :---: | :---: | :---: |
| Task/Issue | `title` | AES-256-GCM | AES-256-GCM | Расшифровка | Нет |
| Task/Issue | `description` | AES-256-GCM | AES-256-GCM | Расшифровка | Нет |
| Page | `title` | AES-256-GCM | AES-256-GCM | Расшифровка | Нет |
| Page | `content` и вложенный JSON/text | AES-256-GCM | AES-256-GCM | JSON после расшифровки | Нет |
| Page | `markdown` | AES-256-GCM | AES-256-GCM | Расшифровка | Нет |
| Upload | `original_name` | AES-256-GCM | Helper доступен | Расшифровка service-layer | Нет |

Фактическая модель не содержит Issue comments, labels или отдельного search
index. UUID/FK, status, position, deadline, роли, названия Space/Team/Board,
техническое имя обработанного файла и размеры остаются plaintext как
структурные/операционные данные. Бинарное содержимое изображения хранится в
filesystem и этой миграцией не шифруется.

Криптографический формат:

- AES-256-GCM из `cryptography`, без самописной криптографии;
- ключ — ровно 32 байта в Base64 из environment;
- уникальный случайный 12-byte nonce для каждого сохранения;
- отдельный 16-byte authentication tag;
- AAD связывает version, table, record UUID и field;
- `encryption_key_version=1`;
- wrong key, повреждённый tag/ciphertext, неправильная длина nonce/tag и
  неверный UTF-8/JSON завершаются контролируемой ошибкой без plaintext fallback;
- encrypted record обязан иметь стабильный UUID до шифрования;
- ключ не возвращается API, не передаётся frontend/Next.js и не помещается в
  Celery payload.

## 6. Alembic-миграции

### `0002_secure_content`

- Переименовывает `space_members` в `space_memberships`.
- Добавляет encrypted BYTEA columns и `encryption_key_version`.
- Одноразово шифрует существующие Task/Page/Upload values без вывода plaintext
  в лог.
- Делает encrypted columns `NOT NULL`.
- Удаляет исходные plaintext columns только после backfill.
- Downgrade требует тот же ключ, расшифровывает значения и восстанавливает
  legacy columns.
- Использует финализированные имена constraints через `op.f(...)`.

### `0003_team_members`

- Добавляет check constraint ролей Team.
- Делает `tasks.assignee_id` nullable.
- FK использует `ON DELETE SET NULL`.
- Downgrade не переназначает Issue молча: при unassigned tasks он останавливается
  с понятной ошибкой до DDL.

### `0004_system_statuses`

- Добавляет nullable `board_columns.system_status`.
- Legacy label считается системным только при однозначном единственном
  совпадении; position/custom-name не используются как предположение.
- Создаёт недостающие canonical system columns с детерминированными UUID и
  уникальным display name.
- До записи проверяет лимит 10 columns. Если безопасное добавление невозможно,
  вся transaction прерывается и перечисляет UUID Board; custom columns не
  удаляются и не переименовываются.
- Добавляет check и unique `(board_id, system_status)`.
- Downgrade удаляет только созданные миграцией columns и отказывается это
  делать, если на них уже ссылаются Tasks.

Проверена только структура цепочки:

```text
0001_initial
  -> 0002_secure_content
  -> 0003_team_members
  -> 0004_system_statuses (head)
```

Реальные PostgreSQL upgrade/downgrade в этой среде не выполнялись.

## 7. Изменённые файлы

Конфигурация и документация:

```text
.env.example
.gitignore
Makefile
README.md
NOKI_FIX_REPORT.md
docker-compose.yml
backend/.dockerignore
frontend/.dockerignore
```

Backend:

```text
backend/alembic/versions/0002_encrypted_content_and_space_memberships.py
backend/alembic/versions/0003_team_members_and_optional_assignee.py
backend/alembic/versions/0004_system_issue_statuses.py
backend/app/api/routes/issues.py
backend/app/api/routes/pages.py
backend/app/api/routes/uploads.py
backend/app/api/routes/workspaces.py
backend/app/core/config.py
backend/app/core/encryption.py
backend/app/main.py
backend/app/models/__init__.py
backend/app/models/issues.py
backend/app/models/page.py
backend/app/models/workspace.py
backend/app/schemas/__init__.py
backend/app/schemas/issues.py
backend/app/schemas/navigation.py
backend/app/schemas/pages.py
backend/app/schemas/workspace.py
backend/app/services/access.py
backend/app/services/content_encryption.py
backend/app/services/memberships.py
backend/app/worker/celery_app.py
backend/pyproject.toml
backend/tests/test_app.py
backend/tests/test_encryption.py
backend/tests/test_memberships.py
backend/tests/test_page_validation.py
backend/tests/test_postgres_encryption.py
backend/tests/test_resource_rbac_integration.py
backend/tests/test_team_issue_integration.py
backend/tests/test_team_issue_rules.py
```

Frontend:

```text
frontend/next-env.d.ts
frontend/src/app/globals.css
frontend/src/app/app/pages/[pageId]/page.tsx
frontend/src/app/app/spaces/[spaceId]/members/page.tsx
frontend/src/app/app/teams/[teamId]/page.tsx
frontend/src/components/editor/editor-toolbar.tsx
frontend/src/components/editor/page-editor.tsx
frontend/src/components/kanban/board-settings.tsx
frontend/src/components/kanban/kanban-board.tsx
frontend/src/components/kanban/task-dialog.tsx
frontend/src/components/layout/sidebar.tsx
frontend/src/components/members/add-space-member-dialog.tsx
frontend/src/components/members/team-members-panel.tsx
frontend/src/lib/types.ts
```

Удалены три отслеживаемых runtime-файла
`backend/celerybeat-schedule{,-shm,-wal}`. Они были сгенерированным состоянием
Celery Beat, а не исходным кодом; восстановимы из Git. Новое расписание
записывается в `/tmp`, а `celerybeat-schedule*` игнорируется.

## 8. Frontend

- Board API возвращает `current_user_id`, `can_manage_tasks`,
  `can_claim_tasks`.
- Member не видит create Issue, Board settings, DnD, assignee/deadline/full
  edit/delete.
- Свободная Issue показывает claim.
- Status selector показывается только assignee текущего пользователя и только
  для системной исходной колонки.
- Owner/admin видит полный manager UI.
- Системные колонки нельзя удалить в Board Settings.
- Page API возвращает author/capabilities.
- Чужая Page read-only: нет autosave, title editing, toolbar, upload или delete.
- Вставленные в Page ссылки открываются по клику в editable/read-only режимах;
  URL без протокола нормализуется в HTTPS, опасные протоколы отклоняются.
- `403` и другие mutation errors показываются через toast.
- React Query обновляет Board/Page/navigation без полной перезагрузки.
- Frontend service больше не получает root `.env`; Docker build contexts
  исключают `.env*`.

## 9. Redis, Celery и логи

- Фактическая Celery-задача cleanup не принимает Page/Issue content; payload
  содержит только имя task, результат — числовые counters.
- В Redis не помещается decrypted content или encryption key.
- Cleanup логирует только случайное техническое имя обработанного файла, а не
  зашифрованный `original_name`.
- SQLAlchemy echo/request-body logging в приложении не включены.
- Worker и Beat валидируют encryption key при startup.
- Frontend analytics/audit log/search index в проекте отсутствуют.

## 10. Команды запуска

Один раз заполнить стабильный `DATA_ENCRYPTION_KEY` в `.env`, затем:

```bash
docker compose down --remove-orphans
docker compose up --build
```

Проверка:

```bash
docker compose ps
docker compose logs backend worker beat frontend
curl http://localhost:8000/health
```

Ручной backend:

```bash
cd backend
python -m pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload
```

## 11. Команды тестирования

```bash
cd backend
pytest -q -rs
ruff check .
ruff format --check .
python -m compileall -q app alembic tests
alembic heads
alembic history

cd ../frontend
npm ci
npm run typecheck
npm run lint
npm run build
npm audit --omit=dev
```

Выделенная PostgreSQL-проверка:

```bash
cd backend
NOKI_TEST_DATABASE_URL='postgresql+asyncpg://...' pytest -q -m postgres
```

Тест создаёт случайную отдельную schema, делает Task/Page INSERT/UPDATE/GET
через реальный FastAPI ASGI HTTP transport, читает raw BYTEA через SQL, проверяет
Upload, повторное шифрование одинакового plaintext, wrong key и tampering, затем
удаляет schema.

## 12. Фактические результаты

| Проверка | Запускалась | Результат |
| --- | :---: | --- |
| Backend pytest без PostgreSQL URL | Да | `95 passed, 1 skipped in 6.01s` |
| PostgreSQL raw test отдельно | Да | Setup error: `ConnectionDoesNotExistError`; test body не выполнен |
| Ruff check | Да | Passed |
| Ruff format check | Да | Passed |
| Python compileall | Да | Passed |
| Alembic heads/history | Да | Passed, одна head |
| Alembic upgrade clean PostgreSQL | Нет | Нет доступного PostgreSQL/Docker |
| Alembic upgrade existing DB | Нет | Нет доступного PostgreSQL/Docker |
| Alembic downgrade | Нет | Нет доступного PostgreSQL/Docker |
| Frontend TypeScript | Да | Passed |
| Frontend ESLint | Да | Passed |
| Frontend production build | Да | Passed, 11 routes |
| Frontend key scan source + `.next` | Да | Совпадений key identifier/test key нет |
| Docker Compose static YAML/invariants | Да | Passed |
| `docker compose down --remove-orphans` | Да | Не выполнен: `docker` command not found |
| `docker compose up --build` | Да | Не выполнен: `docker` command not found |
| `npm audit --omit=dev` | Да | Failed: 3 high transitive advisories |
| Browser/E2E interaction | Нет | Backend stack нельзя запустить без Docker/PostgreSQL/Redis |

### Каждый backend test case

Итоговый запуск собрал 96 test cases: 95 завершились успешно, один
PostgreSQL-тест был пропущен без выделенной тестовой PostgreSQL БД:

| Suite | Cases | Результат |
| --- | ---: | --- |
| `test_app` | 1 | 1 passed |
| `test_encryption` | 12 | 12 passed |
| `test_images` | 1 | 1 passed |
| `test_memberships` | 7 | 7 passed |
| `test_page_validation` | 19 | 19 passed |
| `test_postgres_encryption` | 1 | skipped в общем suite; отдельный запуск завершился setup error |
| `test_resource_rbac_integration` | 33 | 33 passed |
| `test_security` | 2 | 2 passed |
| `test_team_issue_integration` | 4 | 4 passed |
| `test_team_issue_rules` | 16 | 16 passed |

Покрыты owner/admin/member/outsider, field-level `403`, forbidden multi-field
atomicity, omitted/null assignee, deadline, assignee validation, claim `409`,
системные и custom statuses, Board/bulk restrictions, Issue/Page IDOR, Page
author-or-manager, Upload association integrity, wrong key/tampering/nonce и
отсутствие legacy plaintext columns в моделях.

## 13. Raw PostgreSQL — честный вывод

Код raw PostgreSQL-теста добавлен и отдельный запуск был предпринят с
настроенным локальным target `localhost:5432`. Соединение было закрыто сервером
во время setup:

```text
RuntimeError: Dedicated PostgreSQL encryption test database is unavailable
or cannot create an isolated schema (ConnectionDoesNotExistError)
```

Поэтому в этой среде не подтверждены:

- фактические raw BYTEA в запущенном PostgreSQL;
- отсутствие контрольных plaintext-строк в реальной БД;
- clean upgrade, upgrade поверх `0001`, downgrade;
- health/docs/worker/beat/frontend в Compose;
- отсутствие plaintext в runtime logs.

На уровне кода и SQLite integration подтверждены отсутствие legacy plaintext
attributes/columns в текущих моделях, AES-GCM round-trip, random nonce,
tamper/wrong-key fail-closed и API decryption. Это не подменяет raw PostgreSQL
proof.

Даже после успешной логической миграции `DROP COLUMN` не гарантирует мгновенное
физическое стирание старых bytes из heap/WAL/backups. Для production после
проверенного backup/restore нужны политика retention/rotation WAL и backups и,
при требовании физического уничтожения, отдельная согласованная DBA-процедура.

## 14. Оставшиеся ограничения

- `npm audit --omit=dev` сообщает 3 high advisories в transitive
  `next/postcss/sharp`. Dry-run показывает, что автоматический force-fix
  заменил бы Next на несовместимую major-версию; это нарушило бы запрет на
  замену стека, поэтому destructive `npm audit fix --force` не выполнялся.
- Инварианты parent Space membership для TeamMember и Team membership для
  Task assignee обеспечиваются permission service и транзакционными locks, но
  не составным FK/trigger в PostgreSQL; ручной SQL в обход приложения может
  создать несогласованность.
- PostgreSQL BYTEA не ограничивает длину `LargeBinary(12/16)` на уровне типа.
  Decryptor проверяет длину nonce/tag и fail-closed, но отдельные DB check
  constraints могут быть дополнительным hardening.
- Реальный `.env` не изменялся, ключ не генерировался и не ротировался.

## 15. Финальное состояние исходной папки

Все исправления внесены непосредственно в исходные файлы проекта.
Архив, JUnit XML, каталоги зависимостей и сборки, Python/pytest/Ruff caches,
`*.egg-info` и `*.tsbuildinfo` удалены после финальной проверки.

Сохранены `.git`, реальный `.env`, исходники, миграции, тесты, lock-файл,
README, этот отчёт и каталог `backend/storage`, предназначенный для
пользовательских загрузок.
