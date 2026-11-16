.PHONY: \
	install-backend install-frontend \
	dev-backend dev-frontend \
	dev-db-check migrate migration \
	test lint typecheck build verify format \
	pm2-check pm2-migrate pm2-backfill

install-backend:
	cd backend && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"

install-frontend:
	cd frontend && npm ci

dev-backend:
	cd backend && .venv/bin/python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

dev-frontend:
	cd frontend && npm run dev

dev-db-check:
	cd backend && .venv/bin/python -c "from app.core.config import settings; assert settings.environment != 'production', 'Use the backup-gated make pm2-migrate target in production'"

migrate: dev-db-check
	cd backend && .venv/bin/python -m alembic upgrade head

migration: dev-db-check
	cd backend && .venv/bin/python -m alembic revision --autogenerate -m "$(name)"

test:
	cd backend && .venv/bin/python -m pytest -q

lint:
	cd backend && .venv/bin/python -m ruff check .
	cd frontend && npm run lint

typecheck:
	cd frontend && npm run typecheck

build:
	cd frontend && npm run build:production

verify:
	cd backend && .venv/bin/python -m pytest -q && .venv/bin/python -m ruff check . && .venv/bin/python -m ruff format --check .
	cd frontend && npm run verify

format:
	cd backend && .venv/bin/python -m ruff format .
	cd frontend && npm run format

pm2-check:
	node --check ecosystem.config.cjs
	node --check scripts/migrate-production.cjs
	node -e "require('./ecosystem.config.cjs')"
	node scripts/migrate-production.cjs --validate-only

pm2-migrate: pm2-check
	@test "$(BACKUP_CONFIRMED)" = "YES" || \
		(printf '%s\n' 'Set BACKUP_CONFIRMED=YES after verifying the PostgreSQL and upload backups.' && exit 1)
	node scripts/migrate-production.cjs --backup-confirmed

pm2-backfill:
	cd backend && .venv/bin/python -m app.cli backfill-production-data --batch-size 250
