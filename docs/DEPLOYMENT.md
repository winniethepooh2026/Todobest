# Состояние продакшна Noki

Документ описывает, что фактически развёрнуто и как это работает. Пошаговые
инструкции — в [`PRODUCTION.md`](PRODUCTION.md), обновление релиза — в
[`../UPDATE.md`](../UPDATE.md).

Развёрнуто **12 сентября 2026**. Первый продакшн-деплой, база поднята с нуля.

## Адреса и топология

| | |
|---|---|
| Домен | **https://noki.click** (плюс `www.noki.click` → 301 на основной) |
| Сервер | `178.105.43.157`, Ubuntu 24.04.4 |
| Код | `/var/www/noki` |
| Служебный аккаунт | `noki` (системный, `HOME=/home/noki`) |
| Backend | `127.0.0.1:8010` |
| Frontend | `127.0.0.1:3010` |

Порты **не** дефолтные 8000/3000: на том же сервере живут другие проекты, и
:8000 занят backend'ом finrise.uz, :3001 и :3002 — их фронтендами. Наружу
Noki доступен только через nginx; 8010, 3010, 5432 и 6380 на внешнем
интерфейсе закрыты.

## Процессы

Четыре процесса под PM2 (`ecosystem.config.cjs`), все от пользователя `noki`:

| Процесс | Что делает |
|---|---|
| `noki-api` | Uvicorn, 1 worker, `--limit-concurrency 200`, access-log выключен |
| `noki-worker` | Celery worker, concurrency 1, `--max-tasks-per-child=100` |
| `noki-beat` | Celery Beat, расписание в `/var/lib/noki/celery` |
| `noki-frontend` | `next start` на 3010 |

PM2 запускается systemd-юнитом **`pm2-noki`** (`enabled`), состояние процессов
сохранено через `pm2 save` в `/home/noki/.pm2/dump.pm2` (права 600). После
перезагрузки сервера юнит поднимает всё сам через `pm2 resurrect`.

Суммарное потребление ~500 МБ.

## Инфраструктура

**PostgreSQL 18.6** из PGDG-репозитория (в apt Ubuntu 24.04 нужной версии нет),
слушает `127.0.0.1:5432`. База и роль `noki`; роль намеренно без `SUPERUSER`,
`CREATEDB`, `CREATEROLE`, `REPLICATION` и `BYPASSRLS`. Схема на ревизии
`0018_todo_completed_by`, 15 таблиц.

**Redis** — **отдельный инстанс на 6380**, юнит `redis-noki`, конфиг
`/etc/redis/redis-noki.conf`, данные в `/var/lib/redis-noki`, `maxmemory 256mb`,
политика `noeviction`. Системный Redis на 6379 не тронут: его уже используют
соседние приложения и он без пароля, а валидатор Noki требует пароль в
`REDIS_URL` — добавить пароль в общий инстанс означало бы сломать соседей.

**Node.js 24** и **pm2 7.0.3** установлены системно (в apt только Node 18, он не
проходит `engines` фронтенда). Раньше node существовал только внутри
`/root/.nvm` и пользователю `noki` был недоступен.

**nginx 1.24** проксирует `/api/` на 8010, всё остальное (включая `/media/*`,
которые Next сам проксирует на backend) — на 3010. Конфиги в репозитории:

- `nginx.conf` — рабочий HTTPS-конфиг (→ `/etc/nginx/sites-available/noki`);
- `nginx.initial.conf` — только :80, для первого выпуска сертификата;
- `nginx.http.conf` — объявления http-уровня (→ `/etc/nginx/conf.d/noki-http.conf`):
  `map` для WebSocket-upgrade и `limit_req_zone` для лимита на вход.

Две особенности этого сервера, которые обязательно учитывать при правке конфига:

1. `listen` указывает **конкретный IP** (`178.105.43.157:80/443`), потому что
   все остальные сайты объявлены так же. С `listen 80` nginx предпочёл бы более
   специфичный блок и запросы к noki.click ушли бы на чужой сайт.
2. **IPv6-слушателей нет** — у noki.click только A-запись. Лишний блок на
   `[::]:443` мог бы стать default для IPv6 и отдавать наш сертификат чужим
   доменам.

`http2` задаётся внутри `listen` (nginx 1.24 не понимает отдельную директиву
`http2 on`).

**TLS** — Let's Encrypt на `noki.click` + `www.noki.click`, метод webroot через
`/var/www/html`. Автопродление штатным `certbot.timer` (см. «Риски»).

**Диагностика наружу закрыта**: `/health`, `/live`, `/docs`, `/redoc`,
`/openapi.json` отдают 404. Снимать только по loopback.

**Логи** — `/var/log/noki/backend` и `/var/log/noki/frontend`, logrotate
(`/etc/logrotate.d/noki`): ежедневно, максимум 50 МБ, 14 копий, сжатие.

**Swap 4 ГБ** (`/swapfile`, `vm.swappiness=10`) добавлен при деплое: на сервере
7.6 ГБ памяти, из которых ~5 ГБ уже занято соседями, а swap отсутствовал вовсе.
Без него сборка Next.js уходила бы в OOM, и OOM-killer выбрал бы самый крупный
процесс — с большой вероятностью чужой.

## Что включено и что отключено

**Работает**: регистрация и вход по email с паролем (Argon2, JWT в HttpOnly
cookies), Google OAuth, Spaces/Teams/Boards/Issues/Pages, личные todo,
комментарии, публичный API, загрузка изображений в `/var/lib/noki/uploads`.

**Google OAuth включён.** Client ID и secret в `.env`, redirect URI —
`https://noki.click/api/v1/auth/google/callback` (путь жёстко проверяется
валидатором: `{api_v1_prefix}/auth/google/callback`, только https, без query и
fragment). Authorized JavaScript origins в Google Console не нужны: флоу
серверный, браузерный JS с Google напрямую не общается.

**Отключено осознанно:**

- **S3-хранилище аватаров** — все четыре `AWS_*` пустые. Google-аватары не
  импортируются, показываются инициалы. Это штатная ветка в коде.
- **ClamAV** — на хост не ставился. Антивирусная проверка вызывается только в
  цепочке загрузки аватара в S3, а она отключена, поэтому код
  `backend/app/services/antivirus.py` мёртв. Сам код не удалён: вырезать его —
  рефакторинг с задетыми тестами без выигрыша для работы.

## Секреты

Все в `/var/www/noki/.env` (chmod 600, владелец `noki`). `JWT_SECRET` и
`DATA_ENCRYPTION_KEY` сгенерированы прямо на сервере. Пароли инфраструктуры
продублированы в `/root/.noki-db-pass` и `/root/.noki-redis-pass` (chmod 600).

Frontend получает только публичные значения из allowlist
`ecosystem.config.cjs`; backend-секреты из корневого `.env` ему не передаются.

**Бэкапов пока нет.** Отдельно важно: `DATA_ENCRYPTION_KEY` существует в
единственном экземпляре. Без его копии в отдельном от базы месте зашифрованные
Pages и Issues не восстановить даже из корректного дампа PostgreSQL.

## Что было исправлено в коде перед деплоем

Контекст на случай вопросов «почему так»:

- `ecosystem.config.cjs` читает один корневой `.env`, использует стандартные
  порты 8010/3015 и не блокирует запуск preflight-проверками каталогов.
- Из `nginx.conf` убран публично проксируемый `/health`, который раскрывал
  состояние БД, Redis, storage и миграций.
- Ревизия `EXPECTED_DB_REVISION` синхронизирована на `0018_todo_completed_by`
  (расходилась: `0017` в шаблоне и тесте, `0012` в локальном env). Миграционный
  гейт отказывался работать при расхождении.
- Закрыты уязвимости зависимостей: `next` 16.2.12 → 16.3.5 (critical RCE),
  `@tiptap/*` 3.29.0 → 3.31.3, `sharp` → 0.35.4, `nanoid` → 3.3.18. Апгрейд
  tiptap потребовал overrides на `@tiptap/extensions`, `core` и `pm` — в 3.31
  пакеты переструктурированы и `extension-*` требуют одноимённой версии
  `@tiptap/extensions`. `npm audit --omit=dev --audit-level=high` → 0.
- Удалён каталог `backend/build/` — случайно закоммиченный артефакт setuptools
  (52 файла, устаревшая копия всего приложения), ломавший `ruff check`.
- `.env.local` с реальными продакшн-секретами был закоммичен в git (`.gitignore`
  покрывал `.env`, но не `.env.local`). Файл убран из индекса, шаблон
  расширен. **Секреты из истории git не удалены** — при деплое сгенерированы
  новые, старые значения больше нигде не используются, но в истории остаются.
- `UPDATE.md` переписан: прежняя версия предписывала `alembic upgrade head` и
  `pm2 restart` вручную, что обходит и backup-гейт, и проверку ревизии, и
  оставляет фронтенд со старым production build.

Ещё одна вещь исправлена на самом сервере: systemd потерял контроль над nginx —
сайты обслуживал «осиротевший» мастер-процесс в scope SSH-сессии, а
`nginx.service` числился `failed` и падал с `Address already in use`. nginx
возвращён под systemd (`cgroup: system.slice/nginx.service`).

## Риски и незакрытое

**Автопродление сертификата noki.click провалится около 11 ноября 2026.**
В `/etc/letsencrypt/renewal-hooks/` лежат глобальные `pre/stop-nginx.sh`
(`systemctl stop nginx`) и `post/start-nginx.sh`. Они останавливают nginx на
весь прогон продления. Нужны они только двум standalone-сертификатам соседних
проектов (`mail.saleprofit.dev`, `sudoteach.com`), но noki.click валидируется
через webroot и требует **работающий** nginx. Эта же схема, судя по всему, и
осиротила nginx-процесс.

Починка: перенести `pre_hook`/`post_hook` из глобальных hooks в
`/etc/letsencrypt/renewal/{mail.saleprofit.dev,sudoteach.com}.conf`, а
остальным сертификатам прописать `renew_hook = systemctl reload nginx`.
Изменение затрагивает продление чужих домейнов, поэтому ждёт решения владельца.
Текущий сертификат действует до **11 декабря 2026**.

**Бэкапы PostgreSQL и ключа шифрования не настроены** — отложено осознанно.

**Мониторинг не настроен.** Минимум, который стоит поднять: доступность HTTPS,
`/health` по loopback, счётчик перезапусков PM2, свободное место, возраст
бэкапа.

**Деплой выполнен rsync'ом** рабочего дерева, git-remote на сервере не
настроен. Для обновления через `git pull` понадобится deploy key.

Не относится к Noki, но замечено на сервере: `saleprofit.uz` и `sudoteach.com`
не продлевают сертификаты несколько прогонов; `mail.saleprofit.dev` отдаёт по
HTTPS чужой сертификат `devskill.saleprofit.dev`, потому что у него только
AAAA-запись, а его nginx-блок слушает лишь IPv4; `apache2.service` в `failed`
с мая (конфликт с nginx за :80, сервис не нужен).

## Диагностика

```bash
# всё от пользователя noki
sudo -u noki -H bash
export HOME=/home/noki

pm2 status
pm2 logs noki-api --lines 50
curl -sS http://127.0.0.1:8010/health     # ожидаем true по всем проверкам
curl -sS http://127.0.0.1:8010/live
curl -sSI http://127.0.0.1:3010/
```

```bash
# от root
systemctl status pm2-noki nginx postgresql redis-noki
sudo -u postgres psql -d noki -c "SELECT version_num FROM alembic_version"
certbot certificates --cert-name noki.click
```

## Приёмка после деплоя (пройдена)

- `/health` — `database`, `migrations`, `encryption`, `redis`, `storage` → `true`.
- Регистрация → 201, вход → 200; cookies `noki_access` и `noki_refresh` с
  `HttpOnly; Secure; SameSite=lax`, CSRF-cookie без `HttpOnly` (нужен для
  double-submit).
- `/refresh` и `/logout` с чужого Origin → 403; CORS-заголовок выдаётся только
  доверенному Origin. Сами `login` и `register` CSRF не требуют — у них нет
  сессии для подделки, это осознанный дизайн (`AuthCSRF` навешен только на
  `refresh` и `logout`).
- Celery worker отвечает `inspect ping`, Beat один.
- `/health`, `/live`, `/docs`, `/openapi.json` снаружи → 404.
- Внутренние порты снаружи закрыты, в логах нет секретов и трейсбеков.
- Google OAuth: `/api/v1/auth/google` → 302 на `accounts.google.com` с верными
  `client_id`, `redirect_uri` и `scope=openid email profile`; Google принимает
  запрос без `redirect_uri_mismatch`. Полный цикл входа нужно проверять руками.
- PM2: 4 процесса `online`, перезапуск через systemd проверен.
