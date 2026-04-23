# Phase 1 — Core Infrastructure, Authentication & RBAC

> **Prerequisite reading:** `00_overview.md`, `project_notes/decisions.md` (ADR-001), `10_operations_runbook.md`, `11_security_baseline.md`
> **Estimated scope:** 4–5 weeks (extended from 3–4 to absorb security hardening and three-environment setup)
> **Deliverable:** Running Fly.io platform (dev, staging, prod) with Neon Postgres + Cloudflare R2 + Cloudflare WAF, authenticated API with full auth hardening, seeded role system, CI/CD pipeline with auto-rollback, observability, and security scanning. Every infra feature below is built for Fly.io today with a documented GCP equivalent recorded in `12_gcp_production_target.md` for the migration path.

---

## Epic 1.1 — Platform Infrastructure & Project Scaffolding

### Feature 1.1.1 — Monorepo Project Structure

**User Story:**
As an Admin, I want the project to be organized in a clean monorepo so that all services (API, web frontend, iOS app, infra) are versioned together and Claude Code can navigate the codebase predictably.

**Acceptance Criteria:**
- Monorepo root contains: `/api` (FastAPI), `/web` (React/TypeScript), `/ios` (SwiftUI), `/infra` (Terraform), `/scripts` (migration + seed scripts)
- Each service has its own `README.md`, dependency manifest, and Dockerfile (where applicable)
- Root `Makefile` with targets: `dev`, `test`, `lint`, `build`, `deploy`
- All Dockerfiles pin base image versions (no `latest` tag)
- `.env.example` file at root with all required env var keys documented; no default values for secrets
- `.gitignore` excludes `.env`, `*.pem`, `__pycache__`, `.DS_Store`, iOS `DerivedData/`
- Pre-commit hooks installed: `ruff` (Python), `eslint` (TypeScript), `swiftlint` (Swift)

---

### Feature 1.1.2 — Platform Infrastructure Provisioning (Fly.io + Neon + Cloudflare)

**User Story:**
As an Admin, I want all hosting infrastructure defined as code so that environments are reproducible, configuration changes are reviewed like code, and the platform can be recreated from source if the account is lost or we need to migrate providers.

**Acceptance Criteria:**
- **Six Fly.io apps provisioned** per `10_operations_runbook.md` §2.3: `temple-api-{dev,staging,prod}` and `temple-web-{dev,staging,prod}`. All in the `temple-he` Fly organization with 2FA required on every member account.
- **Neon Postgres project** with three branches (`dev`, `staging`, `prod`) per `10_operations_runbook.md` §2.4; Pro plan active before any real customer data lands in prod (for PITR).
- **Three Cloudflare R2 buckets** (`temple-he-photos`, `temple-he-reports`, `temple-he-backups`) with object versioning enabled, per `10_operations_runbook.md` §2.5.
- **Cloudflare zone** on the production domain with DNS proxy enabled, Managed WAF Ruleset on, edge rate limiting on `/api/*` set to 100 req/min per IP, SSL/TLS Full (Strict), HSTS enabled with 6-month max-age/includeSubdomains/preload, per `10_operations_runbook.md` §2.6.
- **Fly `fly.toml` per app checked into git** defining `min_machines_running`, concurrency limits, health check, graceful shutdown, and internal port — values per `10_operations_runbook.md` §10.1.
- **Terraform-style declarative config for Cloudflare** (via `cloudflare/cloudflare` Terraform provider): zone settings, WAF rules, rate limits, DNS records. `terraform plan` must succeed in CI before any `apply`.
- **Fly apps on private 6PN network** for app-to-app traffic (API → backup Machine, web → API optional); public ingress only via Fly Proxy at `:443` per `10_operations_runbook.md` §10.2.
- **Environment sizing:**
  - Dev: `shared-cpu-1x`, 256 MB, `min_machines_running=0`, Neon `dev` branch (shares compute with staging)
  - Staging: `shared-cpu-1x`, 512 MB, `min_machines_running=0`, Neon `staging` branch
  - Prod: `shared-cpu-1x`, 512 MB, `min_machines_running=1`, Neon `prod` branch (dedicated compute, PITR 7 days)
- **All images tagged** with git SHA (`temple-api:git-<sha>`); no `latest` tag in production Fly releases.
- **Per-app Fly deploy tokens** stored in GitHub Actions secrets (not personal tokens), rotated every 90 days per `10_operations_runbook.md` §9.4. Local copies destroyed after upload to GitHub secrets.
- **Daily off-site backup Fly Machine** running the `pg_dump` → R2 script defined in `10_operations_runbook.md` §6.2; verified working on staging before prod goes live.

**GCP target equivalent (for future migration, per `12_gcp_production_target.md` §2):**
- Fly apps → Cloud Run services in three GCP projects (`temple-dev`, `temple-staging`, `temple-prod`)
- Neon branches → Cloud SQL instances with PITR and private IP
- R2 buckets → Cloud Storage buckets with object versioning and lifecycle policies
- Cloudflare WAF → Cloud Armor policy on the API load balancer
- Fly deploy tokens → Workload Identity Federation (no static keys)
- `fly.toml` → Terraform resource blocks
- Record the migration trigger and execute per `13_hosting_migration_plan.md`.

---

### Feature 1.1.3 — CI/CD Pipeline

**User Story:**
As a developer, I want automated testing and deployment on every push so that broken code never reaches production and deployments are one-click with easy rollback.

**Acceptance Criteria:**
- GitHub Actions pipeline per-environment (see `10_operations_runbook.md` §4 for the visual pipeline):
  - Push to `develop` branch → lint → test → security scans → build → `flyctl deploy --app temple-api-dev`
  - Merge to `main` → same steps → `flyctl deploy --app temple-api-staging` → run E2E + accessibility tests
  - Tag `v*` → same steps → **manual approval gate** → `flyctl deploy --app temple-api-prod --strategy bluegreen` → smoke tests → traffic swap
- Three GitHub environments configured (`dev`, `staging`, `prod`) with protection rules; `prod` requires Jim's manual approval
- Security scan workflow (`.github/workflows/security.yml`) runs on every PR and scheduled weekly — Dependabot + Trivy + gitleaks + pip-audit + npm audit + OSV-Scanner per `10_operations_runbook.md` §9
- Production deploy uses Fly **blue-green strategy**: new Machine starts, health-checks green, then traffic swaps atomically; old Machine drains
- **Auto-rollback** on smoke-test failure: workflow runs `flyctl releases rollback --yes` to restore the prior release and posts to `#alerts` Slack
- **Maintenance mode middleware** available on the API — toggled via `MAINTENANCE_MODE` env var (set via `fly secrets set`); when true, all requests except `/api/v1/health` return a friendly 503 HTML page (used in the panic-path rollback in `10_operations_runbook.md` §5.3)
- Database migrations run via `flyctl ssh console --command "alembic upgrade head"` *before* the new Machine starts; failed migrations block the deploy and alert
- API Docker image built inside the GitHub Actions runner via `flyctl deploy --build-only` (or `docker buildx build --push` to GitHub Container Registry) tagged with `git-<sha>`; Fly pulls the image by digest
- Frontend built and deployed to `temple-web-<env>` Fly app; each release is a full immutable deploy — rollback by `flyctl releases rollback`
- Sentry release created on every deploy (`sentry-cli releases new git-<sha>`) so errors are attributable to a specific release
- All tests must pass before deploy step runs
- Secrets never logged or echoed in CI output; GitHub Actions masks `FLY_API_TOKEN` and all `SENTRY_*` / `NEON_*` values
- **Per-environment deploy tokens** scoped via `flyctl tokens create deploy --app <app>` so a dev-env token cannot deploy to prod
- Deployment rollback runbook documented in `10_operations_runbook.md` §5

**GCP target equivalent:** the same workflow runs against Cloud Run via Workload Identity Federation instead of Fly tokens; `gcloud run deploy --no-traffic` + `update-traffic` replaces `flyctl deploy --strategy bluegreen`. Migration details in `13_hosting_migration_plan.md`.

---

### Feature 1.1.4 — Local Development Environment (Docker Compose)

**User Story:**
As a developer, I want to run the full stack on my laptop without needing cloud infrastructure so that I can iterate fast and keep cloud costs low.

**Acceptance Criteria:**
- `docker-compose.yml` at repo root brings up: Postgres 16 and a local SMTP catcher (Mailpit) on ports that don't collide with common defaults
- No Redis in local or Fly POC — record locking uses Postgres advisory locks (see Feature 1.4.x locking service); behavior matches staging/prod exactly
- `.env.example` at the root documents every variable the API and web frontend need to run locally
- `make dev` starts Docker, runs Alembic migrations, seeds the database, and launches API on `:8000` and web on `:5173`
- `make reset` tears down the local stack, wipes volumes, and brings it back up fresh (for when something goes sideways)
- Documented in `README.md` with a 5-step "quickstart" so a new developer (or future-you) can run the stack in < 10 minutes
- Local Docker never talks to Fly or Neon — everything runs against local Postgres/Mailpit
- Optional: `make dev-pr` spawns an ephemeral Neon branch for integration work (requires `NEON_API_KEY` in `.env`), per `10_operations_runbook.md` §3.4

**GCP target equivalent:** Redis comes back at GCP migration time; `RecordLockService` interface does not change — implementation swaps from advisory locks to Redis heartbeats.

---

### Feature 1.1.5 — Observability & Monitoring Setup

**User Story:**
As the sole operator, I want structured logs and error tracking from day one so that I can investigate production issues quickly without tail-grepping raw logs.

**Acceptance Criteria:**
- **Structured JSON logging** in the API: every request emits a log entry with fields `timestamp`, `severity`, `request_id`, `user_id`, `route`, `status_code`, `latency_ms`, `error` (per `10_operations_runbook.md` §7.2)
- Every request carries a `X-Request-ID` header (generated if not present) threaded through all logs for that request
- **Sentry** SDK integrated into the API (`sentry-sdk[fastapi]`) and the web frontend (`@sentry/react`) — DSNs stored in `fly secrets` per environment (Secret Manager after GCP migration)
- Sentry releases tagged with git SHA on every deploy; source maps uploaded for the web frontend
- **BetterStack log shipping** enabled on prod API and prod web apps; Fly's short-retention platform logs are forwarded to BetterStack for 1 GB/month free retention (per `10_operations_runbook.md` §7.2)
- **Alert policies** configured per the table in `10_operations_runbook.md` §7.3, split across:
  - UptimeRobot (external HTTP checks on prod, SMS + email + Slack)
  - BetterStack log-based alerts (5xx rate, latency, error patterns)
  - Fly Machine metrics → Slack (OOM, CPU sustained)
  - Sentry → Slack (new issue in prod)
  - Cloudflare Notifications → email (WAF spike)
- **Slack webhook** configured as the primary notification channel; webhook URL in `fly secrets`
- **UptimeRobot monitor** on `https://api.templehe.com/api/v1/health` from multiple regions, 5-minute interval, alerts after 2 consecutive failures
- `/api/v1/health` endpoint returns 200 with a JSON status of its dependencies (DB reachable, migrations up-to-date, R2 reachable) so Fly can use it as a readiness probe and the admin panel can surface it in Phase 4

**GCP target equivalent:** BetterStack replaced by Cloud Logging, UptimeRobot by Cloud Monitoring uptime checks, Cloudflare by Cloud Armor (optional). Sentry, Slack, and the structured logging format all carry over unchanged.

---

## Epic 1.2 — Database Schema & Migrations

### Feature 1.2.1 — Core Schema Migrations

**User Story:**
As a developer, I want a versioned database schema managed by Alembic so that schema changes are tracked, reversible, and applied consistently across environments.

**Acceptance Criteria:**
- Alembic configured with `alembic.ini` reading the Postgres connection string from the `DATABASE_URL` env var (never hardcoded); points at Neon today, swaps to Cloud SQL transparently after GCP migration
- Initial migration creates all core tables — grouped by domain:

  **Auth & Users**
  - `users` — id, email, password_hash, first_name, last_name, role, status, google_id, totp_secret_enc, profile_photo_url
  - `roles` — id, slug, display_name (reference table; rows seeded, not user-managed)
  - `notification_preferences` — id, user_id FK, channel ENUM(email|sms|slack), slack_user_id, phone_number

  **Customers & Equipment**
  - `customers` — id, user_id FK, business_name, submitter_name, title, address fields, business_phone, business_phone_ext, cell_phone, communication_prefs JSONB, state, zip
  - `equipment_records` — id, customer_id FK, status ENUM, assigned_sales_rep_id FK, assigned_appraiser_id FK, created_at, updated_at, deleted_at
  - `appraisal_submissions` — id, equipment_record_id FK, category_id FK, all intake + scoring fields, approved_purchase_offer, suggested_consignment_price, management_review_required, hold_for_title_review, red_flags JSONB, comparable_sales JSONB, overall_score, score_band, submitted_at
  - `appraisal_photos` — id, appraisal_submission_id FK, slot_label, gcs_path, capture_timestamp, gps_latitude, gps_longitude, gps_missing, gps_out_of_range, file_size_bytes
  - `component_scores` — id, appraisal_submission_id FK, category_component_id FK, raw_score DECIMAL(3,2), weight_at_time_of_scoring DECIMAL(6,4), notes

  **Equipment Categories (fully dynamic — see Phase 4, Epic 4.8)**
  - `equipment_categories` — id, name VARCHAR(255), slug VARCHAR(255) UNIQUE, status ENUM(active|inactive), display_order INT, created_by UUID FK, created_at, updated_at, deleted_at
  - `category_components` — id, category_id FK, name VARCHAR(255), weight_pct DECIMAL(6,4), display_order INT, active BOOLEAN
  - `category_inspection_prompts` — id, category_id FK, label VARCHAR(500), response_type ENUM(yes_no_na|text|scale_1_5), required BOOLEAN, display_order INT, active BOOLEAN
  - `category_attachments` — id, category_id FK, label VARCHAR(255), description TEXT, display_order INT, active BOOLEAN
  - `category_photo_slots` — id, category_id FK, label VARCHAR(255), helper_text TEXT, required BOOLEAN, display_order INT, active BOOLEAN
  - `category_red_flag_rules` — id, category_id FK, condition_field VARCHAR(100), condition_operator ENUM(equals|is_true|is_false), condition_value VARCHAR(255), actions JSONB, label VARCHAR(255), active BOOLEAN

  **Workflow & Scheduling**
  - `appraisal_reports` — id, equipment_record_id FK, appraisal_submission_id FK, gcs_path, generated_at
  - `consignment_contracts` — id, equipment_record_id FK, envelope_id, status ENUM(sent|completed|declined|voided), signed_at
  - `change_requests` — id, equipment_record_id FK, request_type ENUM(delete_listing|update_description|update_hours_condition), customer_notes TEXT, status ENUM(pending|resolved|rejected), resolution_notes TEXT, requires_manager_reapproval BOOLEAN, submitted_at, resolved_at
  - `lead_routing_rules` — id, rule_type ENUM(ad_hoc|geographic|round_robin), priority INT, conditions JSONB, assigned_user_id FK, round_robin_index INT, is_active BOOLEAN
  - `calendar_events` — id, equipment_record_id FK, appraiser_id FK, scheduled_at TIMESTAMP, duration_minutes INT, site_address TEXT, drive_time_buffer_minutes INT, cancelled_at
  - `public_listings` — id, equipment_record_id FK, listing_title, asking_price, primary_photo_gcs_path, status ENUM(active|sold|withdrawn), published_at, sold_at

  **Platform**
  - `audit_logs` — id, event_type, actor_id FK, actor_role, target_type, target_id, before_state JSONB, after_state JSONB, ip_address, user_agent, created_at (append-only)
  - `record_locks` — id, record_id UUID, record_type VARCHAR, locked_by FK, locked_at, expires_at, overridden_by FK, overridden_at
  - `app_config` — id, key VARCHAR(255) UNIQUE, value JSONB, category VARCHAR(100), field_type VARCHAR(50), updated_by FK, updated_at
  - `analytics_events` — id, session_id, user_id FK, event_type VARCHAR, page VARCHAR, metadata JSONB, created_at
  - `inquiries` — id, public_listing_id FK, first_name, last_name, email, phone, message TEXT, created_at
  - `comparable_sales` — id, make, model, year, hours, sale_price, sale_date, source VARCHAR, category_id FK, created_at

- All tables include `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`, `created_at TIMESTAMPTZ DEFAULT now()`, `updated_at TIMESTAMPTZ DEFAULT now()` (updated via trigger), `deleted_at TIMESTAMPTZ NULL` (soft delete, except `audit_logs` which has no `deleted_at`)
- Foreign keys defined with explicit `ON DELETE` behavior:
  - User-owned data (customers, equipment_records): `ON DELETE RESTRICT` — never cascade-delete customer history
  - Child records (appraisal_photos, component_scores): `ON DELETE CASCADE` from their parent submission
  - `audit_logs`: no FK constraints — records remain even if the referenced user is deleted
- All migrations are idempotent and reversible (`upgrade` / `downgrade`)
- Migrations run automatically in CI before tests; never auto-run in production (manual gate)
- Indexes:
  - `users.email` (UNIQUE)
  - `equipment_records.customer_id`, `equipment_records.status`, `equipment_records.assigned_sales_rep_id`
  - `equipment_categories.slug` (UNIQUE)
  - `category_components.category_id`, `category_photo_slots.category_id`, `category_red_flag_rules.category_id`
  - `calendar_events.appraiser_id`, `calendar_events.scheduled_at`
  - `analytics_events.created_at`, `analytics_events.event_type`
  - `audit_logs.target_id`, `audit_logs.actor_id`, `audit_logs.created_at`

**Key Schema Notes:**
- `equipment_records.status` enum: `new_request | appraisal_scheduled | appraisal_completed | pending_manager_approval | approved_pending_esign | esigned_pending_publish | published | withdrawn | rejected`
- `equipment_categories` is the source of truth for all category configuration — do not store category structure in `app_config`. The `app_config` table is reserved for platform-wide operational settings (notification toggles, thresholds, drive time buffers, PDF branding, etc.)
- `record_locks` references Redis TTL (the live lock) but also has a DB row (for audit). A lock that expired in Redis but still has a DB row is treated as expired.
- `component_scores.weight_at_time_of_scoring` captures the weight in effect when the appraisal was submitted — so historical score recalculations remain accurate even after an Admin changes component weights later

---

### Feature 1.2.2 — Seed Data

**User Story:**
As a developer, I want a seed script that populates reference data so that I can run the app locally without manual data entry.

**Acceptance Criteria:**
- Seed script populates the following in order (respects FK dependencies):
  1. `roles` — six role rows (customer, sales, appraiser, sales_manager, admin, reporting)
  2. `equipment_categories` — all 15 default categories from `01_checklists/`, each with `status = active`
  3. `category_components` — all components + weights per category from `03_implementation_package/06_scoring_and_rules_logic.csv`
  4. `category_inspection_prompts` — all inspection prompts per category from `02_schema_and_dictionary/01_normalized_app_field_schema_v1.md`
  5. `category_attachments` — all attachment/option rows per category from `02_schema_and_dictionary/01_normalized_app_field_schema_v1.md`
  6. `category_photo_slots` — all required photo slots per category from `02_schema_and_dictionary/01_normalized_app_field_schema_v1.md`, with `required = true`
  7. `category_red_flag_rules` — all red flag rules per category from `03_implementation_package/06_scoring_and_rules_logic.csv`
  8. `app_config` — default entries for all operational config keys (notification toggles, thresholds, drive time buffers, PDF branding, etc.) — NOT category structure (that lives in the category tables above)
  9. One Admin user — email and password read from env vars `SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD`; never hardcoded
- Seed script is idempotent (safe to run multiple times)
- Seed script located at `/scripts/seed.py` with a `make seed` target
- Running `make seed` in CI populates the test database before integration tests

---

## Epic 1.3 — Authentication

### Feature 1.3.1 — Email/Password Registration with Email Confirmation

**User Story:**
As a new user, I want to register with my email and password and receive a confirmation email so that TempleHE can verify I am a real person before granting portal access.

**Acceptance Criteria:**
- `POST /api/v1/auth/register` accepts: `email`, `password` (min 12 chars, 1 uppercase, 1 number, 1 special char), `first_name`, `last_name`
- Password hashed with bcrypt (cost factor 12) before storage; plaintext never stored or logged
- On successful registration, user record created with `status = pending_verification`
- Confirmation email sent immediately via SendGrid with a unique signed token link (JWT, 24-hour expiry)
- `GET /api/v1/auth/verify-email?token=<jwt>` validates the token, sets `status = active`, returns 200
- Expired or invalid tokens return 400 with a human-readable error message
- Portal access (`POST /api/v1/auth/login`) returns 403 if `status = pending_verification` with message: "Please verify your email address before logging in."
- Resend confirmation email endpoint: `POST /api/v1/auth/resend-verification` (rate-limited: max 3 per hour per email)
- All registration events written to `audit_logs`

---

### Feature 1.3.2 — Google SSO

**User Story:**
As a user, I want to sign in with my Google account so that I don't need to manage a separate password for this platform.

**Acceptance Criteria:**
- OAuth2 flow using Google Identity Platform; client ID and secret stored in `fly secrets` (moves to Secret Manager after GCP migration)
- `GET /api/v1/auth/google` initiates OAuth2 redirect
- `GET /api/v1/auth/google/callback` handles the callback, creates or updates the user record, issues a session JWT
- If Google account email matches an existing password account, the accounts are linked (not duplicated)
- Google SSO users skip the email confirmation step (Google-verified email is sufficient)
- Google SSO users cannot set a password unless they explicitly request one via the "Set Password" flow
- Profile photo from Google is stored in the user record (optional field)

---

### Feature 1.3.3 — JWT Session Management

**User Story:**
As a user, I want my session to remain active while I am using the platform and expire when I stop so that my account is not left open indefinitely.

**Acceptance Criteria:**
- Login returns an access token (JWT, 15-minute expiry) and a refresh token (opaque, stored in Redis, 7-day expiry)
- Access token carries: `user_id`, `email`, `role`, `exp`
- `POST /api/v1/auth/refresh` accepts the refresh token and issues a new access token
- Refresh token rotation: each refresh issues a new refresh token and invalidates the old one
- `POST /api/v1/auth/logout` invalidates the refresh token in Redis
- All API routes except `/auth/*` and `/public/*` require a valid access token in `Authorization: Bearer <token>`
- Token validation middleware returns 401 with `WWW-Authenticate: Bearer` on failure

---

### Feature 1.3.4 — Two-Factor Authentication (2FA)

Full acceptance criteria below. Also see `11_security_baseline.md` §1 → Feature 1.3.7 for recovery flow when all 10 codes are consumed and TOTP is lost.


**User Story:**
As a user, I want to optionally enable two-factor authentication so that my account is protected even if my password is compromised.

**Acceptance Criteria:**
- `POST /api/v1/auth/2fa/setup` generates a TOTP secret and returns a QR code URL for authenticator app setup
- `POST /api/v1/auth/2fa/confirm` verifies the first TOTP code and activates 2FA on the account
- When 2FA is enabled, login flow returns `{ "requires_2fa": true, "partial_token": "<short-lived token>" }` instead of a full session
- `POST /api/v1/auth/2fa/verify` accepts the partial token + TOTP code and returns full session tokens
- `POST /api/v1/auth/2fa/disable` requires the current TOTP code to disable 2FA
- Recovery codes: 10 single-use recovery codes generated at 2FA setup; downloadable once
- Admin can force-enable 2FA requirement for specific roles (configurable in Admin panel)
- TOTP secret stored encrypted at rest in the database

---

### Feature 1.3.5 — Password Reset Flow

Full detail in `11_security_baseline.md` §1. Summary:

**Acceptance Criteria:**
- `POST /api/v1/auth/password-reset-request` always returns 200 (prevents email enumeration); sends signed JWT reset link (30-min expiry) only if email matches an active user
- `POST /api/v1/auth/password-reset-confirm` validates token, applies password complexity rules, bcrypt-hashes, invalidates all existing refresh tokens, sends notification email to the user
- Rate limited: 3 requests per email per hour, 10 per IP per hour
- All reset events written to `audit_logs`

---

### Feature 1.3.6 — Email Change Flow

See `11_security_baseline.md` §1 for full acceptance criteria. Summary: requires current-password re-verification, double confirmation (verification email to new address + notification to old address), and a cancellation grace period.

---

### Feature 1.3.7 — Rate Limiting on Auth Endpoints

See `11_security_baseline.md` §2 for full acceptance criteria. Summary:
- Per-endpoint rate limits via `slowapi` backed by Redis (limits table in security baseline §2)
- 429 response with `Retry-After` header on exceed
- Sustained abuse (> 20 429s from same IP in 5 min) emits a Sentry event

---

### Feature 1.3.8 — Account Lockout

See `11_security_baseline.md` §2. Summary:
- 5 failed logins in 15 minutes → account status `locked`, login returns 423 with friendly message
- Lockout auto-releases after 30 minutes; password reset or admin action also releases
- Lockout events written to `audit_logs`

---

### Feature 1.3.9 — New-Device Login Notifications

See `11_security_baseline.md` §2. Summary: on successful login from a previously-unseen UA family + IP ASN combination, send an informational email to the user.

---

## Epic 1.4 — Role-Based Access Control (RBAC)

### Feature 1.4.1 — Role System & Permission Guards

**User Story:**
As an Admin, I want each platform feature to be gated by role so that users can only access what their job requires.

**Acceptance Criteria:**
- Six roles defined: `customer`, `sales`, `appraiser`, `sales_manager`, `admin`, `reporting`
- Role stored on the JWT and validated on every protected endpoint
- Permission matrix enforced via a `require_roles(*roles)` FastAPI dependency — not inline conditionals
- Role permission matrix (minimum):

| Endpoint Category | customer | sales | appraiser | sales_manager | admin | reporting |
|---|---|---|---|---|---|---|
| Customer portal (own records) | R/W | — | — | — | R/W | — |
| All equipment records | — | R/W | R | R/W | R/W | R |
| Appraisal submission | — | — | R/W | R | R/W | R |
| Lead routing config | — | — | — | — | R/W | — |
| Manager approval | — | — | — | R/W | R/W | — |
| Admin panel | — | — | — | — | R/W | — |
| Reports | — | — | — | R | R/W | R/W |
| User management | — | — | — | — | R/W | — |
| Record lock override | — | — | — | R/W | R/W | — |

- Attempting to access a resource outside your role returns 403 with a human-readable message
- All permission-denied events written to `audit_logs`

---

### Feature 1.4.2 — Admin User Management

**User Story:**
As an Admin, I want to invite, edit, and deactivate platform users so that I can manage who has access to the system.

**Acceptance Criteria:**
- `POST /api/v1/admin/users/invite` sends an invitation email with a one-time sign-up link (48-hour expiry); Admin specifies the role at invite time
- `GET /api/v1/admin/users` returns paginated user list with: name, email, role, status, last_login, created_at
- `PATCH /api/v1/admin/users/:id` allows Admin to update role, status (`active | suspended`), and notification preferences
- `DELETE /api/v1/admin/users/:id` soft-deletes the user and invalidates all their active sessions
- Admin cannot delete or downgrade their own account via the API (must be done by another Admin)
- All user management actions written to `audit_logs` with before/after state

---

## Epic 1.6 — Security Middleware & Hardening

Full detail in `11_security_baseline.md` §3. Summary of what must ship in Phase 1:

### Feature 1.6.1 — Input Sanitization

**Acceptance Criteria:**
- All free-text fields on user-submitted models (`AppraisalSubmission.notes`, `ChangeRequest.customer_notes`, `Customer.*_notes`, `PublicListing.description`, `Inquiry.message`, `AppraisalPhoto.notes`) pass through a sanitization layer using `bleach` on write
- Sanitization strips all HTML tags; preserves plain text and newlines
- Frontend renders user-submitted text via React's default text escaping; no `dangerouslySetInnerHTML` on user content anywhere
- Markdown is explicitly NOT parsed for user-submitted fields
- Integration test: submit `<script>`, `<img onerror=...>`, and `javascript:` URLs in every user-editable field; render back and confirm sanitized

### Feature 1.6.2 — Security Response Headers

**Acceptance Criteria:**
- FastAPI middleware sets HSTS, X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy, and a strict Content-Security-Policy on every response (header values in `11_security_baseline.md` §3)
- CSP violations report to Sentry via `report-uri`
- CORS middleware allowlists only known frontend origins (configured per env in `AppConfig` key `cors_allowed_origins`); no wildcard
- All security headers verified present in integration tests (GET `/api/v1/health` → assert headers)

### Feature 1.6.3 — Secrets Rotation Policy

**Acceptance Criteria:**
- All application secrets stored in `fly secrets` per app — never committed to git, never written to local `.env` files outside developer laptops
- Inventory of every secret name, its owning integration, and rotation cadence captured in `project_notes/secrets-rotation.md` (per `11_security_baseline.md` §4 and `10_operations_runbook.md` §9.4 schedule)
- Per-app Fly deploy tokens (`flyctl tokens create deploy --app temple-{api,web}-{dev,staging,prod}`) rotated every 90 days; old tokens revoked with `flyctl tokens revoke`
- Monthly scheduled task emails Jim the secrets due to rotate within 60 days (see `10_operations_runbook.md` §8.3 pattern)
- GitHub Actions consumes Fly deploy tokens via `secrets.FLY_API_TOKEN_*` — no long-lived service account keys committed anywhere
- **GCP target equivalent:** secrets move to Secret Manager with `rotation_due` labels; GitHub → GCP uses Workload Identity Federation (no JSON keys). Documented in `12_gcp_production_target.md`.

---

## Epic 1.5 — Audit Logging

### Feature 1.5.1 — Immutable Audit Log

**User Story:**
As an Admin, I want every state change and sensitive action in the system to be recorded with who did it and when so that I can investigate issues and demonstrate compliance.

**Acceptance Criteria:**
- `audit_logs` table: `id`, `event_type`, `actor_id`, `actor_role`, `target_type`, `target_id`, `before_state JSONB`, `after_state JSONB`, `ip_address`, `user_agent`, `created_at`
- Audit entries are append-only — no UPDATE or DELETE on this table (enforced by DB-level trigger)
- Events logged: user registration, login, logout, 2FA changes, role changes, record status transitions, record lock acquire/release/override, manager approvals, eSign events, Admin config changes
- `GET /api/v1/admin/audit-logs` returns paginated, filterable log (by event_type, actor_id, target_id, date range)
- Audit log endpoint restricted to `admin` role only

---

## Phase 1 Completion Checklist

**Platform Infrastructure (Fly.io POC):**
- [ ] Fly.io org `temple-he` created with 2FA required for all members; six apps (`temple-{api,web}-{dev,staging,prod}`) provisioned per `10_operations_runbook.md` §2.3
- [ ] Neon Postgres project created with three branches (`dev`, `staging`, `prod`); Pro plan active for prod PITR per `10_operations_runbook.md` §2.4
- [ ] Cloudflare R2 buckets (`temple-he-photos`, `temple-he-reports`, `temple-he-backups`) created with object versioning enabled per `10_operations_runbook.md` §2.5
- [ ] Cloudflare zone active on production domain with Managed WAF, edge rate limiting, SSL/TLS Full (Strict), HSTS preload per `10_operations_runbook.md` §2.6
- [ ] `fly.toml` committed for every app defining concurrency limits, health checks, graceful shutdown (§10.1 values)
- [ ] Cloudflare Terraform config committed under `infra/cloudflare/` and applied to the prod zone; `terraform plan` green
- [ ] Fly.io Production Hardening Checklist (`10_operations_runbook.md` §10) walked end-to-end; every box green
- [ ] Daily off-site `pg_dump` backup Fly Machine running and verified on staging per `10_operations_runbook.md` §6.2
- [ ] GCP target architecture documented in `12_gcp_production_target.md` (no provisioning required yet)

**CI/CD:**
- [ ] GitHub Actions deploy pipeline green end-to-end: push to `develop` → `flyctl deploy --app temple-api-dev`; merge to `main` → staging; `v0.0.1` tag → prod with manual approval
- [ ] Per-app Fly deploy tokens created (`flyctl tokens create deploy --app ...`) and stored in GitHub secrets; local token files destroyed
- [ ] Security scan workflow green on first PR (Dependabot, Trivy, gitleaks, pip-audit)
- [ ] Dependabot enabled for pip, npm, swift, docker, github-actions ecosystems
- [ ] Secret scanning + push protection enabled in repo settings
- [ ] Branch protection on `main` and `develop` requires CI green + PR review
- [ ] Maintenance mode middleware works: `flyctl secrets set MAINTENANCE_MODE=true` returns friendly 503; `/health` still responds
- [ ] Rollback tested: deploy a bad revision to staging, run `flyctl releases rollback --yes`, verify previous revision serves traffic per `10_operations_runbook.md` §5.1
- [ ] Blue-green deploy tested on staging: new Machine health-checks green, traffic swaps, old Machine drains

**Local dev:**
- [ ] `make dev` brings up the full stack on a fresh laptop in < 10 minutes (Postgres + Mailpit only; no Redis)
- [ ] `README.md` quickstart walks a new developer through local setup
- [ ] Optional: `make dev-pr` spawns an ephemeral Neon branch for integration testing

**Auth:**
- [ ] `POST /api/v1/auth/register` → verification email sent (routed to Mailpit in dev/staging) → `GET /api/v1/auth/verify-email` → login succeeds
- [ ] Password reset flow: request → email delivered → reset link → new password set → old sessions invalidated
- [ ] Email change flow: current password re-verified, new address verification required, both addresses notified
- [ ] Google SSO login creates user and returns valid session tokens
- [ ] 2FA setup, confirm, verify, and recovery-code flows work end-to-end
- [ ] Account lockout: 5 failed logins → locked → auto-released after 30 min; password reset also releases
- [ ] Rate limiting on auth endpoints returns 429 with `Retry-After` as specified in `11_security_baseline.md` §2
- [ ] New-device login notification email delivered when logging in from a new UA + IP ASN

**RBAC:**
- [ ] `customer` token cannot reach `/api/v1/admin/*` endpoints (403)
- [ ] Admin can invite a new user, who receives email, registers, and logs in

**Security middleware:**
- [ ] All security response headers present on API (`curl -I https://api.temple-staging.com/api/v1/health` verifies)
- [ ] CSP violations reported to Sentry (tested by a violation triggered in staging)
- [ ] Input sanitization test: `<script>` submitted in every free-text field renders as text
- [ ] CORS allowlist enforces: request with disallowed origin is blocked

**Observability:**
- [ ] Sentry receiving errors from all three environments with correct `SENTRY_ENVIRONMENT` tag and release SHA
- [ ] BetterStack alert policies configured; triggering a synthetic 5xx log line on staging produces an email/SMS alert within 5 minutes per `10_operations_runbook.md` §7.3
- [ ] UptimeRobot monitors active against `https://api.templehe.com/api/v1/health` (prod) and staging equivalent from multiple global regions, 1-minute interval, alert to email + SMS
- [ ] Fly built-in metrics dashboard bookmarked per app; Fly spend alert set at $20/month in `fly billing`
- [ ] Neon project spend alert set at $25/month; Twilio spend alert at $15/month per `10_operations_runbook.md` §8.1

**Audit logging:**
- [ ] All auth actions (register, login, 2FA events, password reset, email change, lockout, lockout release) produce `audit_log` entries with correct before/after state
- [ ] Audit log append-only trigger verified (UPDATE and DELETE return an error)

**Hygiene:**
- [ ] No secrets in source code, logs, or CI output — gitleaks scan green
- [ ] `project_notes/secrets-rotation.md` drafted with rotation procedure for each integration secret
- [ ] `project_notes/decisions.md` initialized with architecture decisions made during Phase 1
