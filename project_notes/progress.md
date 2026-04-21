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

### Sprint 2: Auth Flows — COMPLETE (verified green 2026-04-20)

Spec: Epic 1.3 in `dev_plan/01_phase1_infrastructure_auth.md`

- [x] api/routers/auth.py — 14 auth endpoints (register, verify, login, refresh, logout, password reset, change email, 2FA setup/confirm/verify/recovery/disable)
- [x] api/services/auth_service.py — registration, login, bcrypt (direct, not passlib), TOTP 2FA, Fernet-encrypted secrets, account lockout, device fingerprinting, audit logging
- [x] api/services/session_service.py — opaque refresh tokens, SHA-256 hashed in DB, rotation on refresh
- [x] api/services/email_service.py — SendGrid (prod) / Mailpit SMTP (dev), asyncio.to_thread, 7 email templates
- [x] api/middleware/auth.py — Bearer JWT decode, `get_current_user`, `require_roles()` factory
- [x] api/middleware/rate_limit.py — Postgres fixed-window counters; 8 pre-configured endpoint limiters
- [x] api/schemas/auth.py — all request/response models with password validation regex
- [x] api/tests/unit/test_auth_service.py — 21/21 passing (pure functions: hashing, JWT, TOTP, fingerprint, schema validation)
- [x] api/tests/integration/test_auth_flows.py — 18/18 passing (all auth flows end-to-end)
- [x] Makefile updated: test-unit-api (no gate), test-integration-api (no gate), test-api (85% gate on combined)
- [x] pyproject.toml: replaced passlib (incompatible with Python 3.14 / bcrypt 5.x) with direct bcrypt usage

**Bugs fixed during sprint:**
- `_ip` parameter shadowed module-level `_ip()` function in login + password-reset routes → renamed to `_rl_ip`
- Test DB missing "customer" role (seed not run on test DB) → added role seeding to `setup_test_db` fixture
- Email rate limit (5/15min) conflicted with lockout threshold (5 attempts) → raised email limit to 10/15min
- passlib + bcrypt 5.x incompatibility (wrap-bug detection fails) → replaced with direct `bcrypt` calls

**Unit test gate: 21/21 passing**
**Integration test gate: 23/23 passing (18 auth flows + 5 migration tests)**

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

### Sprint 3: RBAC + Security Middleware — COMPLETE (verified green 2026-04-20)

Spec: Epic 1.4 + Feature 1.1.5 in `dev_plan/01_phase1_infrastructure_auth.md`

- [x] api/middleware/rbac.py — `require_roles(*roles)` FastAPI dependency (moved from auth.py)
- [x] api/middleware/security_headers.py — CSP, HSTS, X-Frame-Options, X-Content-Type, Referrer-Policy, Permissions-Policy (pure ASGI)
- [x] api/middleware/request_id.py — generate/thread `X-Request-ID` through all logs (pure ASGI)
- [x] api/middleware/structured_logging.py — JSON log per request: request_id, user_id, method, path, status_code, latency_ms (pure ASGI)
- [x] api/tests/integration/test_rbac.py — 9 tests: no-token 401, wrong-role 403, correct-role 200, multi-role, security headers, request-id passthrough
- [x] api/tests/integration/test_audit_log.py — 7 tests: registered, login, login_failed, account_locked, password_reset_requested, 2fa_setup_initiated

**Bugs fixed during sprint:**
- `BaseHTTPMiddleware` causes `RuntimeError: Task got Future attached to a different loop` when route handlers use `asyncio.create_task()` → rewrote all three middleware as pure ASGI
- Test helpers using `get_db()` (new connection) can't see data registered via `db_session` (READ COMMITTED, uncommitted) → threaded `db_session` through all helpers, use `await db.flush()`
- `user.login_failed` and `user.2fa_setup_initiated` audit events missing from auth_service.py → added in `_record_failed_attempt()` and `setup_2fa()`

**Integration test gate: PASSED — 40/40 green on 2026-04-20**
(18 auth flows + 5 migrations + 16 RBAC/headers + 7 audit log + 1 health + 3 middleware)

---

### Sprint 4: Health Check + Observability — COMPLETE (verified green 2026-04-20)

Spec: Feature 1.1.5 in `dev_plan/01_phase1_infrastructure_auth.md`

- [x] `GET /api/v1/health` — checks DB reachability, migration version (alembic_version), R2 connectivity; 200/503 based on required checks
- [x] Sentry SDK: added `release=settings.release` (populated from `GIT_SHA` / `FLY_IMAGE_REF` env var at build time)
- [x] `config.py`: added `release: str = ""` setting
- [x] api/tests/integration/test_health.py — 9/9 passing (shape, db ok, migrations ok, r2 unconfigured, 503 on failure, r2 error non-degrading)
- [ ] BetterStack log drain — manual step (configure on prod Fly app; token in `betterstack_source_token` env var)
- [ ] UptimeRobot monitor on `/api/v1/health` — manual step

**Integration test gate: PASSED — 49/49 green on 2026-04-20**

---

### Sprint 5: CI/CD + Fly.io Configs — COMPLETE (2026-04-21)

Spec: Feature 1.1.2 + 1.1.3 in `dev_plan/01_phase1_infrastructure_auth.md`

- [x] infra/fly/temple-api-dev.toml
- [x] infra/fly/temple-api-staging.toml
- [x] infra/fly/temple-api-prod.toml
- [x] infra/fly/temple-web-dev.toml
- [x] infra/fly/temple-web-staging.toml
- [x] infra/fly/temple-web-prod.toml
- [x] .github/workflows/ci.yml — lint → test → staging auto-deploy on push to main, prod deploy via workflow_dispatch
- [x] .github/workflows/security.yml — Dependabot + Trivy + gitleaks + pip-audit + npm audit
- [x] infra/cloudflare/ — **intentionally skipped; Cloudflare WAF/CDN configured manually**
- [x] Fly.io apps provisioned — 6 apps created (temple-{api,web}-{dev,staging,prod}); pending first deploy; secrets staged
- [x] Neon Postgres provisioned — project created, 3 branches (dev/staging/prod); PITR on prod **requires Neon Pro upgrade before customer data lands** (see known-issues)
- [x] Cloudflare R2 buckets created
- [x] Fly secrets staged (will activate on first `flyctl deploy` triggered by CI)
- [x] web/e2e/phase1_auth.spec.ts — Playwright E2E spec written; staging-dependent tests gated behind `test.skip` pending live staging env

**Bugs fixed post-merge (PR #17, 2026-04-21):**
- `fly` → `flyctl` in all CI deploy commands (binary is named `flyctl`, not `fly`)
- Added `setup-python@v5` to `pip-audit` job in security.yml
- Added `permissions: security-events: write` + `ignore-unfixed: true` to Trivy job

**Phase 1 gate status:** E2E gate pending — staging deploy activates on PR #17 merge; `test.skip` guards on E2E tests will be removed once staging is live and test user is seeded.

---

## Phase 2–8 — Not started
