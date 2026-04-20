# ABOUTME: Dev workflow automation — start stack, run tests, seed DB, lint.
# ABOUTME: Targets: dev, reset, seed, install, test-unit-api, test-integration-api, lint.

.PHONY: dev reset seed install test-unit-api test-integration-api lint

## Start Docker services, run migrations, and seed the database.
## Then run API and web servers manually (see output for commands).
dev:
	docker compose up -d
	@echo "Waiting for Postgres..."
	@until docker compose exec -T postgres pg_isready -U templehe -d templehe > /dev/null 2>&1; do sleep 1; done
	cd api && uv run alembic upgrade head
	$(MAKE) seed
	@echo ""
	@echo "Stack ready. Start servers:"
	@echo "  API:   cd api && uv run uvicorn main:app --reload --port 8000"
	@echo "  Web:   cd web && npm run dev"
	@echo "  Email: http://localhost:8025"

## Tear down all volumes and rebuild the stack from scratch.
reset:
	docker compose down -v
	$(MAKE) dev

## Seed the database with roles, categories, and defaults (idempotent).
seed:
	cd api && DATABASE_URL=$${DATABASE_URL:-postgresql+asyncpg://templehe:devpassword@localhost:5432/templehe} \
		uv run python ../scripts/seed.py

## Install Python and Node dependencies.
install:
	cd api && uv sync
	cd web && npm install

## Run API unit tests with 85% coverage gate.
test-unit-api:
	cd api && uv run pytest tests/unit/ -v \
		--cov=. --cov-report=term-missing --cov-fail-under=85 \
		--ignore=tests/integration

## Run API integration tests against the test database.
test-integration-api:
	cd api && uv run pytest tests/integration/ -v

## Lint Python (ruff) and TypeScript (eslint).
lint:
	cd api && uv run ruff check . && uv run ruff format --check .
	cd web && npm run lint
