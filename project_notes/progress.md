# Progress

## Phase 1 — Infrastructure & Auth (In Progress, started 2026-04-20)

### Sprint 1: Foundation — COMPLETE
- [x] docker-compose.yml (Postgres 15 + Mailpit)
- [x] Makefile (dev, reset, seed, install, test-unit-api, test-integration-api, lint)
- [x] .env.example (all secret keys documented)
- [x] .gitignore (fixed — uv.lock now committed per standards)
- [x] README.md (5-step quickstart)
- [x] api/pyproject.toml (uv + Python 3.12)
- [x] api/Dockerfile
- [x] api/config.py (pydantic-settings)
- [x] api/main.py (FastAPI scaffold with CORS + Sentry wiring)
- [x] api/database/base.py (async engine + session factory)
- [x] api/database/models.py (31 tables — all SQLAlchemy ORM models)
- [x] api/alembic.ini + api/alembic/env.py (async migration runner)
- [x] api/alembic/versions/001_init_schema.py (all tables + triggers + indexes)
- [x] api/tests/conftest.py (test DB fixtures, async client)
- [x] api/tests/integration/test_migrations.py (schema + trigger verification)
- [x] scripts/seed.py (idempotent — roles, 15 categories, app_config defaults, admin user)
- [x] web/ scaffold (Vite + React 18 + TypeScript strict + Tailwind + React Query)
- [x] web/Dockerfile + nginx.conf

### Sprint 2: Auth Flows — NOT STARTED
- [ ] api/routers/auth.py
- [ ] api/services/auth_service.py
- [ ] api/services/session_service.py (refresh tokens)
- [ ] api/services/email_service.py (SendGrid / Mailpit)
- [ ] api/middleware/auth.py (JWT decode + get_current_user)
- [ ] api/middleware/rate_limit.py (Postgres-backed)
- [ ] api/tests/unit/test_auth_service.py
- [ ] api/tests/integration/test_auth_flows.py
- [ ] web/e2e/phase1_auth.spec.ts (Playwright)

### Sprint 3: RBAC + Security Middleware — NOT STARTED
### Sprint 4: Health Check + Observability — NOT STARTED
### Sprint 5: CI/CD + Fly.io Configs — NOT STARTED

---

## Phase 2–8 — Not started
