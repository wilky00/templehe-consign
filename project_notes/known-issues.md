# Known Issues & Blockers

## BLOCKING — Twilio A2P 10DLC Registration
**Status:** Action required immediately (Jim)
**Impact:** SMS notifications will not work until carrier approval (~2–4 weeks)
**Action:** Register TempleHE brand + campaign at twilio.com/console/sms/a2p-10dlc
- Required info: business EIN, legal name, website, use case description, sample messages
- Do this on Day 1 of Phase 1 — approval window is outside our control

## BLOCKING — SendGrid DNS Records (SPF / DKIM / DMARC)
**Status:** Awaiting TempleHE domain admin action
**Impact:** Transactional email (verification, reset, notifications) will only work via Mailpit locally until DNS is set
**Action:**
1. Log in to SendGrid → Settings → Sender Authentication
2. Add SPF: `v=spf1 include:sendgrid.net ~all`
3. Add two DKIM CNAME records (from SendGrid dashboard)
4. Add DMARC: `v=DMARC1; p=none; rua=mailto:dmarc@templehe.com` (start at p=none for 2 weeks, then quarantine, then reject)
5. Validate at mail-tester.com

## OPEN — Google OAuth workspace domain
**Status:** Not yet configured
**Impact:** Google SSO (Phase 1 stub, not yet implemented) will need the `hd` (hosted domain) claim value
**Action:** Provide the Google Workspace domain (e.g. `templehe.com`) before SSO implementation

## OPEN — Fly.io provisioning
**Status:** Not yet done
**Impact:** Staging/prod deploys blocked until apps exist
**Action:** See `docs/fly-provisioning.md` for the step-by-step guide — Jim runs these manually

## OPEN — Neon Postgres provisioning
**Status:** Not yet done
**Impact:** Staging/prod DB blocked
**Action:** Create Neon project, three branches (dev/staging/prod), enable PITR on prod branch — see `docs/fly-provisioning.md`

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

## OPEN — Category components / prompts / scoring rules
**Status:** Placeholder data only
**Impact:** Scoring engine (Phase 6) will need real component weights and red flag rules per category
**Action:** Populate `category_components`, `category_inspection_prompts`, and `category_red_flag_rules` tables with business data from internal checklists before Phase 5/6. This is an Admin Panel (Phase 4) task.
