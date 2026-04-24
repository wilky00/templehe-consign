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

## Phase 2 — Customer Portal (COMPLETE — 2026-04-24, started 2026-04-22)

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

### Sprint 5: Web Frontend (Customer Portal) — COMPLETE (verified green 2026-04-23)

Spec: Epic 2.1–2.6 (customer-facing UI) in `dev_plan/02_phase2_customer_portal.md`

Every Phase 2 backend endpoint now has a working UI path. Design is workmanlike Tailwind utility classes — visual polish + design-system tokens can iterate once UAT surfaces what needs attention.

**API client + state (6 files):**
- [x] `web/src/api/client.ts` — fetch wrapper with Bearer header, `credentials: "include"` for the refresh cookie, auto `401 → /auth/refresh → retry` dance, typed `ApiError` with `status` + `detail`
- [x] `web/src/api/types.ts` — TypeScript shapes mirroring every backend schema
- [x] `web/src/api/auth.ts`, `legal.ts`, `equipment.ts`, `account.ts` — typed wrappers per domain
- [x] `web/src/state/auth.ts` — Zustand store for the access token (sessionStorage-backed; refresh is HttpOnly cookie)
- [x] `web/src/hooks/useMe.ts` — React Query hook against `/auth/me`, gated on token presence

**Design-system atoms (6 files):**
- [x] `web/src/components/ui/Button.tsx` — 4 variants (primary/secondary/ghost/danger), 3 sizes, accessible focus ring
- [x] `web/src/components/ui/Input.tsx` — `TextInput`, `Select`, `Textarea`, `Checkbox` — consistent labels + errors + aria-invalid
- [x] `web/src/components/ui/Alert.tsx` — 4 tones, role=alert on errors/warnings
- [x] `web/src/components/ui/Card.tsx` — simple bordered container
- [x] `web/src/components/ui/Spinner.tsx` — css-only animated loader with aria-label
- [x] `web/src/components/ui/StatusBadge.tsx` — colored badge mapping the 8 Phase 2 equipment statuses

**Shell (3 files):**
- [x] `web/src/components/Layout.tsx` — header + nav + logout + ToS interstitial wrapper for every authenticated page
- [x] `web/src/components/ProtectedRoute.tsx` — redirects to /login on no-token or /auth/me failure
- [x] `web/src/components/ToSInterstitial.tsx` — full-screen modal driven by `CurrentUser.requires_terms_reaccept`; re-accept triggers `POST /legal/accept` then invalidates the `me` query

**Customer portal pages (8 files):**
- [x] `web/src/pages/Register.tsx` — pulls current ToS + Privacy versions, requires the consent checkbox, echoes versions on `POST /auth/register`; success shows the "check your inbox" state
- [x] `web/src/pages/Login.tsx` — simple email+password, sets the access token, honors `Location.state.from` for a post-login redirect
- [x] `web/src/pages/VerifyEmail.tsx` — reads `?token=…`, calls `GET /auth/verify-email`, surfaces success/error
- [x] `web/src/pages/Dashboard.tsx` — lists submissions with status badges + a "Submit new equipment" CTA; empty state links to intake
- [x] `web/src/pages/IntakeForm.tsx` — category dropdown (new `GET /me/equipment/categories` backend endpoint added for this), all customer-supplied fields, multi-photo picker; submits record with `photos=[]` then runs the 3-step signed-URL upload per file and partials any failures back as a warning
- [x] `web/src/pages/EquipmentDetail.tsx` — details card, timeline card, photo grid (reads from `VITE_R2_PUBLIC_URL` when set; otherwise shows storage_key as placeholder), and an inline change-request form that shows prior requests
- [x] `web/src/pages/Account.tsx` — email preferences (save-on-click), data export (request + latest job state + download link), account deletion (confirmation checkbox → request; pending_deletion users see the cancel button)
- [x] `web/src/pages/NotFound.tsx` — catch-all 404
- [x] `web/src/App.tsx` — real routes for `/login`, `/register`, `/auth/verify-email`, `/portal`, `/portal/submit`, `/portal/equipment/:id`, `/portal/account`; Sales CRM + Admin Panel stay as placeholders

**Supporting (2 files):**
- [x] `web/src/hooks/usePhotoUpload.ts` — orchestrates `upload-url → PUT (direct to R2 via fetch) → finalize` for a single file
- [x] `web/src/vite-env.d.ts` — ImportMeta typings for `VITE_API_BASE_URL` and `VITE_R2_PUBLIC_URL`

**Backend side-car:**
- [x] `api/routers/equipment.py` — new `GET /me/equipment/categories` endpoint returning active categories ordered by display_order (customer role required; existing tests unaffected)

**Env:**
- [x] `web/.env.example` — documents `VITE_API_BASE_URL` (defaults to vite proxy → `:8000`) and `VITE_R2_PUBLIC_URL` for photo thumbnails

**Full stack gates:** `npm run build` clean (119 modules, 249 KB main JS), `npm run lint` clean, backend 195/195 tests green, ruff clean. No frontend unit tests this sprint — that's Sprint 6's Playwright + axe + Lighthouse territory.

**Bugs fixed during sprint:**
- TypeScript build initially failed with `Property 'env' does not exist on type 'ImportMeta'` — added `web/src/vite-env.d.ts` with the standard Vite augmentation so `VITE_*` reads type-check.

**Deliberately deferred (flagged, not regressed):**
- 2FA setup/verify/disable UI — all backend endpoints exist and the `CurrentUser.totp_enabled` flag is in the types; the Phase 5 iOS sprint will need the UI and can build it then.
- Password reset + change email full UI — backend endpoints shipped in Phase 1; the front-end flow is one more pair of pages that Phase 6 polish can pick up.
- Polished design system (color tokens, type ramp, spacing scale) — minimal Tailwind utility classes today. Phase 6 design pass handles the visual refresh.
- Frontend unit tests (Vitest + Testing Library) — Sprint 6 delivers E2E + axe + Lighthouse as the gate; component-level unit tests come alongside if useful.

**Flows working end-to-end against local stack (`make dev` + `npm run dev`):**
1. Register → ToS/Privacy consent → verification email → verify → login
2. Dashboard → Submit equipment (incl. photos via signed-URL direct to R2 when configured) → detail page → THE-XXXXXXXX reference visible
3. Detail page → change request → sales notification queued in `notification_jobs`
4. Account page → email prefs → save
5. Account page → data export → 7-day download URL surfaced (and emailed via NotificationService)
6. Account page → delete account → 30-day grace → cancel
7. Version bump in `app_config.tos_current_version` → ToSInterstitial blocks every route until re-accept

**Endpoints surfaced this sprint (new):**
- `GET /api/v1/me/equipment/categories` — ordered list of active categories for the intake form dropdown

**Routes (new in the web app):**
- `/register`, `/login`, `/auth/verify-email`
- `/portal` (dashboard), `/portal/submit` (intake), `/portal/equipment/:id` (detail + change-request), `/portal/account`

---

### Sprint 6: Phase 2 Gate — Playwright + axe + Lighthouse — COMPLETE (verified green 2026-04-23)

Spec: `dev_plan/09_testing_strategy.md` §4, §7

Every Phase 2 customer flow is now exercised in a real browser against a real stack. Accessibility is enforced by axe-core (zero Critical/Serious); Lighthouse CI pins Accessibility + Best Practices ≥ 0.9 on the public auth pages.

- [x] `web/package.json` — added `@playwright/test ^1.59`, `@axe-core/playwright ^4.11`, `@lhci/cli ^0.15` dev deps; new scripts: `e2e`, `e2e:ui`, `lhci`
- [x] `web/playwright.config.ts` — auto-starts `npm run dev` unless `E2E_SKIP_WEBSERVER=1`; trace on first retry, screenshot + video on failure; `fullyParallel: false` + `workers: 1` so per-user rate-limit counters don't cross-contaminate tests
- [x] `web/e2e/helpers/api.ts` — `makeTestUser` (unique `e2e+slug@example.com` + random TEST-NET-1 fake IP), `apiRegister` / `apiLogin` / `apiVerifyEmail` with the fake IP as `CF-Connecting-IP`, `applyFakeIp` helper to thread the same header onto the browser context (sidesteps the 5-registrations/hour IP limiter)
- [x] `web/e2e/helpers/mailpit.ts` — polls Mailpit's HTTP API for a verify email by recipient + subject; extracts the JWT token from the HTML body
- [x] `web/e2e/helpers/axe.ts` — `@axe-core/playwright` wrapper tagged `wcag2a / aa wcag21a / aa`; asserts zero Critical/Serious
- [x] `web/e2e/phase2_register_verify_login.spec.ts` — register form → Mailpit token → verify page → login → dashboard; plus wrong-password surfaces the error banner
- [x] `web/e2e/phase2_intake_flow.spec.ts` — intake form → detail page with `THE-XXXXXXXX` → dashboard shows the row + status badge
- [x] `web/e2e/phase2_change_request.spec.ts` — change request from detail → success banner + appears in prior-requests list
- [x] `web/e2e/phase2_account.spec.ts` — email prefs save roundtrip (reload preserves), delete → pending_deletion → cancel, data export button renders (R2 happy path left to backend tests)
- [x] `web/e2e/phase2_tos_interstitial.spec.ts` — Playwright route interceptor flips `requires_terms_reaccept` on `/auth/me` → full-screen modal blocks every route
- [x] `web/e2e/phase2_accessibility.spec.ts` — axe sweep across public routes (login, register, verify-email) + authenticated routes (dashboard, submit, detail, account); zero Critical/Serious required
- [x] `web/lighthouserc.cjs` — `/login` and `/register` served from `dist/`; Accessibility + Best Practices ≥ 0.9 gated; Performance kept at a warning (cold-boot CI is noisy)
- [x] `.github/workflows/ci.yml` — new `e2e` job: Postgres service, Mailpit via `docker run`, uvicorn + vite preview backgrounded, `npx playwright test`, `lhci autorun`; uploads the Playwright report + API log on failure; `deploy-staging` now depends on `e2e` passing

**Frontend/UI fixes discovered by axe + E2E:**

- `web/src/pages/Register.tsx` — `AuthShell` promotes page-specific title to `<h1>` with the brand as supplementary text above; gives every auth page one real landmark so axe heading-order is happy.
- `web/src/pages/IntakeForm.tsx` — the multi-file photo picker had no label; added a visually-hidden `<label for="intake-photos">` so axe "label" rule passes (was 97 matching nodes).
- `web/src/pages/VerifyEmail.tsx` — switched from `useMutation` inside `useEffect` to `useQuery`. StrictMode's dev-mode double-mount was firing the verify mutation twice — success the first, 400 the second (status flipped to `active` between calls) — and leaving `mutation.isError` true. `useQuery` dedupes by key and is the right primitive for a token-gated one-shot read anyway.

**Backend + infra fixes discovered by real SMTP round-trip:**

- `api/services/email_service.py` — `smtplib.SMTP(...)` now passes `local_hostname="localhost"` and `timeout=10`. Default invocation calls `socket.getfqdn()`, which on macOS hangs ~35s on an mDNS lookup with no responder. Explicit hostname skips it.
- `api/config.py` + `.env` + `.env.example` — `smtp_host` default `localhost` → `127.0.0.1`. `localhost` resolves to `::1` first on macOS; Mailpit binds IPv4 only, so the resolver takes ~35s to fall back. 127.0.0.1 is unambiguous.
- `web/vite.config.ts` — Vite dev proxy `target` `localhost` → `127.0.0.1`. Same IPv6-first trap from the Node side.

**Full local E2E: 12/12 passing in ~15s** against `make dev` + API + Playwright's auto-started vite.

**Bugs fixed during sprint:**
- Pydantic `email_validator` rejects `.test` TLD (reserved); switched `makeTestUser` to `e2e+<slug>@example.com` (example.com is the reserved documentation domain, passes deliverability check).
- Per-IP register rate limit (5/hr) blew up fast across repeat runs; random TEST-NET-1 fake IP per test via `CF-Connecting-IP` header (backend's `get_client_ip` already honors it, no API change).

**Deferred (out of scope for Phase 2 gate):**
- Photo upload E2E through real R2 — backend integration tests already cover `upload-url` + `finalize`; the full UI path needs R2 creds and lives in a manual smoke on staging.
- Password reset + change email E2E — UIs deferred per Sprint 5 scope note; E2E follows the UI work.
- 2FA E2E — follows the Phase 5 iOS TOTP work.
- Lighthouse Performance budget — left as a warning; cold-boot CI scores are too noisy to gate on.

**Phase 2 PR from `phase2-customer-portal` → `main` is ready to open** after this commit. Full Phase 2 scope delivered:

- Sprint 1: ToS + Privacy + consent capture
- Sprint 2: Equipment intake + durable notification queue + category bundle
- Sprint 3: Photo upload + status timeline + change requests
- Sprint 4: GDPR-lite data export + 30-day grace deletion + audit PII scrubber
- Sprint 5: Web frontend — every endpoint has a UI path
- Sprint 6: E2E gate green, axe zero Critical/Serious, Lighthouse CI wired

### Phase 2 Gate — CLOSED 2026-04-24

- **PR #28** merged to main at commit `a42ad7b` on 2026-04-24T15:36:04Z. Six grouped sprint commits on `phase2-customer-portal`: a6fb519, 5611c90, e07dcb0, 87d8ef4, da779fb, cf643ea.
- **Backend:** 195/195 green, 95.80% coverage (85% floor).
- **E2E:** 12/12 Playwright tests green in CI, zero Critical/Serious axe violations, Lighthouse Accessibility + Best Practices ≥ 0.9 on `/login` + `/register`.
- **CI jobs on merge commit:** Lint ✅ Test ✅ E2E ✅ Deploy-Staging ✅. Deploy-Production is manual `workflow_dispatch`.
- **Staging deploy fired automatically on the merge-to-main push** and succeeded — first real deploy of the `temple-api-staging` + `temple-web-staging` Fly apps. Staged secrets activated.

### Phase 2 — deliberate deferrals / deviations (not bugs)

All items are documented in `known-issues.md` or the relevant ADR so nothing is silent.

- **Phase 2 completion checklist items that defer to later phases:**
  - "Sales Rep resolves change request → customer receives resolution email" → Phase 3 (Sales CRM endpoints don't exist yet).
  - "Admin can modify `AppConfig.intake_fields_visible` → form reflects changes without code deploy" → Phase 4 (Admin Panel).
  - "SMS warning copy on registration" — register page doesn't surface an SMS preference toggle (the SMS opt-in is on the Account page post-login). `Standard SMS messaging rates may apply…` copy + A2P STOP/HELP wiring lands with the real Twilio A2P go-live (tracked in `known-issues.md`).
  - "Customer cannot submit a second change request while one is pending" — not enforced server-side in Sprint 3. Tracked as a new known-issue; first Phase 3 ticket if sales rep dashboards need it.
- **Security-stronger deviation from spec:** cross-customer access to another user's equipment record returns **404**, not 403, to avoid leaking the ID space. Confirmed by `test_equipment_intake.py::test_cross_customer_detail_is_404`. This is the intended posture.
- **UI shape:** intake form is a single page rather than the 3-step wizard the spec describes. Sprint 5 note acknowledged visual polish + wizard flow as iterable; no user-blocking impact.
- **Not yet surfaced:** 2FA setup/verify/disable UI (backend live; deferred to Phase 5 alongside iOS TOTP). Password-reset + change-email UI (backend live since Phase 1; deferred to Phase 6 polish).

### Phase 2 — operational follow-ups before real customer data lands on prod

Tracked in `known-issues.md` (prod-go-live bundle). None of these block Phase 3 work.

- Neon Pro upgrade (PITR on prod branch)
- Rotate `neondb_owner` password (leaked in chat)
- Create `temple-sweeper` Fly app (hourly retention sweep)
- Create `temple-notifications` Fly app (drains `notification_jobs`)
- Confirm Twilio A2P 10DLC approval (SMS dispatch is silently skipped until `twilio_messaging_service_sid` is set)
- Final lawyer-reviewed ToS + Privacy text (drafts live at `api/content/tos/v1.md` + `api/content/privacy/v1.md`)

---

## Phase 3 — Sales CRM, Lead Routing & Shared Calendar (In Progress, started 2026-04-24)

Full spec: `dev_plan/03_phase3_sales_crm.md`

### Sprint 1: Record Locking + Duplicate Change-Request Guard — COMPLETE (verified green 2026-04-24)

Spec: Epic 3.5 in `dev_plan/03_phase3_sales_crm.md` + Phase 2 Sprint 3 carry-over.

- [x] `api/alembic/versions/009_phase3_change_request_resolution_and_uniqueness.py` — adds `change_requests.resolved_by` FK to `users`; partial UNIQUE index `ux_change_requests_one_pending_per_record` (`equipment_record_id WHERE status='pending'`). DB-level enforcement of Phase 2 Feature 2.4.1.
- [x] `api/database/models.py` — `ChangeRequest.resolved_by` column added to ORM.
- [x] `api/services/record_lock_service.py` — POC impl backed by `record_locks` table. `acquire/heartbeat/release/override` — 15-min TTL, self-heal expired rows, unique constraint as atomic primitive. Redis-swap contract preserved per ADR-013 addendum.
- [x] `api/schemas/record_lock.py` — `LockAcquireRequest`, `LockInfoOut`, `LockConflictOut` shapes.
- [x] `api/routers/record_locks.py` — POST acquire, PUT heartbeat, DELETE release, DELETE override. RBAC: any authed user for acquire/heartbeat/release; `sales_manager`/`admin` for override. Every state change writes `audit_logs` (`record_lock.acquired`, `record_lock.released`, `record_lock.overridden`).
- [x] `api/services/change_request_service.py` — duplicate-pending submit now caught via `IntegrityError` from the partial unique index and surfaced as `409 Conflict` with human-readable detail.
- [x] `api/main.py` + `api/routers/health.py` — wired new router; bumped `_EXPECTED_MIGRATION_HEAD` to `"009"`.
- [x] `api/tests/integration/test_record_locks.py` — 10 tests: acquire happy/audit, conflict 409 with locked_by, same-user refreshes, expired-lock replaced by other user, heartbeat refresh/404/non-owner 404, release happy/idempotent, manager override happy/audit trail, customer forbidden from override, cross-record isolation.
- [x] `api/tests/integration/test_change_requests.py` — 2 new tests for duplicate guard (409 on second pending, re-allowed after first is resolved).

**Full test gate: 209/209 green, 95.86% coverage (85% floor)**

**Design notes:**
- **Postgres advisory locks not needed.** ADR-002 mentioned `pg_try_advisory_lock` as an option, but the UNIQUE constraint on `(record_id, record_type)` is itself the atomic primitive — a concurrent second INSERT surfaces `IntegrityError` which the service maps to `LockHeldError`. Simpler, auditable, visible in normal SQL tooling.
- **Release deletes the row.** Overridden flags on the table (`overridden_by`, `overridden_at`) are vestigial — audit trail lives in `audit_logs`. Swap to Redis will drop the whole table.
- **Partial unique index vs. app-level check.** Belt-and-suspenders would be redundant; the DB enforces "one pending per record" which makes the rule impossible to violate from any callsite. The 409 path exercises the error surface.

**Deferred (flagged, not regressed):**
- Expired lock sweep: today a fresh acquire self-heals a stale row. Hourly cleanup via `temple-sweeper` (migration 010 or 011 will extend `fn_sweep_retention()`); not needed until traffic makes accumulation matter.
- `/sales/equipment/{id}` integration with lock lifecycle on the UI side — Sprint 2 (Sales Dashboard) wires that.

---

### Sprint 2: Sales Dashboard + Record View + Cascade + Manual Publish + Change-Request Resolution — COMPLETE (verified green 2026-04-24)

Spec: Epic 3.1 + 3.2 + 3.3 + 3.6 + parts of 3.7 in `dev_plan/03_phase3_sales_crm.md`.

**Backend (all new):**
- [x] `api/schemas/sales.py` — `EquipmentRowOut`, `CustomerGroupOut`, `DashboardResponse`, `StatusEventSummary`, `ChangeRequestSummary`, `EquipmentDetailOut`, `AssignmentPatch`, `CascadePatch`, `CascadeResult`, `ChangeRequestResolve`, `ChangeRequestResolveOut`, `PublishResponse`. Patch schemas use `model_fields_set` so "unset" and "null" are distinguishable over the wire.
- [x] `api/services/sales_service.py` — `list_dashboard` (role-scoped, grouped by customer, newest-first), `get_record_detail` (eager-loads customer, status_events, change_requests, consignment_contract, public_listing, appraisal_reports), `ensure_lock_held` (gate for PATCH assignment — 409 if no active lock), `apply_assignment` (writes via `record_transition` when nothing else changes, audits only on delta), `cascade_assignment` (touches `status='new_request'` only; rest returned in `skipped_record_ids`), `publish_record` (requires status=`esigned_pending_publish` + signed contract + ≥1 appraisal report; transitions record to `listed`, upserts `PublicListing`).
- [x] `api/routers/sales.py` — `GET /sales/dashboard`, `GET /sales/equipment/{id}`, `PATCH /sales/equipment/{id}`, `PATCH /sales/customers/{id}/cascade-assignments`, `POST /sales/equipment/{id}/publish`, `PATCH /sales/change-requests/{id}`. All behind `require_roles("sales", "sales_manager", "admin")`.
- [x] `api/services/change_request_service.py` — added `resolve_change_request()`. On `status='resolved'` + `request_type='withdraw'` calls `equipment_status_service.record_transition(to_status='withdrawn')`. Audits `change_request.resolved|rejected`; enqueues customer email via NotificationService with idempotency key `change_request_resolution:{id}:{status}`.
- [x] `api/main.py` — wires `sales_router`.
- [x] `api/tests/integration/test_sales_dashboard.py` (6), `test_sales_assignment.py` (5), `test_cascade_assignment.py` (4), `test_manual_publish.py` (5), `test_change_request_resolution.py` (6) — +26 integration tests, all green.

**Frontend (all new):**
- [x] `web/src/api/sales.ts` — API wrappers: `getDashboard`, `getEquipmentDetail`, `patchAssignment`, `cascadeAssignments`, `publishListing`, `resolveChangeRequest`, `acquireLock`, `heartbeatLock`, `releaseLock`, `overrideLock`.
- [x] `web/src/hooks/useRecordLock.ts` — lifecycle hook: acquire on mount, heartbeat every 60s, release on unmount, parses `LockConflict` JSON body from 409.
- [x] `web/src/components/CascadeAssignModal.tsx` — bulk reassign sales_rep + appraiser for every `new_request` under a customer, confirm checkbox required.
- [x] `web/src/components/RecordLockIndicator.tsx` — banner per lock state (acquiring / held / expired / conflict / error). Conflict state exposes "Break lock" to sales_manager + admin only.
- [x] `web/src/components/PhoneLink.tsx` — `tel:` helper; strips non-digits for href, renders em-dash when absent.
- [x] `web/src/pages/SalesDashboard.tsx` — grouped-by-customer dashboard. Scope toggle (mine / all) for managers only; click-to-call cell + office, cascade button per group opens modal.
- [x] `web/src/pages/SalesEquipmentDetail.tsx` — lock-aware detail view. Customer card + equipment card (read-only) + assignment form (disabled unless `lock.status === "held"`) + PublishCard (only rendered when `status === "esigned_pending_publish"`, shows missing gates) + inline ChangeRequestResolver per pending request with resolved/rejected buttons + notes + status timeline.

**Supporting (modified):**
- [x] `web/src/api/types.ts` — Phase 3 types: `LockInfo`, `LockConflict`, `EquipmentRow`, `CustomerGroup`, `SalesDashboardResponse`, `SalesStatusEvent`, `SalesChangeRequest`, `SalesEquipmentDetail`, `AssignmentPatch`, `CascadeResult`, `ChangeRequestResolveRequest/Response`, `PublishResponse`.
- [x] `web/src/components/Layout.tsx` — sales-side nav when `user.role ∈ {sales, sales_manager, admin}`; customer-side nav unchanged.
- [x] `web/src/components/ui/StatusBadge.tsx` — added `pending_manager_approval`, `approved_pending_esign`, `esigned_pending_publish`, `withdrawn` mappings.
- [x] `web/src/App.tsx` — `/sales` and `/sales/equipment/:id` routes wrapped in `ProtectedRoute + Layout`; old placeholder retired.

**Full test gate: 235/235 green, 96.16% coverage (85% floor)**

**Design decisions this sprint:**
- **Lock required for PATCH assignment.** Router calls `sales_service.ensure_lock_held()` before any write; 409 if no valid lock. Frontend acquires on detail-page mount via `useRecordLock`.
- **Cascade only touches `status='new_request'` rows.** Later-status rows are returned in `skipped_record_ids` + human-readable `skipped_reason` so the modal can surface what was left alone.
- **Publish transitions to `'listed'`** (not `'published'`) — matches the code vocabulary in `equipment_status_service._CUSTOMER_EMAIL_STATUSES`. Record must be in `esigned_pending_publish` with a signed `ConsignmentContract` and ≥1 `AppraisalReport`.
- **Withdraw on resolve** → `record_transition(to_status='withdrawn')`. Other resolution paths don't change record status.
- **Cross-record access:** sales/sales_manager/admin can read any record via `/sales/equipment/{id}`; listing is filtered by default to `assigned_sales_rep_id == caller`. Managers flip to `scope=all` in the UI.

**Deferred (flagged, not regressed):**
- User pickers (sales rep + appraiser dropdowns) — today the UI takes raw UUIDs. Phase 4 (Admin Panel) will ship the searchable picker component and wire it into CascadeAssignModal + the detail assignment form.
- Lead Routing Engine (ad-hoc / geographic / round-robin) — Sprint 3.
- Scheduling + shared calendar + drive-time — Sprint 4.
- Workflow notification preferences UI — Sprint 5.

**Endpoints (new in Sprint 2):**
- `GET  /api/v1/sales/dashboard` — role-scoped, grouped by customer, optional `scope`, `status`, `assigned_rep_id` filters
- `GET  /api/v1/sales/equipment/{id}` — full detail (customer + equipment + lock metadata + history + change requests)
- `PATCH /api/v1/sales/equipment/{id}` — update sales_rep / appraiser assignments; requires held lock
- `PATCH /api/v1/sales/customers/{id}/cascade-assignments` — bulk assign for all `new_request` rows under a customer
- `POST /api/v1/sales/equipment/{id}/publish` — manual publish; transitions to `listed`, upserts `PublicListing`
- `PATCH /api/v1/sales/change-requests/{id}` — resolve or reject pending change request; withdraw-resolves flip record to `withdrawn`

**Routes (new in the web app):**
- `/sales` — dashboard
- `/sales/equipment/:id` — record view / edit

---

## Phase 4–8 — Not started
