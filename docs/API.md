# Noki Public API

Public API — это версионированный REST-интерфейс для серверных интеграций с Noki. Он позволяет получать структуру рабочих пространств, читать и изменять задачи, а также работать с комментариями.

API не является анонимным. Для запросов нужен персональный API-токен (PAT), созданный пользователем Noki. Токен действует от имени этого пользователя и не расширяет его права.

## Базовый адрес

```text
Production: https://noki.example/api/public/v1
Локально:   http://localhost:8000/api/public/v1
```

Во всех примерах замените `noki.example` на домен своей установки Noki.

Все тела запросов и ответов используют JSON в UTF-8. В production используйте только HTTPS.

## Первый токен

PAT создаётся в браузерном API `/api/v1`. Оно использует обычную сессию Noki: access cookie и CSRF cookie. Сам PAT не может создавать или отзывать другие PAT.

### Через веб-интерфейс

Откройте DevTools на странице своей установки Noki и выполните код в Console. Делайте это только на собственном домене Noki; не вставляйте такой код на чужих сайты.

```js
const csrfCookie = document.cookie
  .split("; ")
  .find((value) => value.startsWith("noki_csrf="));

if (!csrfCookie) {
  throw new Error("CSRF cookie noki_csrf not found");
}

const csrfToken = decodeURIComponent(
  csrfCookie.slice("noki_csrf=".length),
);
const response = await fetch("/api/v1/api-tokens", {
  method: "POST",
  credentials: "same-origin",
  headers: {
    "Content-Type": "application/json",
    "X-CSRF-Token": csrfToken,
  },
  body: JSON.stringify({
    name: "My integration",
    scopes: ["write"],
    expires_in_days: 90,
  }),
});
const data = await response.json();

if (!response.ok) {
  throw new Error(
    typeof data.detail === "string"
      ? data.detail
      : `HTTP ${response.status}`,
  );
}

console.log(data.token);
```

Полное значение нового PAT появится в Console только один раз. Сразу перенесите его в защищённое хранилище.

### Через Python-скрипт

Установите зависимость:

```bash
python -m pip install requests
```

Задайте переменные окружения:

```bash
export NOKI_ORIGIN="https://noki.example"
export NOKI_EMAIL="user@example.com"
export NOKI_PASSWORD="your-password"
```

Скрипт:

```python
import os
import requests

origin = os.environ["NOKI_ORIGIN"].rstrip("/")
email = os.environ["NOKI_EMAIL"]
password = os.environ["NOKI_PASSWORD"]

with requests.Session() as session:
    login = session.post(
        f"{origin}/api/v1/auth/login",
        json={"email": email, "password": password},
        timeout=15,
    )
    login.raise_for_status()

    csrf_token = session.cookies.get("noki_csrf")
    if not csrf_token:
        raise RuntimeError("Noki did not return the CSRF cookie")

    created = session.post(
        f"{origin}/api/v1/api-tokens",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "name": "My integration",
            "scopes": ["write"],
            "expires_in_days": 90,
        },
        timeout=15,
    )
    created.raise_for_status()

    token = created.json()["token"]
    print(token)
```

Полное значение `token` возвращается только при создании. Сохраните его в менеджере секретов или в защищённой переменной окружения. Получить это значение повторно нельзя.

Поле `expires_in_days` принимает целое число от 1 до 365. Значение по умолчанию — 90 дней.

### Через вход в Google

Если аккаунт создан только через Google и у него нет пароля Noki, PAT можно выпустить из уже авторизованной браузерной сессии. Используйте первый вариант с Console в браузере, где вы уже авторизованы через Google.

## Управление токенами через Public API

После создания первого PAT вы можете управлять токенами напрямую через Public API, без браузерной сессии и CSRF.

### Список токенов

```bash
curl --fail-with-body --silent --show-error \
  -H "Authorization: Bearer $NOKI_API_TOKEN" \
  "$NOKI_API_URL/api-tokens"
```

Ответ — JSON-массив:

```json
[
  {
    "id": "fd36a4ab-09b9-4dda-8b1a-dfe341aed67a",
    "name": "My integration",
    "prefix": "noki_pat_a1b2c3d4",
    "scopes": ["read", "write"],
    "expires_at": "2026-11-13T08:00:00Z",
    "last_used_at": null,
    "created_at": "2026-08-15T08:00:00Z"
  }
]
```

В списке возвращается только безопасный `prefix`, а не полный секрет.

### Создание токена

```bash
curl --fail-with-body --silent --show-error \
  -X POST \
  -H "Authorization: Bearer $NOKI_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "New integration",
    "scopes": ["write"],
    "expires_in_days": 90
  }' \
  "$NOKI_API_URL/api-tokens"
```

Ответ `201`:

```json
{
  "id": "fd36a4ab-09b9-4dda-8b1a-dfe341aed67a",
  "name": "New integration",
  "prefix": "noki_pat_a1b2c3d4",
  "scopes": ["read", "write"],
  "expires_at": "2026-11-13T08:00:00Z",
  "last_used_at": null,
  "created_at": "2026-08-15T08:00:00Z",
  "token": "noki_pat_..."
}
```

Полное значение `token` возвращается только при создании. Сохраните его сразу.

### Отзыв токена

```bash
curl --fail-with-body --silent --show-error \
  -X DELETE \
  -H "Authorization: Bearer $NOKI_API_TOKEN" \
  "$NOKI_API_URL/api-tokens/fd36a4ab-09b9-4dda-8b1a-dfe341aed67a"
```

Ответ:

```json
{"message":"API token revoked"}
```

Запись удаляется окончательно. Сразу после успешного `DELETE` запросы с этим секретом получают `401 invalid_token`.

### Управление токенами через браузерный API

Эти маршруты относятся к браузерному API и требуют обычную сессию Noki:

| Метод | Путь | CSRF | Назначение |
| --- | --- | --- | --- |
| `GET` | `/api/v1/api-tokens` | Нет | Список действующих токенов текущего пользователя |
| `POST` | `/api/v1/api-tokens` | Да | Создать токен |
| `DELETE` | `/api/v1/api-tokens/{token_id}` | Да | Удалить токен |

## Авторизация и безопасность

Передавайте PAT только в заголовке `Authorization`:

```http
Authorization: Bearer noki_pat_...
```

Public API принимает только PAT с префиксом `noki_pat_`. Браузерные cookies, access JWT и refresh JWT не заменяют PAT. Для запросов к `/api/public/v1` CSRF-заголовок не нужен.

Доступны два scope:

| Scope | Возможности |
| --- | --- |
| `read` | Чтение пользователя, пространств, команд, участников, досок, задач и комментариев |
| `write` | Создание и изменение задач, изменение статуса, назначение задачи себе и создание комментариев; автоматически включает `read` |

Scope ограничивает токен, но не меняет роли пользователя в Noki. Например, токен со scope `write`, созданный обычным участником команды, не получает права администратора команды.

Правила хранения токена:

- не помещайте PAT в URL, query string или логи;
- не добавляйте PAT в браузерный JavaScript, React-клиент или мобильное приложение без защищённого backend;
- храните PAT в переменной окружения или менеджере секретов;
- создавайте отдельный PAT для каждой интеграции;
- отзывайте токен, если он попал в открытый доступ;
- смена пароля пользователя делает ранее выпущенные PAT недействительными;
- блокировка пользователя, истечение срока или отзыв PAT сразу закрывают доступ.

## Права доступа

PAT выполняет запросы от имени создавшего его пользователя. Действуют те же правила, что и в интерфейсе Noki:

- Space owner и Space admin видят команды и ресурсы всего пространства;
- Space member видит только команды, в которых состоит напрямую;
- Team owner, Team admin, Space owner и Space admin могут создавать задачи и менять все их поля;
- обычный Team member не может использовать общий `PATCH /tasks/{task_id}`;
- прямой участник команды может назначить себе свободную задачу через `POST /tasks/{task_id}/claim`;
- обычный участник может менять системный статус только у задачи, назначенной ему, и только когда текущая колонка задачи тоже является системной;
- пользователь, который видит задачу, может читать и создавать комментарии;
- недоступный ресурс обычно возвращается как `404`, чтобы не раскрывать его существование.

## Идентификаторы и даты

Основные идентификаторы имеют формат UUID:

```text
34cdb419-5d4c-4e37-b7ea-45d272f61e1f
```

Поле задачи `code`, например `OPS-17`, предназначено для отображения. Оно не является глобально уникальным: ключ доски уникален только внутри команды. Public API не поддерживает получение задачи по `code`.

Все даты передаются в ISO 8601. Для входных полей `deadline` и `updated_after` часовой пояс обязателен:

```text
2026-08-20T18:00:00+05:00
2026-08-20T13:00:00Z
```

Сервер хранит даты в UTC. Клиент должен уметь принимать как суффикс `Z`, так и смещение `+00:00`.

## OpenAPI

Описание Public API доступно без авторизации:

```text
GET /api/public/v1/openapi.json
```

Корневой маршрут также не требует токена:

```text
GET /api/public/v1
```

Ответ:

```json
{
  "name": "Noki Public API",
  "version": "1.0.0",
  "openapi_url": "/api/public/v1/openapi.json"
}
```

OpenAPI содержит Bearer-схему `NokiApiToken` и может использоваться для генерации клиента. Отдельный публичный Swagger UI не предоставляется.

## Формат ошибок

Ошибки, которые приложение Noki формирует для маршрутов `/api/public/v1`, имеют единый формат:

```json
{
  "error": {
    "code": "not_found",
    "message": "Task not found",
    "request_id": "b79f8b3e-81f4-43b8-8acf-cf72eb16e027"
  }
}
```

Ошибка валидации дополнительно содержит `details`:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed",
    "details": [
      {
        "type": "string_too_short",
        "loc": ["body", "title"],
        "msg": "String should have at least 1 character"
      }
    ],
    "request_id": "b79f8b3e-81f4-43b8-8acf-cf72eb16e027"
  }
}
```

Основные коды:

| HTTP | `error.code` | Значение |
| --- | --- | --- |
| `400` | `bad_request` | Некорректное состояние или связанный идентификатор |
| `401` | `invalid_token` | Токен отсутствует, неверен, истёк или отозван |
| `403` | `forbidden` | Не хватает scope или прав пользователя |
| `404` | `not_found` | Ресурс не найден или недоступен |
| `405` | `method_not_allowed` | Метод не поддерживается |
| `408` | `request_timeout` | Клиент не успел передать тело запроса |
| `409` | `conflict` | Конфликт состояния или достигнут лимит ресурса |
| `413` | `payload_too_large` | Тело запроса превышает допустимый размер |
| `422` | `validation_error` | Неверные типы или поля запроса |
| `429` | `rate_limit_exceeded` | Превышен лимит запросов |
| `500` | `internal_error` | Внутренняя ошибка, которую обработало приложение |
| `504` | `request_timeout` | Превышено время обработки запроса |

Ответ reverse proxy, CDN или другой инфраструктуры может иметь другое тело. Необработанная ошибка 5xx также не обязана содержать этот envelope. Сначала проверяйте HTTP-код, затем наличие объекта `error`.

Ответ, сформированный приложением Noki, содержит `X-Request-ID`. Сохраняйте его вместе с HTTP-кодом для диагностики. Клиент может передать свой идентификатор длиной до 128 символов в одноимённом заголовке. Допустимы латинские буквы, цифры и символы `.`, `_`, `:`, `-`; первый символ должен быть буквой или цифрой. Инфраструктура перед Noki может заменить заголовок или вернуть ответ без него.

## Ограничение частоты запросов

Стандартные настройки Public API:

- 600 запросов в минуту на PAT;
- 1200 запросов в минуту на IP-адрес.

Администратор установки может изменить эти значения. При превышении лимита сервер отвечает `429` и передаёт число секунд до следующей попытки в заголовке `Retry-After`.

Public API не возвращает заголовки с остатком лимита. Не отправляйте запрос на каждый элемент, если данные можно получить списком.

## Пагинация

Списки задач и комментариев используют `limit` и `offset`.

Ответ:

```json
{
  "items": [],
  "total": 0,
  "limit": 50,
  "offset": 0
}
```

Для задач:

- `limit`: от 1 до 100, по умолчанию 50;
- `offset`: от 0 до 100000;
- порядок: `updated_at`, затем `id`, по возрастанию.

Для комментариев:

- `limit`: от 1 до 100, по умолчанию 50;
- `offset`: от 0 до 10000;
- порядок: `created_at`, затем `id`, по возрастанию.

Следующая страница существует, если `offset + len(items) < total`. Поле `total` может измениться между запросами, если другие пользователи создают или обновляют данные.

## Маршруты

| Метод | Путь | Scope | Назначение |
| --- | --- | --- | --- |
| `GET` | `/me` | `read` | Текущий пользователь |
| `GET` | `/spaces` | `read` | Доступные пространства |
| `GET` | `/spaces/{space_id}/teams` | `read` | Доступные команды пространства |
| `GET` | `/teams/{team_id}/members` | `read` | Участники команды и права текущего пользователя |
| `GET` | `/teams/{team_id}/boards` | `read` | Доски команды |
| `GET` | `/boards/{board_id}` | `read` | Доска и её колонки, без задач |
| `GET` | `/tasks` | `read` | Поиск и постраничный список задач |
| `POST` | `/tasks` | `write` | Создать задачу |
| `GET` | `/tasks/{task_id}` | `read` | Получить задачу |
| `PATCH` | `/tasks/{task_id}` | `write` | Изменить поля задачи |
| `PATCH` | `/tasks/{task_id}/status` | `write` | Изменить системный статус |
| `POST` | `/tasks/{task_id}/claim` | `write` | Назначить свободную задачу себе |
| `GET` | `/tasks/{task_id}/comments` | `read` | Список комментариев |
| `POST` | `/tasks/{task_id}/comments` | `write` | Создать комментарий |
| `GET` | `/todos` | `read` | Список личных задач текущего пользователя |
| `GET` | `/todos/{todo_id}` | `read` | Получить личную задачу |
| `POST` | `/todos` | `write` | Создать личную задачу |
| `PATCH` | `/todos/{todo_id}` | `write` | Изменить личную задачу |
| `DELETE` | `/todos/{todo_id}` | `write` | Удалить личную задачу |
| `GET` | `/api-tokens` | `read` | Список действующих PAT текущего пользователя |
| `POST` | `/api-tokens` | `write` | Создать PAT |
| `DELETE` | `/api-tokens/{token_id}` | `write` | Удалить PAT |

Во всех путях таблицы подразумевается базовый адрес `/api/public/v1`.

## Проверка токена

```bash
export NOKI_API_URL="https://noki.example/api/public/v1"
export NOKI_API_TOKEN="noki_pat_..."

curl --fail-with-body --silent --show-error \
  -H "Authorization: Bearer $NOKI_API_TOKEN" \
  -H "Accept: application/json" \
  "$NOKI_API_URL/me"
```

Пример ответа:

```json
{
  "id": "9a1ac744-2a68-4f10-af84-b5f96363caa7",
  "email": "user@example.com",
  "name": "Иван Петров",
  "avatar_url": null,
  "timezone": "Asia/Tashkent"
}
```

## Пространства, команды и доски

Получение пространств:

```bash
curl --fail-with-body --silent --show-error \
  -H "Authorization: Bearer $NOKI_API_TOKEN" \
  "$NOKI_API_URL/spaces"
```

Ответ — JSON-массив:

```json
[
  {
    "id": "8f82e09c-b740-496a-88c5-770eea999e9f",
    "name": "Отдел продаж",
    "created_at": "2026-08-01T07:30:00Z",
    "updated_at": "2026-08-01T07:30:00Z"
  }
]
```

Получение команд и досок:

```bash
export NOKI_SPACE_ID="8f82e09c-b740-496a-88c5-770eea999e9f"
export NOKI_TEAM_ID="5c24a091-f290-49bd-b1da-c694a1c6f992"

curl --fail-with-body --silent --show-error \
  -H "Authorization: Bearer $NOKI_API_TOKEN" \
  "$NOKI_API_URL/spaces/$NOKI_SPACE_ID/teams"

curl --fail-with-body --silent --show-error \
  -H "Authorization: Bearer $NOKI_API_TOKEN" \
  "$NOKI_API_URL/teams/$NOKI_TEAM_ID/boards"
```

Получение доски с колонками:

```bash
export NOKI_BOARD_ID="a8983bb6-6f72-4e68-819b-36634b20a06e"

curl --fail-with-body --silent --show-error \
  -H "Authorization: Bearer $NOKI_API_TOKEN" \
  "$NOKI_API_URL/boards/$NOKI_BOARD_ID"
```

Ответ:

```json
{
  "id": "a8983bb6-6f72-4e68-819b-36634b20a06e",
  "team_id": "5c24a091-f290-49bd-b1da-c694a1c6f992",
  "name": "Сделки",
  "key": "SAL",
  "columns": [
    {
      "id": "f221a0c8-98ed-4e97-9a5f-ecb575238602",
      "name": "Todo",
      "position": 0,
      "system_status": "todo",
      "color": null,
      "is_default": true
    },
    {
      "id": "75f61df5-b04c-490f-8658-b836ca2fd602",
      "name": "In Progress",
      "position": 1,
      "system_status": "in_progress",
      "color": "#3B82F6",
      "is_default": false
    }
  ],
  "created_at": "2026-08-01T08:00:00Z",
  "updated_at": "2026-08-10T12:00:00Z"
}
```

`system_status` принимает `todo`, `in_progress`, `done` или `null` для пользовательской колонки.

Участники команды:

```bash
curl --fail-with-body --silent --show-error \
  -H "Authorization: Bearer $NOKI_API_TOKEN" \
  "$NOKI_API_URL/teams/$NOKI_TEAM_ID/members"
```

Ответ содержит `members`, роли `owner`, `admin`, `member` и флаги прав текущего пользователя.

## Задачи

### Список и фильтры

```http
GET /tasks
```

Доступные query-параметры:

| Параметр | Тип | Значение |
| --- | --- | --- |
| `board_id` | UUID | Только задачи указанной доски |
| `team_id` | UUID | Только задачи указанной команды |
| `status_id` | UUID | Только задачи указанной колонки |
| `assignee_id` | UUID | Только задачи указанного исполнителя |
| `updated_after` | ISO 8601 | Нижняя граница по `updated_at`; без `updated_after_id` граница включается |
| `updated_after_id` | UUID | ID последней обработанной задачи для точного курсора `(updated_at, id)` |
| `limit` | integer | От 1 до 100, по умолчанию 50 |
| `offset` | integer | От 0 до 100000, по умолчанию 0 |

Все переданные фильтры объединяются условием AND.

Неизвестные query-параметры FastAPI может игнорировать, поэтому используйте только перечисленные имена. Неизвестные поля в JSON-теле запрещены и возвращают `422`.

`updated_after_id` можно передавать только вместе с `updated_after`; иначе сервер возвращает `422`. Если передан только `updated_after`, задачи на самой временной границе включаются через `>=`. Это может вернуть уже обработанные элементы, но не пропускает задачи с одинаковым временем изменения. Если переданы оба значения, сервер выбирает задачи строго после пары `(updated_after, updated_after_id)` в порядке `(updated_at, id)`.

Пример продолжения polling после последней обработанной задачи:

```bash
curl --fail-with-body --silent --show-error --get \
  -H "Authorization: Bearer $NOKI_API_TOKEN" \
  --data-urlencode "updated_after=2026-08-15T07:25:00Z" \
  --data-urlencode "updated_after_id=34cdb419-5d4c-4e37-b7ea-45d272f61e1f" \
  --data-urlencode "limit=100" \
  --data-urlencode "offset=0" \
  "$NOKI_API_URL/tasks"
```

Пример:

```bash
curl --fail-with-body --silent --show-error --get \
  -H "Authorization: Bearer $NOKI_API_TOKEN" \
  --data-urlencode "board_id=$NOKI_BOARD_ID" \
  --data-urlencode "updated_after=2026-08-01T00:00:00Z" \
  --data-urlencode "limit=50" \
  --data-urlencode "offset=0" \
  "$NOKI_API_URL/tasks"
```

Ответ:

```json
{
  "items": [
    {
      "id": "34cdb419-5d4c-4e37-b7ea-45d272f61e1f",
      "board_id": "a8983bb6-6f72-4e68-819b-36634b20a06e",
      "status_id": "f221a0c8-98ed-4e97-9a5f-ecb575238602",
      "number": 17,
      "code": "SAL-17",
      "title": "Подготовить договор",
      "description": "Проверить реквизиты клиента",
      "assignee": {
        "id": "9a1ac744-2a68-4f10-af84-b5f96363caa7",
        "name": "Иван Петров",
        "email": "user@example.com",
        "avatar_url": null
      },
      "created_by": {
        "id": "35d6148e-c014-49d8-b8d6-94393b29c810",
        "name": "Анна Смирнова",
        "email": "anna@example.com",
        "avatar_url": null
      },
      "deadline": "2026-08-20T13:00:00Z",
      "position": 3,
      "created_at": "2026-08-15T07:20:00Z",
      "updated_at": "2026-08-15T07:25:00Z"
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

### Создание задачи

```http
POST /tasks
```

Тело запроса:

| Поле | Обязательно | Ограничения |
| --- | --- | --- |
| `board_id` | Да | UUID доступной доски |
| `title` | Да | От 1 до 200 символов |
| `description` | Нет | До 5000 символов, по умолчанию пустая строка |
| `assignee_id` | Нет | UUID активного прямого участника команды или `null` |
| `deadline` | Нет | ISO 8601 с часовым поясом или `null` |
| `status_id` | Нет | UUID колонки этой доски или `null` |

Если `status_id` не передан, используется колонка доски по умолчанию. Новая задача может не иметь исполнителя.

```bash
curl --fail-with-body --silent --show-error \
  -X POST \
  -H "Authorization: Bearer $NOKI_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "board_id": "$NOKI_BOARD_ID",
    "title": "Подготовить договор",
    "description": "Проверить реквизиты клиента",
    "deadline": "2026-08-20T18:00:00+05:00",
    "assignee_id": null
  }' \
  "$NOKI_API_URL/tasks"
```

Успешный ответ имеет код `201` и содержит объект задачи из примера выше.

### Изменение задачи

```http
PATCH /tasks/{task_id}
```

Можно передать только изменяемые поля:

```json
{
  "title": "Подготовить и согласовать договор",
  "description": "Новая версия описания",
  "assignee_id": "9a1ac744-2a68-4f10-af84-b5f96363caa7",
  "deadline": "2026-08-21T12:00:00Z",
  "status_id": "75f61df5-b04c-490f-8658-b836ca2fd602"
}
```

Отсутствующее поле не изменяется. `assignee_id: null` снимает исполнителя, `deadline: null` очищает срок, а `description: null` очищает описание. `title: null` и `status_id: null` не допускаются.

```bash
export NOKI_TASK_ID="34cdb419-5d4c-4e37-b7ea-45d272f61e1f"

curl --fail-with-body --silent --show-error \
  -X PATCH \
  -H "Authorization: Bearer $NOKI_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"deadline":null,"assignee_id":null}' \
  "$NOKI_API_URL/tasks/$NOKI_TASK_ID"
```

### Системный статус

```http
PATCH /tasks/{task_id}/status
```

```bash
curl --fail-with-body --silent --show-error \
  -X PATCH \
  -H "Authorization: Bearer $NOKI_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status":"in_progress"}' \
  "$NOKI_API_URL/tasks/$NOKI_TASK_ID/status"
```

Поле `status` принимает `todo`, `in_progress` или `done`. Сервер находит системную колонку с таким статусом. Для перемещения в пользовательскую колонку manager должен использовать общий `PATCH /tasks/{task_id}` и передать `status_id`.

### Назначение задачи себе

```http
POST /tasks/{task_id}/claim
```

Тело запроса отсутствует:

```bash
curl --fail-with-body --silent --show-error \
  -X POST \
  -H "Authorization: Bearer $NOKI_API_TOKEN" \
  "$NOKI_API_URL/tasks/$NOKI_TASK_ID/claim"
```

Операция доступна прямому участнику команды. Она назначает текущего пользователя только на свободную задачу. Если исполнитель уже установлен, сервер отвечает `409`.

## Комментарии

Получение комментариев:

```bash
curl --fail-with-body --silent --show-error --get \
  -H "Authorization: Bearer $NOKI_API_TOKEN" \
  --data-urlencode "limit=50" \
  --data-urlencode "offset=0" \
  "$NOKI_API_URL/tasks/$NOKI_TASK_ID/comments"
```

Ответ:

```json
{
  "items": [
    {
      "id": "9798c17f-769b-4d5a-ac44-adb70a795e1c",
      "task_id": "34cdb419-5d4c-4e37-b7ea-45d272f61e1f",
      "body": "Договор отправлен на согласование",
      "created_by": {
        "id": "9a1ac744-2a68-4f10-af84-b5f96363caa7",
        "name": "Иван Петров",
        "email": "user@example.com",
        "avatar_url": null
      },
      "created_at": "2026-08-15T09:00:00Z",
      "updated_at": "2026-08-15T09:00:00Z"
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

Создание комментария:

```bash
curl --fail-with-body --silent --show-error \
  -X POST \
  -H "Authorization: Bearer $NOKI_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"body":"Договор отправлен на согласование"}' \
  "$NOKI_API_URL/tasks/$NOKI_TASK_ID/comments"
```

`body` содержит от 1 до 4000 символов. Пробелы в начале и конце удаляются. Успешный ответ имеет код `201`.

Public API не предоставляет изменение или удаление комментария.

## Личные задачи

### Список задач

```http
GET /todos
```

Ответ — JSON-массив:

```json
[
  {
    "id": "34cdb419-5d4c-4e37-b7ea-45d272f61e1f",
    "title": "Позвонить клиенту",
    "description": "Уточнить дату подписания",
    "deadline": "2026-08-20T18:00:00Z",
    "status": "done",
    "position": 0,
    "completed_by": {
      "id": "9a1ac744-2a68-4f10-af84-b5f96363caa7",
      "name": "Иван Петров",
      "email": "user@example.com",
      "avatar_url": null
    },
    "created_at": "2026-08-15T07:20:00Z",
    "updated_at": "2026-08-15T09:00:00Z"
  }
]
```

Поле `completed_by` заполняется, только если `status` равен `done`. В нём содержится пользователь, который последним изменил статус на `done`. Если задача не выполнена, поле равно `null`.

### Получение задачи

```http
GET /todos/{todo_id}
```

Ответ — объект задачи из примера выше.

### Создание задачи

```http
POST /todos
```

Тело запроса:

| Поле | Обязательно | Ограничения |
| --- | --- | --- |
| `title` | Да | От 1 до 200 символов |
| `description` | Нет | До 5000 символов, по умолчанию пустая строка |
| `deadline` | Нет | ISO 8601 с часовым поясом или `null` |
| `status` | Нет | `todo`, `in_progress` или `done`; по умолчанию `todo` |
| `position` | Нет | Целое число от 0, по умолчанию 0 |

```bash
curl --fail-with-body --silent --show-error \
  -X POST \
  -H "Authorization: Bearer $NOKI_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Позвонить клиенту",
    "description": "Уточнить дату подписания",
    "deadline": "2026-08-20T18:00:00+05:00",
    "status": "todo"
  }' \
  "$NOKI_API_URL/todos"
```

Успешный ответ имеет код `201` и содержит объект задачи.

### Изменение задачи

```http
PATCH /todos/{todo_id}
```

Можно передать только изменяемые поля:

```json
{
  "title": "Позвонить клиенту и согласовать договор",
  "status": "done"
}
```

При изменении `status` на `done` поле `completed_by` автоматически заполняется текущим пользователем. При изменении `status` на любое другое значение `completed_by` очищается.

```bash
curl --fail-with-body --silent --show-error \
  -X PATCH \
  -H "Authorization: Bearer $NOKI_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status":"done"}' \
  "$NOKI_API_URL/todos/$NOKI_TODO_ID"
```

### Удаление задачи

```http
DELETE /todos/{todo_id}
```

```bash
curl --fail-with-body --silent --show-error \
  -X DELETE \
  -H "Authorization: Bearer $NOKI_API_TOKEN" \
  "$NOKI_API_URL/todos/$NOKI_TODO_ID"
```

Ответ:

```json
{"message":"Todo deleted"}
```

## Повторные запросы и синхронизация

Public API не реализует идемпотентность для `POST /tasks` и `POST /tasks/{task_id}/comments`. Если сервер создал объект, но клиент не получил ответ, автоматический повтор может создать дубликат.

Для интеграций:

- храните идентификатор исходного события и созданный UUID Noki;
- перед созданием проверяйте, было ли событие обработано;
- не считайте `X-Request-ID` ключом дедупликации;
- повторяйте `GET` после сетевой ошибки без ограничений;
- повторяйте `429` после паузы из `Retry-After`;
- для 5xx используйте ограниченное число повторов с увеличивающейся задержкой;
- не повторяйте создающий `POST`, пока не проверили внешний журнал дедупликации.

Offset-пагинация может сдвигаться при одновременных изменениях. Для периодической синхронизации используйте курсор из двух значений: `updated_after` равен `updated_at` последней обработанной задачи, а `updated_after_id` — её `id`. Каждый следующий запрос начинайте с `offset=0`, после полной обработки страницы переносите курсор на её последний элемент. Так сервер продолжит выборку строго после пары `(updated_at, id)`.

Если интеграция хранит только время, передавайте один `updated_after`. Сервер включит временную границу, поэтому потери задач с одинаковым `updated_at` не будет, но клиент должен удалять повторы по паре `id` и `updated_at`.

## Ограничения текущей версии

- Нет исходящих webhook из Noki.
- Нет `Idempotency-Key` и гарантий exactly-once.
- Нет получения задачи по `code`; используйте UUID.
- Нет полнотекстового поиска задач.
- Нет удаления задач через Public API.
- Нет изменения и удаления комментариев через Public API.
- Нет API для Pages и загрузок файлов.
- Нет создания и изменения пространств, команд, участников, досок и колонок.
- Лимиты задач, досок и комментариев действующей установки применяются и к Public API; при достижении лимита сервер возвращает `409`.

## Пример на Python

Установите `requests` и задайте `NOKI_API_URL`, `NOKI_API_TOKEN`, `NOKI_BOARD_ID`.

```python
import os
from collections.abc import Iterator
from typing import Any

import requests


class NokiClient:
    def __init__(self) -> None:
        self.base_url = os.environ["NOKI_API_URL"].rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {os.environ['NOKI_API_TOKEN']}",
                "Accept": "application/json",
            }
        )

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self.session.request(
            method,
            f"{self.base_url}{path}",
            timeout=15,
            **kwargs,
        )
        request_id = response.headers.get("X-Request-ID")
        try:
            data = response.json()
        except requests.exceptions.JSONDecodeError as exc:
            raise RuntimeError(
                f"Noki returned a non-JSON response; "
                f"HTTP {response.status_code}; request_id={request_id}"
            ) from exc
        if not response.ok:
            error = data.get("error", {}) if isinstance(data, dict) else {}
            message = error.get("message", f"HTTP {response.status_code}")
            request_id = error.get("request_id") or request_id
            raise RuntimeError(f"{message}; request_id={request_id}")
        return data

    def iter_tasks(self, *, board_id: str) -> Iterator[dict[str, Any]]:
        offset = 0
        while True:
            page = self.request(
                "GET",
                "/tasks",
                params={"board_id": board_id, "limit": 100, "offset": offset},
            )
            yield from page["items"]
            offset += len(page["items"])
            if offset >= page["total"] or not page["items"]:
                return


client = NokiClient()
board_id = os.environ["NOKI_BOARD_ID"]

task = client.request(
    "POST",
    "/tasks",
    json={
        "board_id": board_id,
        "title": "Позвонить клиенту",
        "description": "Уточнить дату подписания",
        "deadline": "2026-08-20T18:00:00+05:00",
    },
)
print(f"Создана задача {task['code']} с id={task['id']}")

for item in client.iter_tasks(board_id=board_id):
    print(item["code"], item["title"])
```

## Пример на server-side Node.js

Пример рассчитан на Node.js 18 или новее. Сохраните его в файл `noki_client.mjs` и запустите командой `node noki_client.mjs`: код использует top-level `await`. Не запускайте его в браузере: PAT попадёт пользователю в исходном коде или сетевых запросах.

```js
const baseUrl = process.env.NOKI_API_URL.replace(/\/$/, "");
const token = process.env.NOKI_API_TOKEN;
const boardId = process.env.NOKI_BOARD_ID;

async function noki(path, options = {}) {
  const response = await fetch(`${baseUrl}${path}`, {
    ...options,
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/json",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    },
    signal: AbortSignal.timeout(15_000),
  });

  const requestId = response.headers.get("x-request-id");
  const body = await response.text();
  let data;
  try {
    data = JSON.parse(body);
  } catch {
    throw new Error(
      `Noki returned a non-JSON response; HTTP ${response.status}; ` +
        `request_id=${requestId}`,
    );
  }
  if (!response.ok) {
    const error = data && typeof data === "object" ? data.error : null;
    const message = error?.message ?? `HTTP ${response.status}`;
    throw new Error(`${message}; request_id=${error?.request_id ?? requestId}`);
  }
  return data;
}

const task = await noki("/tasks", {
  method: "POST",
  body: JSON.stringify({
    board_id: boardId,
    title: "Проверить оплату",
    description: "Сверить платёж с выпиской",
  }),
});

await noki(`/tasks/${task.id}/comments`, {
  method: "POST",
  body: JSON.stringify({ body: "Задача создана из внутреннего сервиса" }),
});

console.log(task.code, task.id);
```

## Ротация токена

1. Создайте новый PAT с нужными scope и сроком действия.
2. Замените секрет в конфигурации интеграции, не отзывая старый PAT.
3. Выполните `GET /api/public/v1/me` с новым PAT и убедитесь, что ответ успешный.
4. После проверки отзовите старый PAT через `DELETE /api/public/v1/api-tokens/{token_id}`.
