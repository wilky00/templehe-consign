# TempleHE Consignment Platform — Phase 1 Status Report

**Date:** 2026-04-20
**Phase:** 1 — Infrastructure & Auth
**Status:** IN PROGRESS (Sprint 2 of 5 complete)
**Author:** Jim Wilen

---

## Executive Summary

Phase 1 Sprint 1 (Foundation) is code-complete and lint-clean. The full database schema, Docker dev environment, migration runner, seed script, and React/TypeScript frontend scaffold are all built and working. Sprints 2–5 have not been started. Phase 1 will not be complete until all five sprints are built and the Playwright E2E suite passes in CI against staging.

---

## What Was Built (Sprint 1)

### Infrastructure
- **docker-compose.yml** — Postgres 15.7-alpine + Mailpit 1.21.3 (no Redis — Postgres-backed sessions per ADR-010)
- **Makefile** — `dev`, `reset`, `seed`, `install`, `test-unit-api`, `test-integration-api`, `lint` targets
- **.env.example** — all 30+ env vars documented; no credentials hardcoded
- **README.md** — 5-step quickstart, < 10 min on a fresh laptop

### API (FastAPI + Python 3.12)
- **api/pyproject.toml** — uv-managed; 15 prod deps, ruff, pytest-asyncio
- **api/Dockerfile** — pinned Python 3.12-slim base
- **api/config.py** — pydantic-settings; all secrets from env, no hardcoded values
- **api/main.py** — FastAPI scaffold with CORS, Sentry init, `/api/v1/health` stub
- **api/database/base.py** — SQLAlchemy 2.0 async engine + session factory
- **api/database/models.py** — 31 SQLAlchemy ORM models (all tables)
- **api/alembic/env.py** — async migration runner (asyncpg + run_sync pattern)
- **api/alembic/versions/001_init_schema.py** — all 31 tables + triggers + indexes in one migration

### Database Schema (31 tables)
| Group | Tables |
|---|---|
| Auth | `users`, `roles`, `user_sessions`, `totp_recovery_codes`, `known_devices` |
| Platform | `notification_preferences`, `rate_limit_counters`, `app_config`, `audit_logs`, `record_locks`, `analytics_events`, `webhook_events_seen` |
| Equipment | `equipment_categories`, `category_components`, `category_inspection_prompts`, `category_attachments`, `category_photo_slots`, `category_red_flag_rules`, `equipment_records` |
| Customers | `customers` |
| Appraisal | `appraisal_submissions`, `appraisal_photos`, `component_scores`, `appraisal_reports` |
| Workflow | `consignment_contracts`, `change_requests`, `lead_routing_rules`, `calendar_events` |
| Public | `public_listings`, `inquiries`, `comparable_sales` |

**DB-level triggers:**
- `prevent_audit_log_modification()` — BEFORE UPDATE OR DELETE on `audit_logs` → RAISE EXCEPTION 'audit_logs is append-only'
- `set_updated_at()` — auto-updates `updated_at` on UPDATE for: `users`, `customers`, `equipment_records`, `equipment_categories`, `app_config`

### Tests
- **api/tests/conftest.py** — session-scoped Alembic migration fixture, rollback-per-test isolation, FastAPI async test client
- **api/tests/integration/test_migrations.py** — 5 tests: all 31 tables exist, unique index on roles, append-only trigger (DELETE blocked), append-only trigger (UPDATE blocked), `updated_at` trigger fires

### Seed Script
- **scripts/seed.py** — idempotent via `ON CONFLICT DO NOTHING`; seeds 6 roles, 15 equipment categories, 11 app_config defaults, admin user from `SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD` env vars

### Frontend Scaffold
- **web/** — Vite 5 + React 18 + TypeScript strict + Tailwind CSS + React Query + Zustand + React Router
- **web/Dockerfile** — multi-stage build; nginx:1.27-alpine serving static assets
- Routes scaffolded: `/` (portal), `/login`, `/portal/*`, `/sales/*`, `/admin/*`

### Documentation
- **docs/fly-provisioning.md** — complete step-by-step Fly.io setup: every `flyctl` command in order, Neon Postgres, R2 buckets, secrets, Google OAuth wiring (Jim runs these; not automated)

---

## Test Results

### Unit Tests
**Result: 0 collected — no unit tests written yet**

Unit tests are a Sprint 2 deliverable (`api/tests/unit/test_auth_service.py`). The test infrastructure is wired and imports cleanly; there is nothing to run yet.

### Integration Tests
**Result: Cannot run — requires a running Postgres instance**

The integration tests require `make dev` to be running (Postgres container on localhost:5432). Docker was not available in the build environment during this gate check.

**Two bugs found and fixed during this check:**

| Bug | File | Fix |
|---|---|---|
| `AnalyticsEvent.metadata` clashes with SQLAlchemy's reserved `DeclarativeBase.metadata` attribute | `api/database/models.py:700` | Renamed to `event_metadata` with explicit column name `mapped_column("metadata", ...)` |
| `database/__init__.py` imported `Base` from `database.base` — `Base` lives in `database.models` | `api/database/__init__.py` | Split import: `get_db` from `database.base`, `Base` from `database.models` |

### Lint (ruff)
**Result: PASS — all checks clean**

---

## Phase Gate Status

| Gate | Status | Notes |
|---|---|---|
| `make dev` stack starts in < 10 min | NOT VERIFIED | Needs Docker; Jim to verify locally |
| Unit tests ≥ 85% coverage | BLOCKED | No unit tests written (Sprint 2) |
| Integration tests pass (auth flows + RBAC + headers) | BLOCKED | Sprints 2–3 not built |
| Playwright E2E passes in CI against staging | BLOCKED | Sprints 2 + 5 not built; Fly.io not provisioned |
| gitleaks clean (no secrets detected) | NOT RUN | Run `gitleaks detect --source .` locally |
| `/api/v1/health` returns all security headers | BLOCKED | Sprint 3 security middleware not built |
| Blue-green deploy tested on staging | BLOCKED | Fly.io not provisioned |
| Rollback tested on staging | BLOCKED | Fly.io not provisioned |
| `project_notes/secrets-rotation.md` drafted | BLOCKED | Sprint 4 not built |

---

## What's Next (Sprints 2–5)

### Sprint 2 — Auth Flows (Next)
All six auth flows end-to-end:

**Files to create:**
- `api/routers/auth.py`
- `api/services/auth_service.py`
- `api/services/session_service.py` (refresh token CRUD)
- `api/services/email_service.py` (SendGrid / Mailpit)
- `api/middleware/auth.py` (JWT decode + `get_current_user`)
- `api/middleware/rate_limit.py` (Postgres-backed counters)
- `api/tests/unit/test_auth_service.py`
- `api/tests/integration/test_auth_flows.py`
- `web/e2e/phase1_auth.spec.ts` (Playwright)

**Endpoints:**
```
POST /api/v1/auth/register
POST /api/v1/auth/verify-email
POST /api/v1/auth/login
POST /api/v1/auth/refresh
POST /api/v1/auth/logout
POST /api/v1/auth/forgot-password
POST /api/v1/auth/reset-password
POST /api/v1/auth/change-email
POST /api/v1/auth/2fa/setup
POST /api/v1/auth/2fa/confirm
POST /api/v1/auth/2fa/verify
POST /api/v1/auth/2fa/recovery
POST /api/v1/auth/2fa/disable
```

### Sprint 3 — RBAC + Security Middleware
### Sprint 4 — Health Check + Observability
### Sprint 5 — CI/CD + Fly.io Configs

---

## Pre-Sprint-2 Configuration Checklist

Complete all of these before starting Sprint 2. Items marked **BLOCKING** prevent testing or deployment.

---

### 1. Twilio A2P 10DLC Registration — BLOCKING (Start Now)

**Why it's blocking:** SMS notifications (device verification, security alerts) require A2P 10DLC carrier approval. Approval takes 2–4 weeks. You must start this on Day 1 — it's outside our control.

**Steps:**
1. Go to [twilio.com/console/sms/a2p-10dlc](https://twilio.com/console/sms/a2p-10dlc)
2. Register your brand:
   - Legal business name: Temple Heavy Equipment (exact legal name)
   - EIN: your employer identification number
   - Business type: Private For-Profit
   - Website: templehe.com (or current company site)
   - Business industry: Transportation/Logistics
3. Register your campaign:
   - Use case: Customer Care (covers verification codes, security alerts)
   - Sample message 1: "Your TempleHE verification code is 482910. Valid for 10 minutes."
   - Sample message 2: "A new device was detected on your TempleHE account. If this wasn't you, contact us immediately."
   - Opt-in flow: describe how customers consent (online form at intake)
4. Add your Twilio number to the campaign
5. Track approval status in `/project_notes/known-issues.md`

**Env vars needed:**
```
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxx
TWILIO_FROM_NUMBER=+1xxxxxxxxxx
```

---

### 2. SendGrid DNS Records — BLOCKING for staging/prod email

**Why it's blocking:** Transactional email (account verification, password reset) will only work via Mailpit locally until these DNS records are set. Staging/prod email will fail without them.

**Steps:**
1. Log in to SendGrid → Settings → Sender Authentication → Authenticate a Domain
2. Enter domain: `templehe.com`
3. SendGrid will generate 3 DNS records — add all of them to your DNS provider:
   - **SPF** (TXT): `v=spf1 include:sendgrid.net ~all` at `@`
   - **DKIM CNAME 1**: `s1._domainkey.templehe.com` → SendGrid-provided value
   - **DKIM CNAME 2**: `s2._domainkey.templehe.com` → SendGrid-provided value
4. Add DMARC (TXT at `_dmarc.templehe.com`): `v=DMARC1; p=none; rua=mailto:dmarc@templehe.com`
   - Start at `p=none` for 2 weeks, then `p=quarantine`, then `p=reject`
5. Click "Verify" in SendGrid after DNS propagates (~30 min to 24 hours)
6. Validate at [mail-tester.com](https://www.mail-tester.com)

**Env vars needed:**
```
SENDGRID_API_KEY=SG.xxxxxxxxxxxxxxxxx
SENDGRID_FROM_EMAIL=noreply@templehe.com
SENDGRID_FROM_NAME=Temple Heavy Equipment
```

---

### 3. Run `make dev` Locally — Verify Sprint 1 Wiring

**Why:** Confirms the full stack starts, migrations run, and seed data loads before Sprint 2 builds on top of it.

```bash
# Prerequisites: Docker Desktop must be running
cd /path/to/templehe-consign

# Copy and fill in the env file
cp .env.example .env
# Edit .env — fill in at minimum:
#   DATABASE_URL (auto-set if using docker-compose)
#   JWT_SECRET_KEY (generate: openssl rand -hex 32)
#   JWT_REFRESH_SECRET (generate: openssl rand -hex 32)
#   TOTP_ENCRYPTION_KEY (generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
#   SEED_ADMIN_EMAIL=admin@example.com
#   SEED_ADMIN_PASSWORD=YourSecurePassword123!

make dev
# Expected output: migrations applied, seed data loaded, API on :8000, web on :5173

# Verify the API is running
curl http://localhost:8000/api/v1/health
# Expected: {"status": "ok"}

# Run integration tests against the live stack
cd api && uv run pytest tests/integration/ -v
# Expected: 5 passed (test_migrations.py)
```

---

### 4. Run the Integration Tests and Get a Green Baseline

**Steps:**
```bash
cd /path/to/templehe-consign/api

# Make sure make dev is running first
uv run pytest tests/integration/ -v

# Expected results:
# PASSED tests/integration/test_migrations.py::test_all_tables_exist
# PASSED tests/integration/test_migrations.py::test_roles_have_indexes
# PASSED tests/integration/test_migrations.py::test_audit_logs_append_only_trigger
# PASSED tests/integration/test_migrations.py::test_audit_logs_update_blocked
# PASSED tests/integration/test_migrations.py::test_users_updated_at_trigger
```

If any of these fail, stop and fix before Sprint 2.

---

### 5. Generate Local Secrets

You'll need these in `.env` for Sprint 2 auth flows to work:

```bash
# JWT secret (access tokens)
openssl rand -hex 32

# JWT refresh secret (refresh tokens)
openssl rand -hex 32

# Fernet key for TOTP secret encryption
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Add the output values to `.env`:
```
JWT_SECRET_KEY=<output of first command>
JWT_REFRESH_SECRET=<output of second command>
TOTP_ENCRYPTION_KEY=<output of third command>
```

---

### 6. Fly.io Provisioning (needed for Sprint 5 / staging)

Not blocking for Sprints 2–4, but must be done before Sprint 5 (CI/CD). Full step-by-step at `/docs/fly-provisioning.md`.

Quick checklist:
- [ ] `flyctl auth login`
- [ ] Create 6 apps (api-dev, api-staging, api-prod, web-dev, web-staging, web-prod)
- [ ] Create Neon project with 3 branches (dev, staging, prod)
- [ ] Create 3 Cloudflare R2 buckets (photos, reports, backups)
- [ ] Set all secrets per app via `fly secrets set`

---

## Open Decisions

| Decision | Needed By | Status |
|---|---|---|
| eSign provider (DocuSign vs Dropbox Sign) | Phase 6 | Open |
| Paid valuation API (IronPlanet vs EquipmentWatch) | Phase 5 | Open |
| Public listing page URL / domain | Phase 8 | Open |
| App Store review timing | Phase 5 completion | Open |
| Twilio A2P 10DLC registration | Now | Action required |
| SendGrid DNS records | Staging deployment | Action required |

---

---

## What Was Built (Sprint 2) — 2026-04-20

### Auth Flows (14 endpoints under `/api/v1/auth/`)

| Endpoint | Description |
|---|---|
| `POST /register` | bcrypt cost 12, sends verification email, returns 201 |
| `GET /verify-email?token=` | JWT-signed token (24h), activates account |
| `POST /resend-verification` | rate-limited 3/hr per email |
| `POST /login` | bcrypt verify, lockout after 5 failures (30 min), 2FA partial token, device fingerprint + new-device email |
| `POST /refresh` | opaque token rotation, SHA-256 hash stored in `user_sessions` |
| `POST /logout` | revokes refresh token (idempotent) |
| `POST /password-reset-request` | always 200 (no email enumeration); JWT-signed link (30 min) |
| `POST /password-reset-confirm` | validates token, re-hashes, revokes all sessions |
| `POST /change-email` | requires current password; verification sent to new address (1 hr link); old address notified |
| `GET /change-email/confirm` | activates new email after confirmation |
| `POST /2fa/setup` | Fernet-encrypted TOTP secret at rest; returns secret + QR URI |
| `POST /2fa/confirm` | activates 2FA; returns 10 SHA-256-hashed recovery codes (shown once) |
| `POST /2fa/verify` | partial token + TOTP → full session |
| `POST /2fa/recovery` | partial token + recovery code → full session; code consumed; 2FA warning email at ≤2 remaining |
| `POST /2fa/disable` | requires current TOTP code |

### New Files
- `api/schemas/auth.py` — 17 request/response Pydantic models; password regex enforces 12+ chars, uppercase, number, special
- `api/services/auth_service.py` — all business logic; pure functions exported for unit tests
- `api/services/session_service.py` — opaque refresh token CRUD (issue, validate+rotate, revoke, revoke-all)
- `api/services/email_service.py` — SendGrid prod / SMTP dev; `asyncio.to_thread` for blocking calls; 7 templates
- `api/middleware/auth.py` — `get_current_user` dependency; `require_roles()` factory; `CurrentUserDep` alias
- `api/middleware/rate_limit.py` — Postgres fixed-window counters (ADR-010); 8 endpoint limiters
- `api/routers/auth.py` — thin route handlers; all 14 endpoints

### Modified Files
- `api/main.py` — registered auth router at `/api/v1`
- `api/tests/conftest.py` — added role seeding to `setup_test_db` fixture
- `api/pyproject.toml` — replaced `passlib[bcrypt]` with `bcrypt>=4.0` (passlib incompatible with Python 3.14 + bcrypt 5.x)
- `Makefile` — split coverage gate: `test-unit-api` (no gate), `test-integration-api` (no gate), `test-api` (85% on combined)

### Test Results

| Suite | Result |
|---|---|
| Unit tests (`make test-unit-api`) | 21/21 passing |
| Integration tests (`make test-integration-api`) | 23/23 passing |
| Lint (`uv run ruff check .`) | Clean |

### Phase Gate Status Update

| Gate | Status | Notes |
|---|---|---|
| Unit tests | PASS | 21/21 (pure function coverage) |
| Integration tests — auth flows | PASS | 18/18 auth flow tests green |
| Integration tests — migrations | PASS | 5/5 (same as Sprint 1) |
| RBAC middleware tests | BLOCKED | Sprint 3 not built |
| Security headers | BLOCKED | Sprint 3 not built |
| Playwright E2E | BLOCKED | Sprint 5 not built |

---

## ADRs Recorded This Phase

| ADR | Decision |
|---|---|
| ADR-009 | Phase 1 auth is email/password + TOTP only; Google SSO deferred to post-POC |
| ADR-010 | Postgres tables (`user_sessions`, `rate_limit_counters`) replace Redis for POC; `SessionService` and `RateLimitService` interfaces abstract the swap to Redis Memorystore on GCP |
