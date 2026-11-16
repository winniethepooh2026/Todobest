# 🚀 Развертывание проекта

## 1. Подготовка сервера

Подключаемся к серверу и создаем рабочую директорию:

```bash
mkdir -p /var/nokiproj
cd /var/nokiproj
```

## 2. Настройка SSH и Git

Генерируем SSH-ключ:

```bash
ssh-keygen -t ed25519 -C "your_email@example.com"
```

Скопируйте сгенерированный публичный ключ и добавьте его в Git (Deploy Keys / SSH Keys).

Далее выполняем:

```bash
git pull
```

## 3. Настройка окружения

Создаем `.env` файл:

```bash
nano .env
```

Вставляем все необходимые переменные (файл будет предоставлен отдельно).

---

## 4. Установка PostgreSQL

Устанавливаем PostgreSQL:

```bash
sudo apt install postgresql postgresql-contrib
sudo systemctl status postgresql
```

### Создание пользователя:

```bash
sudo -u postgres createuser \
--port=5432 \
--login \
--pwprompt \
--no-superuser \
--no-createdb \
--no-createrole \
--no-replication \
--no-bypassrls \
Noki
```

### Создание базы данных:

```bash
sudo -u postgres createdb \
--port=5432 \
--owner=noki \
--encoding=UTF8 \
--template=template0 \
Noki
```

---

## 5. Установка Redis

```bash
sudo apt install redis-server
sudo systemctl enable redis-server
```

---

## 6. Celery

Celery устанавливается автоматически вместе с backend.

---

## 7. Настройка фронтенда

Frontend собирается без отдельного env-файла; по умолчанию используется same-origin API `/api/v1`.

Собираем фронтенд:

```bash
cd frontend
# билд (команда зависит от проекта, обычно npm run build)
```

---

## 8. Настройка backend

Переходим в папку backend:

```bash
cd ../backend
```

### Установка Python 3.13

```bash
sudo apt update
sudo apt install software-properties-common
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update
sudo apt install python3.13 python3.13-venv python3.13-dev
```

### Создание виртуального окружения

```bash
python3.13 -m venv .venv
source .venv/bin/activate
```

### Установка зависимостей

```bash
pip install .
```

---

## 9. Миграции Alembic

Alembic устанавливается вместе с backend.

Применяем миграции:

```bash
alembic upgrade head
```

---

## 10. Запуск проекта

```bash
pm2 start ecosystem.config.cjs
```

---

## 11. Настройка Nginx

В корне проекта уже есть конфиг:

```
nginx.conf
```

Используем его для настройки веб-сервера.

---

## 12. SSL сертификат

Устанавливаем Certbot и получаем SSL-сертификат:

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx
```

---

# ✅ Готово

После выполнения всех шагов проект должен быть полностью развернут и доступен.
