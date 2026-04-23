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

## Phase 2 — Customer Portal (In Progress, started 2026-04-22)

Full spec: `dev_plan/02_phase2_customer_portal.md`

### Sprint 1: Customer Registration + ToS/Privacy Consent — COMPLETE (verified green 2026-04-22)

Spec: Epic 2.1 in `dev_plan/02_phase2_customer_portal.md`

- [x] `api/alembic/versions/005_phase2_customer_profile.py` — adds `users.deletion_grace_until`, `user_consent_versions` archive table (append-only via trigger), and app_config defaults (`tos_current_version`, `privacy_current_version`, `audit_pii_retention_days`, `audit_row_retention_months`)
- [x] `api/database/models.py` — added `UserConsentVersion` model + `User.deletion_grace_until` column
- [x] `api/content/tos/v1.md` + `api/content/privacy/v1.md` — DRAFT placeholder text, file-driven so the final lawyer-reviewed copy can land without a code change
- [x] `api/schemas/customer.py` — `CustomerProfileRead`, `CustomerProfileUpdate` (USPS state validator, strip-or-null text fields), `EmailPrefs`
- [x] `api/schemas/legal.py` — `LegalDocument`, `AcceptTermsRequest`, `ConsentStatus`
- [x] `api/schemas/auth.py` — `RegisterRequest` now requires `tos_version` + `privacy_version`; `CurrentUser` now exposes `requires_terms_reaccept`
- [x] `api/services/customer_service.py` — lazy-creates `customers` row on first `/me/profile` access, profile/email-pref read + update
- [x] `api/services/legal_service.py` — loads markdown from `api/content/`, reads current versions from `app_config`, records consent + updates user, `requires_reaccept()` check
- [x] `api/services/auth_service.py` — `register_user()` now takes `tos_version`/`privacy_version`/`ip_address`/`user_agent`, validates against server-current, writes to consent archive on success
- [x] `api/routers/customers.py` — `GET/PATCH /me/profile`, `GET/PATCH /me/email-prefs`; all require `customer` role
- [x] `api/routers/legal.py` — `GET /legal/tos`, `GET /legal/privacy` (public), `GET /legal/consent-status` + `POST /legal/accept` (auth)
- [x] `api/routers/auth.py` — `/auth/me` returns `requires_terms_reaccept`; `/register` threads client IP + UA to the service layer
- [x] `api/routers/health.py` — `_EXPECTED_MIGRATION_HEAD` bumped to `"005"`
- [x] `api/tests/integration/test_customer_registration.py` — 14 new tests: consent archive, stale-version reject, missing-fields 422, re-accept interstitial, profile auto-create, profile PATCH, USPS state validation, unauth 401s, email prefs roundtrip, app_config seed sanity
- [x] `api/tests/integration/test_auth_flows.py` + `test_audit_log.py` + `test_rbac.py` + `tests/unit/test_auth_service.py` — updated register payloads to include `tos_version` + `privacy_version`

**Full test gate: 124/124 green, 94.67% coverage (85% floor)**

**Bugs fixed during sprint:**
- Migration 005 INSERT parsed by SQLAlchemy as bind params because `":30"` inside JSON literals looked like placeholders → rewrote using `jsonb_build_object()`. Same fix applied to test-time `app_config` updates.
- Docker Compose postgres was still running on a PG15 data volume after the `b6529e0` bump to postgres:16.9-alpine → `make reset` wiped the volume and reinitialized under PG16. All doc references to "PostgreSQL 15" (README, CLAUDE.md, dev_plan/00_overview.md, dev_plan/01_phase1, dev_plan/13_hosting_migration_plan, decisions.md) updated to 16.

**Endpoints (new in Sprint 1):**
- `GET /api/v1/legal/tos` — public ToS doc (markdown body + current version)
- `GET /api/v1/legal/privacy` — public Privacy doc
- `GET /api/v1/legal/consent-status` — authed; drives re-accept interstitial
- `POST /api/v1/legal/accept` — authed; records acceptance of current versions
- `GET /api/v1/me/profile` — authed customer; lazy-creates row
- `PATCH /api/v1/me/profile` — authed customer; partial update
- `GET /api/v1/me/email-prefs` — authed customer
- `PATCH /api/v1/me/email-prefs` — authed customer

**Legal content governance:** ToS/privacy text lives in versioned files under `api/content/<type>/v<N>.md`; current version is advertised via `app_config.tos_current_version` / `privacy_current_version`. Bumping the version string forces every returning user through `requires_terms_reaccept` on their next `/auth/me` call. Registration rejects sign-ups whose submitted version doesn't match current — prevents a stale sign-up page from silently binding a user to unfamiliar terms.

---

### Sprint 2: Equipment Intake + NotificationService + Bundle Seed — COMPLETE (verified green 2026-04-23)

Spec: Epic 2.2 in `dev_plan/02_phase2_customer_portal.md`

- [x] `api/alembic/versions/006_phase2_intake_and_notifications.py` — adds 12 customer-intake columns + reference_number + category_id FK on `equipment_records`; `customer_intake_photos` child table; `notification_jobs` durable queue with CHECK constraints, partial pending-ready index, and set_updated_at trigger reuse
- [x] `api/database/models.py` — `EquipmentRecord` intake columns + `category` + `intake_photos` relationships; new `CustomerIntakePhoto` and `NotificationJob` models
- [x] `api/pyproject.toml` — `bleach>=6.1` re-added (per security baseline §3), `twilio>=9.3` added for A2P 10DLC dispatch
- [x] `api/config.py` — `twilio_messaging_service_sid` setting; if empty, SMS dispatch is skipped + audited
- [x] `api/services/sanitization.py` — `sanitize_plain` strips all markup, `sanitize_html` keeps a narrow inline allowlist and blocks `javascript:` / `data:` URIs
- [x] `api/services/notification_service.py` — `enqueue` (idempotent on key), `claim_next_batch` via `FOR UPDATE SKIP LOCKED`, `process_job` with exponential backoff (30s → 6h) and 5 max attempts; DB-default `scheduled_for` so Python-host clock drift doesn't race `clock_timestamp()`
- [x] `api/services/equipment_service.py` — `submit_intake` creates record, generates `THE-XXXXXXXX` via Crockford-32 secrets, attaches photos via relationship, enqueues intake confirmation through NotificationService; `list_records_for_user` / `get_record_for_user` use `selectinload` to avoid async lazy-load traps
- [x] `api/schemas/equipment.py` — `IntakeSubmission` (running_status + ownership_type enums, photo cap=20, year/hours bounds), `IntakePhotoIn/Out`, `EquipmentRecordOut`
- [x] `api/routers/equipment.py` — `POST /me/equipment`, `POST /me/equipment/batch` → 501 placeholder, `GET /me/equipment`, `GET /me/equipment/{id}`; all gated to `customer` role
- [x] `api/routers/health.py` — `_EXPECTED_MIGRATION_HEAD` bumped to `"006"`
- [x] `scripts/import_category_bundle.py` — imports Dozers, Backhoe Loaders, and Articulated Dump Trucks with full components (weights from `06_scoring_and_rules_logic.csv`), inspection prompts, photo slots, attachments, and red-flag rules (from the per-category checklist markdown)
- [x] `scripts/seed.py` — trimmed stub category list to the 12 remaining categories and hooked `import_bundle()` so `make seed` ships the three complete categories
- [x] `scripts/notification_worker.py` — long-running drainer loop with `SELECT ... FOR UPDATE SKIP LOCKED`, signal-handled shutdown, and a `WORKER_SINGLE_PASS` env toggle for ad-hoc runs
- [x] `infra/fly/temple-notifications.toml` — worker Fly Machine config mirroring the `temple-sweeper` shape
- [x] `project_notes/known-issues.md` — added a pre-launch-gate entry for provisioning `temple-notifications`
- [x] `api/tests/conftest.py` — seeds the starter bundle on test DB bootstrap so Phase 2+ tests have real category data
- [x] `api/tests/unit/test_sanitization.py` — 6 tests: plain-strip, html-allowlist, script/iframe/javascript/data-URI blocks
- [x] `api/tests/integration/test_equipment_intake.py` — 11 tests: happy path, bleach, running-status/ownership validation, unknown category 422, photo cap, unauth 401, batch 501, list isolation, detail cross-customer 404, reference-number uniqueness
- [x] `api/tests/integration/test_notification_service.py` — 8 tests: enqueue writes pending, idempotency-key dedup, unknown channel rejected, claim_next_batch marks processing + skips future, delivered on success, retry on exception, failed after max_attempts, SMS skipped when not configured, SMS failed on missing payload fields
- [x] `api/tests/integration/test_category_bundle_import.py` — 5 tests: 3 starter categories seeded, Dozers child tables populated (8 components + 10 prompts + 10 photos + 8 attachments + 5 red-flag rules), re-import no-ops, unknown-slug ignored, component weights sum to ~100%

**Full test gate: 154/154 green, 94.98% coverage (85% floor)**

**Bugs fixed during sprint:**
- Test DB never ran the category bundle importer → extended `conftest.py` `setup_test_db` to invoke `import_bundle` after role seed.
- `EquipmentRecord.intake_photos` triggered a greenlet-less lazy load when the router serialized a newly-created record → populate the collection via `record.intake_photos.append(...)` + `await db.refresh(record, attribute_names=["intake_photos"])`; list/detail paths use `selectinload`.
- `test_claim_batch_marks_processing_and_skips_future` was flaky because Python on macOS host and Postgres in Docker Desktop VM can drift by hundreds of ms → enqueue now lets the DB default fire on `scheduled_for` when no explicit value is supplied, keeping the insert clock and the claim query's `clock_timestamp()` on the same source. `SELECT ... SKIP LOCKED` query changed `NOW()` → `clock_timestamp()` so jobs enqueued in the same transaction become visible to the worker in the same tx (matters for tests; prod is unaffected).
- Migration 005 colon-bind trip already captured in Sprint 1, but a similar issue almost re-appeared in 006's test data — avoided by using the ORM throughout.

**Sanitization policy (security baseline §3):**
- Every customer-supplied free-text field (make, model, serial, location, description, photo caption) runs through `sanitize_plain` before the DB write.
- `sanitize_html` is reserved for paths that render rich HTML (email templates) — not used in Sprint 2; will come online with status-update emails in Sprint 3.

**Deferred to later Phase 2 sprints:**
- Photo blob upload (signed R2 URLs + client-side multipart) — Sprint 3. Sprint 2 persists `storage_key` metadata only; the R2 object is assumed to already exist via an out-of-band path.
- Change request API + status update emails — Sprint 3.
- GDPR-lite data export + deletion + row-level `audit_logs` PII scrubber — Sprint 4.
- Web frontend (sign-up, dashboard, intake form, detail timeline) — Sprint 5.
- Phase 2 E2E (Playwright + axe-core + Lighthouse ≥ 90) — Sprint 6.

**Endpoints (new in Sprint 2):**
- `POST /api/v1/me/equipment` — submit intake; returns `THE-XXXXXXXX` reference
- `POST /api/v1/me/equipment/batch` — 501 placeholder for Phase 4/5 bulk import
- `GET  /api/v1/me/equipment` — list the caller's intakes
- `GET  /api/v1/me/equipment/{id}` — detail; cross-customer is 404 (not 403 — no ID-space leak)

---

### Sprint 3: Photo Upload + Status Timeline + Change Requests — COMPLETE (verified green 2026-04-23)

Spec: Epic 2.3 + 2.4 in `dev_plan/02_phase2_customer_portal.md`

- [x] `api/alembic/versions/007_phase2_status_events_and_photo_scan.py` — new `status_events` (append-only trigger) + `customer_intake_photos.scan_status` / `content_type` / `sha256` columns with CHECK constraint + partial index for pending scans
- [x] `api/database/models.py` — new `StatusEvent` model with append-only semantics; `CustomerIntakePhoto` gains scan metadata; `EquipmentRecord.status_events` relationship with `cascade="all, delete-orphan"` and `order_by=StatusEvent.created_at`
- [x] `api/services/photo_upload_service.py` — presigned R2 URL generator (15-min expiry), immutable key pattern `photos/{equipment_id}/{uuid}.{ext}`, MIME + extension allowlist, finalize-side defense against cross-record storage_key spoofing
- [x] `api/services/equipment_status_service.py` — single `record_transition()` entry point that writes to status_events, updates the record, and enqueues a customer-facing email on 6 watched destination statuses via NotificationService; narrow forbidden-transition set prevents obvious reversals (sold→new_request etc.)
- [x] `api/services/change_request_service.py` — customer submission + allowlisted request_types; notifies assigned_sales_rep_id if set, else `settings.sales_ops_email`, else logs silently; notes run through `sanitize_plain`
- [x] `api/services/equipment_service.py` — `submit_intake` now refreshes both `intake_photos` and `status_events` after flush; list/detail queries add `selectinload` for both collections; new `finalize_intake_photo` helper
- [x] `api/schemas/photo.py` — `UploadUrlRequest/Response`, `FinalizePhotoRequest` (sha256 optional, hex-64 validated); `api/schemas/change_request.py` — create + out; `api/schemas/equipment.py` — new `StatusEventOut` + timeline on detail; `IntakePhotoOut` gains scan_status + content_type
- [x] `api/config.py` — `sales_ops_email` setting (empty ⇒ silent)
- [x] `api/routers/equipment.py` — four new endpoints; detail serializes both collections
- [x] `api/routers/health.py` — `_EXPECTED_MIGRATION_HEAD` bumped to `"007"`
- [x] `api/tests/integration/test_photo_upload.py` — 9 tests: signed URL happy path (boto3 mocked), unknown extension rejected, non-image MIME rejected, cross-customer 404, finalize persists metadata, wrong-prefix rejected, bad sha256 rejected, detail shows finalized photo, unconfigured R2 returns 503
- [x] `api/tests/integration/test_change_requests.py` — 6 tests: happy path + sales-rep notification enqueue + bleach on notes, ops-email fallback, silent fallback, unknown request_type 422, cross-customer 404, list isolation
- [x] `api/tests/integration/test_status_events.py` — 7 tests: transition writes event + updates status, email enqueued on customer-facing statuses, internal statuses skip email, same-destination 409 + email idempotency, forbidden edge 409, detail endpoint exposes ordered timeline, DB-level append-only trigger blocks UPDATEs

**Full test gate: 176/176 green, 95.65% coverage (85% floor)**

**Bugs fixed during sprint:**
- New `EquipmentRecord.status_events` relationship triggered the same async-SA lazy-load trap the `intake_photos` collection hit in Sprint 2 → `submit_intake` now refreshes both collections after flush, and `list`/`get` use `selectinload` on both.
- Append-only trigger test caught the wrong exception class — Postgres raises asyncpg `RaiseError`, which SQLAlchemy wraps as `DBAPIError`, not `InternalError`/`ProgrammingError`. Test updated to match.

**Deliberately deferred (flagged, not regressed):**
- Real ClamAV scan integration — `scan_status` column is a scaffold that starts `pending` and never flips. Phase 5 or a dedicated scan-worker sprint adds the actual scanner + queue consumer.
- PDF placeholder generator scaffold — zero-scope this sprint; Phase 7 will build the full generator.
- Server-side verification of uploaded blob (sha256 recompute after R2 PUT) — Sprint 3 trusts the client-supplied hash and persists; real verification lives with the scan worker.

**Endpoints (new in Sprint 3):**
- `POST /api/v1/me/equipment/{id}/photos/upload-url` — short-lived presigned R2 PUT URL + immutable storage_key
- `POST /api/v1/me/equipment/{id}/photos` — finalize photo metadata (scan_status=pending)
- `POST /api/v1/me/equipment/{id}/change-requests` — customer submits a change request; enqueues sales notification
- `GET  /api/v1/me/equipment/{id}/change-requests` — list for that record
- `GET  /api/v1/me/equipment/{id}` — detail now includes `photos[].scan_status` + ordered `status_events[]` timeline

**Status transition contract:** `equipment_status_service.record_transition()` is the single entry point. Called directly by tests today; Phase 3 sales-rep HTTP endpoints will call the same function. Status-update emails for the six watched destinations (`appraisal_scheduled`, `appraisal_complete`, `offer_ready`, `listed`, `sold`, `declined`) enqueue one message per (record, destination) via an idempotency key — safe against retries, safe against a bounce-back same-status transition (which 409s upstream).

---

### Sprint 4: GDPR-Lite Data Export + Account Deletion + Audit PII Scrubber — COMPLETE (verified green 2026-04-23)

Spec: Epic 2.5 + security baseline §7 in `dev_plan/11_security_baseline.md`

- [x] `api/alembic/versions/008_phase2_account_deletion_and_audit_scrub.py` — new `data_export_jobs` table (status CHECK, user+requested_at index, updated_at trigger); new PL/pgSQL `fn_scrub_audit_pii(retention_days INT)` with 30–120 guard; new `fn_delete_expired_accounts()` that pseudonymizes users + customers; existing append-only audit trigger now yields when session GUC `templehe.pii_scrub='on'` is set so the scrubber can UPDATE
- [x] `api/database/models.py` — new `DataExportJob` ORM model
- [x] `api/services/data_export_service.py` — gathers user + customer + consent_versions + equipment_records (with intake_photos, status_events, change_requests via selectinload) + notifications_sent; writes per-entity JSON files + manifest.txt into a zip; `PUT` to R2 at `exports/{user_id}/{export_id}.zip`; 7-day presigned GET URL on the job row; enqueues archival email via NotificationService
- [x] `api/services/account_deletion_service.py` — `request_deletion` (idempotent; sets `deletion_requested_at` + `deletion_grace_until = now+30d`, flips status to `pending_deletion`, revokes all other sessions, emails the user); `cancel_deletion` (clears grace, restores `active`, emails confirmation); `finalize_deletion_for_user` (immediate PII scrub for admin/test use; the production path is the hourly sweeper calling `fn_delete_expired_accounts()`)
- [x] `api/middleware/auth.py` — `get_current_user` now accepts `status ∈ {"active", "pending_deletion"}` so a user mid-grace can still hit `/delete/cancel`; `deleted`, `locked`, `pending_verification` still 401
- [x] `api/schemas/account.py` — `DeletionRequestResponse`, `DataExportOut`
- [x] `api/routers/account.py` — 4 new endpoints under `/me/account`
- [x] `api/routers/health.py` — `_EXPECTED_MIGRATION_HEAD` bumped to `"008"`
- [x] `scripts/sweep_retention.py` — extended to call `fn_delete_expired_accounts()` and `fn_scrub_audit_pii()` (reads retention days from `app_config.audit_pii_retention_days`, falling back to 30)
- [x] `scripts/scrub_audit_pii.py` + `scripts/delete_expired_accounts.py` — new standalone admin entry points for ad-hoc runs
- [x] `api/tests/integration/test_data_export.py` — 6 tests: persisted job + download URL, archival email enqueued, zip content includes all 7 expected files + correct payloads, list past jobs, unauth 401, R2 failure marks job failed
- [x] `api/tests/integration/test_account_deletion.py` — 7 tests: grace window set + email enqueued, sessions revoked, idempotent second request, cancel restores active + clears grace, cancel outside grace is 409, finalize PII-scrubs user + customer, `fn_delete_expired_accounts()` via SQL finalizes a grace-expired user, deleted user's token returns 401
- [x] `api/tests/integration/test_audit_pii_scrub.py` — 5 tests: rows > retention nulled, rows < retention untouched, out-of-range retention rejected at the function boundary, non-ip/ua fields preserved, naïve UPDATE outside scrubber still blocked, DELETE still blocked

**Full test gate: 195/195 green, 95.86% coverage (85% floor)**

**Bugs fixed during sprint:**
- `auth_middleware` only allowed `status='active'`, which would have broken `/me/account/delete/cancel` during a grace window. Middleware now allows `active` or `pending_deletion`; all other states still 401.
- Test helper inserted rows with `:days || ' days'` concat — Postgres doesn't auto-cast int → text for `||`. Switched to `make_interval(days => :days)`.

**Deliberately kept out of scope:**
- Hard row deletion of equipment records, consignments, and appraisal history — these are business facts after the identity is scrubbed. GDPR right-to-erasure is satisfied by pseudonymization of `users.email`, `users.first_name`, and the `customers` PII fields; the retention+scrubber layer removes ip_address/user_agent from `audit_logs` on the admin-configured schedule.
- Real-time scan of uploaded export blobs (no PII in the zip itself that isn't already the user's own data).

**Endpoints (new in Sprint 4):**
- `POST /api/v1/me/account/delete` — start 30-day grace, revoke other sessions, email confirmation
- `POST /api/v1/me/account/delete/cancel` — restore active status (must be pending_deletion)
- `POST /api/v1/me/account/data-export` — synchronously build ZIP, upload to R2, return 7-day signed URL + enqueue archival email
- `GET  /api/v1/me/account/data-exports` — list the caller's past export jobs

**Right-to-erasure semantics:** at grace expiry the retention sweeper (hourly) scrubs `users` (email → non-routable marker, first_name → `[deleted]`, secrets nulled, status → `deleted`) and `customers` (submitter_name → `[deleted]`, PII NULLed, deleted_at set). Equipment records and consignment history remain as business facts. Deleted users can no longer authenticate — any surviving access token 401s.

**Audit PII scrubber:** `fn_scrub_audit_pii(days)` nulls ip_address + user_agent on `audit_logs` rows older than N days, guarded by a 30–120 range check. Bypasses the append-only trigger via a session GUC (`templehe.pii_scrub='on'`) that the trigger explicitly recognizes — naïve application-code UPDATEs and DELETEs on audit_logs are still blocked outside that path.

**Operational path:** the existing `temple-sweeper` Fly app (still awaiting provisioning per known-issues.md) now carries the deletion + PII-scrub work in addition to rate_limit_counters + webhook_events_seen + user_sessions + audit-partition bootstrap. No new Fly app to stand up; the retention worker does it all.

---

## Phase 3–8 — Not started
