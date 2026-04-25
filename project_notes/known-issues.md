# Known Issues & Blockers

## FIXED — Pre-existing lint debt across Phase 3 Sprint 1–4 commits
**Fixed:** 2026-04-25 — small cleanup commit on `phase3-sales-crm` after Sprint 5 surfaced the breakage. Wrapped 14 long ABOUTME / docstring lines, removed 5 unused imports (sales_service.py, test_calendar.py), sorted 3 unsorted import blocks, added a missing trailing newline (calendar_service.py), and converted one `timezone.utc` → `datetime.UTC` (UP017). Plus a `ruff format` pass on 20 files that had drifted.
**Was:** `cd api && uv run ruff check .` failed with 33 errors across services, schemas, routers, and tests — mostly long ABOUTME comments from earlier sprints, plus auto-fixable cleanup. CI must have been bypassed or failed-but-merged at the time the offending commits landed.
**Confirmation:** `make lint` clean; full backend test suite still 307/307.

## PENDING CONFIRMATION — Twilio A2P 10DLC Registration
**Status:** Registration submitted, appears approved — awaiting Jim's confirmation (2026-04-21)
**Impact:** SMS notifications come online once the brand + campaign show "Approved" in the Twilio console
**Action:** Jim — check twilio.com/console/sms/a2p-10dlc and update this entry to FIXED once the approval is confirmed

## FIXED — SendGrid DNS Records (SPF / DKIM / DMARC)
**Fixed:** 2026-04-21 — DNS records added for `saltrun.net` (Jim confirmed)
**Was:** SPF / two DKIM CNAMEs / DMARC (p=none) were missing; transactional email via SendGrid would only reach recipients whose providers didn't enforce DMARC
**Fix:** Records added via saltrun.net DNS admin. Run mail-tester.com once before Phase 2 go-live to verify the full SPF + DKIM + DMARC chain. DMARC policy is `p=none` per the soft-launch plan — tighten to `quarantine` 2 weeks post-launch, then `reject`.

## OPEN — Google OAuth workspace domain
**Status:** Not yet configured
**Impact:** Google SSO (Phase 1 stub, not yet implemented) will need the `hd` (hosted domain) claim value
**Action:** Provide the Google Workspace domain (e.g. `templehe.com`) before SSO implementation

## FIXED — Fly.io first deploy (staging)
**Fixed:** 2026-04-24 — first `flyctl deploy` to staging fired automatically on the PR #28 merge-to-main push and succeeded. Staged secrets activated on both `temple-api-staging` and `temple-web-staging`.
**Remaining:** Production deploy is gated behind manual `workflow_dispatch` — fires when the prod-go-live bundle below is complete.

## FIXED — Change request duplicate submission (Phase 3 Sprint 1)
**Fixed:** 2026-04-24 — commit `feb18d1` on `phase3-sales-crm`. Migration 009 added partial UNIQUE index `ux_change_requests_one_pending_per_record` on `(equipment_record_id) WHERE status='pending'`. `change_request_service.submit_change_request` catches the resulting `IntegrityError` and maps to 409 with human-readable detail. Two new integration tests verify the 409 path and that a new request is accepted after the prior one is resolved.
**Was:** `ChangeRequestService.submit_change_request` let a customer file unlimited pending requests on the same record; Phase 2 Feature 2.4.1 required one-at-a-time enforcement.
**Enforcement point:** DB-level partial unique index — impossible to violate from any callsite (direct SQL, seed script, future sales endpoint).

## OPEN — SMS warning copy not present on registration / profile UI
**Status:** Account page has an SMS opt-in checkbox with description "Text message updates (requires a cell number on your profile)". The Phase 2 spec (Feature 2.1.1) calls for visible inline text: *"Standard SMS messaging rates may apply based on your carrier plan."* No such copy is rendered anywhere in the web app today.
**Impact:** Regulatory — A2P 10DLC + CAN-SPAM best practice mandates that consent capture include rate/fee language. Not a blocker until SMS actually dispatches (today `twilio_messaging_service_sid` is empty → SMS is skipped with an audit entry).
**Action:** Add the inline warning under the SMS opt-in checkbox in `web/src/pages/Account.tsx` and on the register page whenever SMS preferences are surfaced. Bundle with the A2P go-live gate below.
**Location:** `web/src/pages/Account.tsx:105-110`.

## OPEN — httpx per-request cookies DeprecationWarning in test suite
**Status:** `test_auth_flows.py::test_refresh_cookie_full_cycle` + `test_email_change_revokes_sessions` trigger `DeprecationWarning: Setting per-request cookies=<...> is being deprecated`. Tests still pass; warning is from httpx (ASGI test client).
**Impact:** None today; will break when httpx removes the API.
**Action:** Switch from `client.post(..., cookies={...})` to setting the cookie on the test client instance or using `client.cookies.set(...)` in the refresh-cookie tests.
**Location:** `api/tests/integration/test_auth_flows.py` (two callsites).

## OPEN — Neon PITR on prod branch
**Status:** Neon project + 3 branches (dev/staging/prod) created; PITR not yet enabled
**Impact:** Prod branch has no point-in-time recovery — do not allow real customer data onto prod until resolved
**Action (two options):**
1. Upgrade Neon to Pro/Scale (~$19/mo) before Phase 2 go-live — enables PITR on the prod branch
2. Accelerate GCP migration — Cloud SQL has PITR on by default at no extra cost; Neon can be cancelled
**Not an immediate blocker** — only matters before real customer data lands on prod. POC dev/staging usage on free tier is fine.

## OPEN — Neon `neondb_owner` password leaked in chat (2026-04-22)
**Status:** Credential exposed in a Claude Code conversation + local shell history; not rotated yet
**Impact:** Holder of the credential has read/write to one Neon branch. Dev/staging hold test data only; prod is not yet live with customer data.
**Action:** Rotate the `neondb_owner` password in the Neon console, update `fly secrets` on `temple-api-{dev,staging,prod}`, update `.env`. Bundle with the Neon Pro / PITR activation above — same gate: before real customer data lands on prod.
**Not an immediate blocker** — same risk profile as the PITR gap; both get resolved together in the "prod go-live readiness" checklist.

## OPEN — Fly app `temple-notifications` not yet created
**Status:** `infra/fly/temple-notifications.toml` committed (Phase 2 Sprint 2), but the Fly app itself hasn't been created.
**Impact:** Rows land in `notification_jobs` with status=`pending`, but nothing drains them. Intake confirmation emails (and Phase 2+ status emails / SMS) never leave the queue in staging/prod.
**Action (same prod-go-live gate as temple-sweeper):**
```
fly apps create temple-notifications --org <org-slug>
fly secrets set -a temple-notifications \
  DATABASE_URL="<prod pooler url>" \
  SENDGRID_API_KEY="..." \
  TWILIO_ACCOUNT_SID="..." TWILIO_AUTH_TOKEN="..." \
  TWILIO_MESSAGING_SERVICE_SID="..."   # leave empty until A2P 10DLC confirmed
fly machine run . --app temple-notifications \
  --config infra/fly/temple-notifications.toml --region iad
```
**Not an immediate blocker** — Sprint 2 integration tests exercise the worker in-process against the test DB; local `make dev` can run the worker manually. Provision alongside Neon Pro / temple-sweeper as one bundle.

## OPEN — Fly app `temple-sweeper` not yet created
**Status:** `infra/fly/temple-sweeper.toml` committed (WS13), but the Fly app itself hasn't been created — `fly secrets` / `fly deploy` fail with "Could not find App".
**Impact:** Hourly retention sweep (rate_limit_counters, webhook_events_seen, expired user_sessions) + monthly audit-log partition bootstrap don't run. Tables grow unbounded.
**Action (same Phase 2 go-live gate):**
```
fly apps create temple-sweeper --org <org-slug>
fly secrets set -a temple-sweeper DATABASE_URL="<prod pooler url>"
fly machine run . --app temple-sweeper \
  --config infra/fly/temple-sweeper.toml --schedule hourly --region iad
```
**Not an immediate blocker** — POC staging/dev traffic is a handful of rows/day from CI. Provision alongside Neon Pro upgrade + password rotation as one bundle.

## FIXED — `AnalyticsEvent.metadata` SQLAlchemy reserved name clash
**Fixed:** 2026-04-20 — `api/database/models.py:700`
**Was:** `metadata: Mapped[dict | None]` — conflicts with `DeclarativeBase.metadata`
**Fix:** Renamed to `event_metadata` with explicit column name `mapped_column("metadata", ...)`

## FIXED — `database/__init__.py` importing `Base` from wrong module
**Fixed:** 2026-04-20 — `api/database/__init__.py`
**Was:** `from database.base import Base, get_db` — `Base` lives in `database.models`, not `database.base`
**Fix:** Split into `from database.base import get_db` + `from database.models import Base`

## FIXED — `make dev` failing to load .env / DATABASE_URL not set
**Fixed:** 2026-04-20
**Was:** Makefile didn't load `.env`; alembic and config.py couldn't find required env vars
**Fix:** Inline DATABASE_URL default in alembic Makefile target; config.py resolves `.env` from repo root via `Path(__file__).parent.parent`; added `extra="ignore"` for Docker Compose-only vars (POSTGRES_PASSWORD)

## FIXED — seed.py asyncpg syntax error on JSONB cast
**Fixed:** 2026-04-20 — `scripts/seed.py`
**Was:** `:value::jsonb` — asyncpg rejects `::` cast mixed with named params
**Fix:** `CAST(:value AS jsonb)`

## FIXED — templehe_test database not created on make dev
**Fixed:** 2026-04-20 — `Makefile`
**Was:** Docker Compose only creates `templehe` DB; integration test fixture failed immediately
**Fix:** Added `CREATE DATABASE templehe_test` step to `make dev` after Postgres ready

## FIXED — set_updated_at trigger using NOW() instead of clock_timestamp()
**Fixed:** 2026-04-20 — `api/alembic/versions/002_fix_set_updated_at_trigger_to_use_clock_.py`
**Was:** `NOW()` returns transaction start time — INSERT + UPDATE in same transaction get identical timestamps, breaking the trigger test
**Fix:** Migration 002 replaces the function with `clock_timestamp()` (wall clock)

## FIXED — Refresh Token Not Returned to Client
**Fixed:** 2026-04-21 on branch `phase1-hardening` (commit eaf82d4, WS3)
**Was:** `auth_service.login()` generated a refresh token and stored its hash in `user_sessions`, but the router (`routers/auth.py:126`) returned only `access_token` and never set a cookie. `/refresh` and `/logout` read from a body field no client could populate.
**Fix:** Login, `/2fa/verify`, and `/2fa/recovery` now set the refresh token as an HttpOnly + SameSite=Strict cookie scoped to `/api/v1/auth`. `/refresh` and `/logout` read from the cookie; `/logout` clears it. Dead `LogoutRequest` / `RefreshRequest` schemas removed. Full HTTP cycle test added.

## DESIGN CONSTRAINT — R2 Does Not Support Object Versioning
**Status:** Permanent constraint — not a bug, not fixable
**Impact:** Any code that uploads to R2 must never overwrite an existing key
**Rule:** All R2 object keys must be immutable by design:
- Photos: `photos/{equipment_id}/{upload_uuid}.{ext}` — new UUID per upload
- Reports: `reports/{consignment_id}/{generated_at_unix}.pdf` — timestamp in key
- Backups: `backups/{date}/{timestamp}-backup.sql.gz` — date-partitioned
**Deletions:** Soft-delete in the DB only; never call R2 delete on a file that may be referenced
**Recovery:** Neon PITR is the primary DB recovery path. R2 backups are supplementary.
**Note:** ADR-001 previously said "versioning enabled" — that was incorrect and has been corrected.

## PENDING — Category components / prompts / photo slots / red flag rules
**Status:** Jim has the seed data ready (2026-04-21). Not yet imported — was missed during Phase 1 Sprint 1 seed.
**Impact:** Phase 2 intake form needs category-specific fields to render; Phase 6 scoring engine needs real component weights and red flag rules per category
**Action at Phase 2 `/phase-start`:**
1. Jim provides the seed CSV / JSON (per-category components with weights, inspection prompts, photo slots, red flag rules) for the default 15 categories.
2. Extend `scripts/seed.py` to import those tables idempotently, or ship a one-off Alembic data migration.
3. Keep the Admin Panel (Phase 4) as the long-term CRUD surface — this import is the bootstrap, not the ongoing management path.

## OPEN — Google Maps API key not provisioned (Phase 3 Sprint 4)
**Status:** Sprint 4 (2026-04-25) shipped the Distance Matrix + Geocoding integrations behind `settings.google_maps_api_key`. The setting is unset in dev / test / staging today.
**Impact:** Without a key, the calendar uses the AppConfig fallback (`drive_time_fallback_minutes = 60` — block any back-to-back appointment within 60 min) and metro-area routing rules silently no-op (the matcher falls through to the next geographic rule). Direct overlap conflicts still work — only the drive-time-buffer math and metro-area routing depend on the key.
**Action when Jim is ready to test live drive-time:**
1. Open Google Cloud Console → create or pick a project (POC is fine on the personal account).
2. **Billing** → enable billing on the project (Google requires a billing account even for free-tier). Set a low daily budget alert (~$1) before enabling APIs.
3. **APIs & Services** → enable both: *Distance Matrix API* and *Geocoding API*.
4. **Credentials** → Create credentials → API key. Restrict the key:
   - **Application restrictions:** None for now (server-side use only — no need for HTTP referrer or IP allowlist while we're calling from Fly's egress).
   - **API restrictions:** Limit the key to *Distance Matrix API* + *Geocoding API* only.
5. Set the key on the API: `fly secrets set GOOGLE_MAPS_API_KEY=AIza... -a temple-api-dev` (and `-staging` / `-prod` when ready).
6. Confirm by hitting `/api/v1/calendar/events` POST with two same-day appointments far apart and inspecting the conflict response — should now reflect real Google duration_in_traffic.

**Cost expectation (POC volume):** Distance Matrix is ~$5 per 1,000 element calls, Geocoding is ~$5 per 1,000. Google gives every account a $200/month free credit (~40k calls each). At our volume — ≤20 appraisal scheduling attempts/day + ≤20 intakes/day with metro-area rules — we're 3–4 orders of magnitude under the free credit. Cap the daily quota at 1,000 calls per API in Cloud Console as belt-and-suspenders.

**Service contract preserved across the swap:** `services/google_maps_service.py` is the only call site for both APIs; cache reads (Postgres `drive_time_cache` + `geocode_cache`) gate every API call. GCP migration swaps the cache to Redis SETEX without touching the public surface.
