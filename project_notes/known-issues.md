# Known Issues & Blockers

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

## OPEN — Fly.io first deploy
**Status:** Apps created, secrets staged, pending first `flyctl deploy`
**Impact:** Staging is not yet live; E2E phase gate cannot run until this fires
**Action:** Merge PR #17 — CI will trigger `flyctl deploy` on staging automatically, which activates the staged secrets. No manual step needed.

## OPEN — Neon PITR on prod branch
**Status:** Neon project + 3 branches (dev/staging/prod) created; PITR not yet enabled
**Impact:** Prod branch has no point-in-time recovery — do not allow real customer data onto prod until resolved
**Action (two options):**
1. Upgrade Neon to Pro/Scale (~$19/mo) before Phase 2 go-live — enables PITR on the prod branch
2. Accelerate GCP migration — Cloud SQL has PITR on by default at no extra cost; Neon can be cancelled
**Not an immediate blocker** — only matters before real customer data lands on prod. POC dev/staging usage on free tier is fine.

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
