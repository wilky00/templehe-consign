# Temple Heavy Equipment — Consignment Platform
## Project CLAUDE.md — Claude Code Session Orientation

---

## Session Startup Checklist

Run this every session, in order:

1. Read `dev_plan/00_overview.md` — architecture reference, stack summary, phase map
2. Read `project_notes/decisions.md` — ADR log; authoritative for all "why" questions
3. Read `project_notes/progress.md` — what's done, what's in flight
4. Read `project_notes/known-issues.md` — open bugs and blockers
5. Read the phase file for the current task (e.g., `dev_plan/01_phase1_infrastructure_auth.md`)
6. State your understanding of the current task before writing any code

If `project_notes/progress.md` is empty, ask Jim what phase we're on before proceeding.

---

## Project Summary

Temple Heavy Equipment (TempleHE) is a ~15-person heavy equipment appraisal and consignment business. This platform replaces manual workflows with:

- Customer-facing web portal (equipment intake, status tracking)
- Internal CRM (sales reps, lead routing, scheduling)
- Native iOS app for field appraisers (iPad/iPhone, offline-capable)
- Admin panel (config, routing rules, user management, dynamic category CRUD)
- Public consignment listing page (standalone; no integration with existing TempleHE website)

Supported remotely by a single operator (Jim) on an 8–24 hour SLA. Every architectural choice is right-sized to a small team: cheap, automatable, and recoverable by one person.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12+, FastAPI, Pydantic v2, asyncio |
| Frontend | React 18, TypeScript (strict), React Query, Zustand, Tailwind CSS |
| iOS | Swift 5.9+, SwiftUI, Core Data (offline), iOS 16+ |
| Database | PostgreSQL 15 — Neon (POC) → Cloud SQL (GCP target) |
| Cache/Locks | Postgres advisory locks + `record_locks` table (POC) → Redis Memorystore (GCP) |
| Compute | Fly Machines (POC) → Cloud Run (GCP) |
| Object Storage | Cloudflare R2 (POC) → Cloud Storage (GCP) |
| Async Jobs | Postgres `jobs` table + Fly scheduled machines (POC) → Pub/Sub + Cloud Run Jobs (GCP) |
| Edge | Cloudflare WAF, CDN, Full (Strict) TLS, HSTS preload |
| Secrets | `fly secrets` per app (POC) → Secret Manager + Workload Identity Federation (GCP) |

The app code does not change between POC and GCP. Only the infrastructure layer swaps. See `dev_plan/12_gcp_production_target.md` and `dev_plan/13_hosting_migration_plan.md`.

---

## Stack Standards — Where to Find Them

These files live in `~/.claude/docs/` on Jim's machine (global config, not checked into this repo). Read the relevant file before working in that area.

| File | Covers |
|---|---|
| `~/.claude/docs/python.md` | uv, type hints, pytest, ruff, FastAPI, Pydantic, asyncio |
| `~/.claude/docs/api-design.md` | REST conventions, status codes, schema design, versioning, error handling |
| `~/.claude/docs/react.md` | Functional components, hooks, state, data fetching, accessibility |
| `~/.claude/docs/typescript.md` | Strict typing, tsconfig, Zod validation, async, error handling |
| `~/.claude/docs/design-system.md` | Design tokens, theming, dark mode, spacing, typography, component patterns |
| `~/.claude/docs/database.md` | PostgreSQL, schema design, migrations, connection pooling, ORM patterns |
| `~/.claude/docs/docker.md` | Compose structure, secrets, networking, validation |
| `~/.claude/docs/gcp.md` | Cloud Run, IAM, Secret Manager, Cloud SQL, Pub/Sub |
| `~/.claude/docs/security.md` | Secrets, input validation, logging, network safety, review checklist |
| `~/.claude/docs/testing.md` | Test pyramid, mocking, CI gates, coverage, performance |
| `~/.claude/docs/git.md` | Commit messages, branch naming, pull requests, rebase workflow |
| `~/.claude/docs/shell.md` | Bash scripting, safety, style, shellcheck |
| `~/.claude/docs/observability.md` | Structured logging, metrics, alerting, health checks, tracing |
| `~/.claude/docs/macos.md` | Apple Silicon, Homebrew, zsh, BSD CLI differences |

---

## Development Phases

| Phase | File | Status |
|---|---|---|
| 1 | `dev_plan/01_phase1_infrastructure_auth.md` | Not started |
| 2 | `dev_plan/02_phase2_customer_portal.md` | Not started |
| 3 | `dev_plan/03_phase3_sales_crm.md` | Not started |
| 4 | `dev_plan/04_phase4_admin_panel.md` | Not started |
| 5 | `dev_plan/05_phase5_ios_app.md` | Not started |
| 6 | `dev_plan/06_phase6_approval_esign.md` | Not started |
| 7 | `dev_plan/07_phase7_pdf_reports.md` | Not started |
| 8 | `dev_plan/08_phase8_analytics_listing.md` | Not started |

Update this table as phases are completed. "In progress" is a valid status.

---

## Repo Structure

```
templehe-consign/
├── api/            # FastAPI backend
├── web/            # React/TypeScript frontend
├── ios/            # SwiftUI iOS app
├── infra/          # Fly.io configs, Terraform (future GCP)
├── scripts/        # Dev, deploy, and migration scripts
├── dev_plan/       # Phase-by-phase dev plan (read-only reference)
├── project_notes/  # Session memory: decisions, progress, known issues
├── docs/           # Project-level docs (ADRs, runbooks, etc.)
└── CLAUDE.md       # This file
```

---

## Key Engineering Rules (Project-Specific)

These are in addition to the global rules in `~/.claude/CLAUDE.md`.

- **No secrets in code or git.** All credentials via `fly secrets` (POC) or Secret Manager (GCP). `.env` files are gitignored; `.env.example` is the template.
- **Scope guard:** Any task touching more than 3 files requires Jim's confirmation before proceeding.
- **Migrations are append-only.** Never modify an existing migration file. Write a new one.
- **Service interfaces are stable.** `RecordLockService`, `NotificationService`, `SigningService`, `ValuationService` — don't change their public APIs. They're designed to swap implementations at migration time.
- **The iOS config endpoint is the source of truth** for dynamic categories, inspection prompts, and red flag rules on device. Do not hardcode these in the iOS app.
- **A2P 10DLC** must be registered before any SMS goes out. See `dev_plan/11_security_baseline.md §5`.
- **Phase gates:** A phase is not complete until its E2E test suite passes in CI against staging. See `dev_plan/09_testing_strategy.md`.
- **Twilio A2P and SendGrid DNS records** need TempleHE domain admin action. Flag and track in `project_notes/known-issues.md` if blocked.

---

## Personas & Role Slugs

| Persona | Slug | Description |
|---|---|---|
| Customer | `customer` | Equipment owner submitting for appraisal/consignment |
| Sales Rep | `sales` | Owns customer relationships, publishes listings |
| Appraiser | `appraiser` | Field tech using iOS app |
| Sales Manager | `sales_manager` | Approves valuations and price changes |
| Admin | `admin` | Full access — config, routing rules, user management |
| Reporting User | `reporting` | Read-only analytics and reports |

---

## Sub-Agents

### researcher

Defined at `.claude/agents/researcher.md`. Runs on Haiku (fast, cheap). Read-only — cannot write or modify files.

**Always delegate to `researcher` when the task is:**
- Reading and summarizing dev_plan/ files before starting a phase
- Finding where a symbol, pattern, or field name appears in the codebase
- Checking what already exists before adding something new
- Understanding the structure of a directory or module
- Looking up library or API documentation on the web
- Answering "does X exist?" or "how is Y currently implemented?"
- Session startup artifact review (reading CLAUDE.md, decisions.md, progress.md, known-issues.md)

**Do NOT use `researcher` for:**
- Writing or editing any file
- Running tests or executing shell commands
- Anything that requires judgment about what to build next

**How to invoke:** just ask the question and Claude will route it. You can also be explicit: "use the researcher agent to find all usages of RecordLockService."

---

## Open Decisions (Pre-Build)

These need Jim's call before the relevant phase starts.

| Item | Needed By |
|---|---|
| eSign provider: DocuSign vs Dropbox Sign | Phase 6 |
| Paid valuation API: IronPlanet vs EquipmentWatch | Phase 5 |
| Public listing page URL / domain | Phase 8 |
| App Store review submission timing | Phase 5 completion |
| Twilio A2P 10DLC brand/campaign registration | Phase 1 completion (~2 week approval window) |
| SendGrid SPF/DKIM/DMARC DNS records | Phase 1 completion (needs TempleHE domain admin) |
