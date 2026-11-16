# Обновление production

Все процессы используют один корневой `.env`. Frontend собирается без
отдельного env-файла и по умолчанию обращается к same-origin `/api/v1`.

Перед `make pm2-check` обновите `EXPECTED_DB_REVISION` в корневом
`.env` до `0026_totp`. Миграции 0025 и 0026 добавляют необязательные поля
сессий и TOTP. Существующие аккаунты и сессии не удаляются.
Администратору нужно включить TOTP в настройках перед следующим изменением
пользователей через админ-панель.

```bash
git pull --ff-only
backend/.venv/bin/python -m pip install --disable-pip-version-check --upgrade ./backend
npm --prefix frontend ci
npm --prefix frontend run build:production
make pm2-check
make BACKUP_CONFIRMED=YES pm2-migrate
make pm2-backfill
# Перезапускаем уже настроенные на сервере процессы PM2, сохраняя их команды и порты.
pm2 restart noki-api --update-env
pm2 restart noki-worker --update-env
pm2 restart noki-mail-worker --update-env
pm2 restart noki-beat --update-env
pm2 restart noki-frontend --update-env
pm2 status
pm2 save
```

После запуска должны быть online пять процессов:

- `noki-api` — Uvicorn на `127.0.0.1:8010`;
- `noki-worker` — основная очередь `celery`;
- `noki-mail-worker` — очередь `mail_queue`;
- `noki-beat` — периодические служебные задачи;
- `noki-frontend` — Next.js на `127.0.0.1:3015`.

Billing worker больше не существует. Если миграция или backfill завершились
ошибкой, не перезапускайте старые процессы до устранения причины.

Проверка после обновления:

```bash
curl --fail --silent http://127.0.0.1:8010/live
curl --fail --silent http://127.0.0.1:8010/health
curl --fail --silent http://127.0.0.1:3015/
```
