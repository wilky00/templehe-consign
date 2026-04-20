# Progress

> **Note on sprints:** Sprints are internal implementation milestones within a phase — they do not require separate `/phase-start` planning sessions. The full spec for all sprints in a phase lives in the phase's `dev_plan/` file. Run `/phase-start` once at the beginning of a phase, then work through sprints sequentially.

---

## Phase 1 — Infrastructure & Auth (In Progress, started 2026-04-20)

Full spec: `dev_plan/01_phase1_infrastructure_auth.md`

### Sprint 1: Foundation — COMPLETE (verified green 2026-04-20)
- [x] docker-compose.yml (Postgres 15 + Mailpit)
- [x] Makefile (dev, reset, seed, install, test-unit-api, test-integration-api, lint)
- [x] .env.example (all secret keys documented)
- [x] .gitignore (fixed — uv.lock now committed per standards)
- [x] README.md (5-step quickstart)
- [x] api/pyproject.toml (uv + Python 3.12)
- [x] api/Dockerfile
- [x] api/config.py (pydantic-settings; .env resolved from repo root; extra fields ignored)
- [x] api/main.py (FastAPI scaffold with CORS + Sentry wiring)
- [x] api/database/base.py (async engine + session factory)
- [x] api/database/models.py (31 tables — all SQLAlchemy ORM models)
- [x] api/alembic.ini + api/alembic/env.py (async migration runner)
- [x] api/alembic/versions/001_init_schema.py (all tables + triggers + indexes)
- [x] api/alembic/versions/002_fix_set_updated_at_trigger.py (clock_timestamp fix)
- [x] api/tests/conftest.py (test DB fixtures, async client)
- [x] api/tests/integration/test_migrations.py (schema + trigger verification — 5/5 passing)
- [x] scripts/seed.py (idempotent — roles, 15 categories, app_config defaults, admin user)
- [x] web/ scaffold (Vite + React 18 + TypeScript strict + Tailwind + React Query)
- [x] web/Dockerfile + nginx.conf

**Integration test gate: PASSED — 5/5 green on 2026-04-20**

---

### Sprint 2: Auth Flows — NOT STARTED

Spec: Epic 1.3 in `dev_plan/01_phase1_infrastructure_auth.md`

- [ ] api/routers/auth.py — all auth endpoints
- [ ] api/services/auth_service.py — registration, login, password hashing, 2FA, lockout
- [ ] api/services/session_service.py — refresh token CRUD (Postgres `user_sessions` table)
- [ ] api/services/email_service.py — SendGrid send + Mailpit fallback
- [ ] api/middleware/auth.py — JWT decode + `get_current_user` dependency
- [ ] api/middleware/rate_limit.py — fixed-window counters via `rate_limit_counters` table
- [ ] api/tests/unit/test_auth_service.py — ≥85% coverage on AuthService
- [ ] api/tests/integration/test_auth_flows.py — happy path + auth/RBAC/validation failure cases

**Endpoints (all under `/api/v1/auth/`):**
- `POST /register` — email + password, bcrypt cost 12, triggers verification email
- `GET /verify-email?token=<jwt>` — activates account
- `POST /resend-verification` — rate-limited 3/hr per email
- `POST /login` — returns access token (15 min) + refresh token (7 day)
- `POST /refresh` — rotate refresh token, issue new access token
- `POST /logout` — invalidate refresh token
- `POST /password-reset-request` — always 200 (prevents email enumeration)
- `POST /password-reset-confirm` — validates token, hashes new password, invalidates all sessions
- `POST /change-email` — requires current password, double-confirmation flow
- `POST /2fa/setup` — TOTP secret + QR code URL
- `POST /2fa/confirm` — activates 2FA, returns 10 recovery codes
- `POST /2fa/verify` — partial token + TOTP → full session
- `POST /2fa/recovery` — partial token + recovery code → full session
- `POST /2fa/disable` — requires current TOTP code

---

### Sprint 3: RBAC + Security Middleware — NOT STARTED

Spec: Epic 1.4 + Feature 1.1.5 in `dev_plan/01_phase1_infrastructure_auth.md`

- [ ] api/middleware/rbac.py — `require_roles(*roles)` FastAPI dependency
- [ ] api/middleware/security_headers.py — CSP, HSTS, X-Frame-Options, X-Content-Type, Referrer-Policy
- [ ] api/middleware/request_id.py — generate/thread `X-Request-ID` through all logs
- [ ] api/middleware/structured_logging.py — JSON log per request: timestamp, severity, request_id, user_id, route, status_code, latency_ms
- [ ] api/tests/integration/test_rbac.py — each role against role permission matrix
- [ ] api/tests/integration/test_audit_log.py — all state-transition events produce audit log rows

---

### Sprint 4: Health Check + Observability — NOT STARTED

Spec: Feature 1.1.5 in `dev_plan/01_phase1_infrastructure_auth.md`

- [ ] `GET /api/v1/health` — checks DB reachability + migration version; used as Fly readiness probe
- [ ] Sentry SDK wired into API and web frontend (DSNs from env; already stubbed in main.py)
- [ ] BetterStack log drain configured on prod Fly app (manual step — see Outline Manual Tasks doc)
- [ ] UptimeRobot monitor on `/api/v1/health` (manual step — see Outline Manual Tasks doc)

---

### Sprint 5: CI/CD + Fly.io Configs — NOT STARTED

Spec: Feature 1.1.2 + 1.1.3 in `dev_plan/01_phase1_infrastructure_auth.md`

- [ ] infra/fly/temple-api-dev.toml
- [ ] infra/fly/temple-api-staging.toml
- [ ] infra/fly/temple-api-prod.toml
- [ ] infra/fly/temple-web-dev.toml
- [ ] infra/fly/temple-web-staging.toml
- [ ] infra/fly/temple-web-prod.toml
- [ ] .github/workflows/ci.yml — lint → test → security scans → build → deploy
- [ ] .github/workflows/security.yml — Dependabot + Trivy + gitleaks + pip-audit + npm audit
- [ ] infra/cloudflare/ — Terraform for WAF + rate limiting + DNS
- [ ] Fly.io apps provisioned (manual — see Outline Manual Tasks doc)
- [ ] Neon Postgres provisioned with 3 branches (manual — see Outline Manual Tasks doc)
- [ ] Cloudflare R2 buckets created (manual — see Outline Manual Tasks doc)
- [ ] web/e2e/phase1_auth.spec.ts — Playwright E2E for all auth flows

**Phase 1 gate:** E2E tests pass in CI against staging before phase is marked complete.

---

## Phase 2–8 — Not started
