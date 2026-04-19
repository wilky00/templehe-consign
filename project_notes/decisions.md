# Architectural Decision Records (ADR Log)

This is the authoritative log of all significant architectural and product decisions made for the TempleHE consignment platform. Read this at the start of every session. When a decision changes, update the existing ADR — do not delete it; mark the old resolution as superseded and add the new one below it.

---

## ADR-001: Hosting Strategy — Fly.io POC + GCP Target

**Date:** 2025-04 (planning)
**Status:** Accepted
**Deciders:** Jim Wilen

### Context

The platform needs to launch quickly and cheaply for a ~15-person business. The operator (Jim) is a single remote engineer on an 8–24 hour SLA. The business may grow to a scale that justifies GCP, but that is not certain at launch.

### Decision

Run the POC and initial production on **Fly.io + Neon Postgres + Cloudflare R2 + Cloudflare WAF/CDN** targeting $0–30/month. Architecture the app so it can migrate to **GCP (Cloud Run + Cloud SQL + Memorystore + Cloud Storage + Pub/Sub)** without changing application code.

**POC stack:**
- Compute: Fly Machines (six apps: `temple-{api,web}-{dev,staging,prod}`)
- Database: Neon Postgres (one project, three branches: `dev`, `staging`, `prod`; PITR on prod)
- Object Storage: Cloudflare R2 (versioning enabled)
- Async Jobs: Postgres `jobs` table drained by scheduled Fly Machines
- Secrets: `fly secrets` per app
- Edge: Cloudflare WAF (Managed ruleset), CDN, Full (Strict) TLS, HSTS preload

**GCP target stack (post-migration):**
- Compute: Cloud Run (three GCP projects: `temple-dev`, `temple-staging`, `temple-prod`)
- Database: Cloud SQL Postgres 15, private IP, PITR
- Object Storage: Cloud Storage (versioning + lifecycle policies)
- Async Jobs: Pub/Sub + Cloud Run Jobs
- Secrets: Secret Manager + Workload Identity Federation (no static keys)

### Migration Trigger

Migrate when **any two** of the following are true: (a) monthly Fly.io cost exceeds $200, (b) team exceeds 5 engineers, (c) an enterprise customer requires SOC 2 or VPC isolation, (d) Neon Postgres PITR proves insufficient for business continuity needs.

### Consequences

- All service interfaces (`RecordLockService`, `NotificationService`, `SigningService`, `ValuationService`) must be stable — only the implementation behind the interface swaps at migration time.
- `RecordLockService` POC: Postgres advisory locks + `record_locks` visibility table. Target: Redis key with identical TTL/heartbeat semantics.
- `NotificationService` POC: `notification_jobs` Postgres table + scheduled Fly Machine. Target: Pub/Sub topic + Cloud Run Job consumer.
- See `dev_plan/12_gcp_production_target.md` for target architecture and `dev_plan/13_hosting_migration_plan.md` for the cutover runbook.

---

## ADR-002: Database Strategy — Single PostgreSQL Wire Protocol, No Redis in POC

**Date:** 2025-04 (planning)
**Status:** Accepted
**Deciders:** Jim Wilen

### Context

Redis adds operational overhead and cost. The POC scale does not justify it. Concurrency and job queuing needs to be solved cheaply and without another service to manage.

### Decision

Use **Postgres advisory locks** + a `record_locks` table for pessimistic concurrency in the POC. Use a **Postgres `jobs` table** drained by a scheduled Fly Machine for async job queuing in the POC. No Redis until GCP migration.

### Consequences

- The `RecordLockService` interface abstracts all locking behavior. The POC implementation uses `pg_try_advisory_lock` + the `record_locks` table. The GCP implementation uses Redis.
- Lock TTL: 15 minutes, enforced by a heartbeat sweeper. Clients send a heartbeat every 60 seconds.
- Admin and Sales Manager roles can break any lock manually. All lock events are written to AuditLog.
- Migrations are append-only. Never modify existing migration files.

---

## ADR-003: Dynamic Equipment Categories — Database-Driven, Not Code-Driven

**Date:** 2025-04 (planning)
**Status:** Accepted
**Deciders:** Jim Wilen

### Context

Temple can add new equipment types (forklifts, aerial work platforms, cranes) at any time. Hardcoding categories would require a code deploy for every new type. The Admin Panel should give business users full control without engineering involvement.

### Decision

Equipment categories and all their sub-entities (components, inspection prompts, photo slots, attachment options, red flag rules) are stored in normalized Postgres tables. Admin Panel has full CRUD. No code deployment required to add, edit, or remove a category or any of its attributes.

**Default seed categories (15 types — see `dev_plan/00_overview.md §5`)** are loaded at schema init and are the starting point, not a fixed list.

### Consequences

- The iOS config endpoint assembles and returns the full category tree. The iOS app never hardcodes categories, prompts, or scoring weights.
- Component weights auto-normalize if they don't sum to 100%.
- Categories can be exported/imported as JSON for environment promotion (dev → staging → prod).
- The `equipment_categories` table is the source of truth, not `AppConfig`.

---

## ADR-004: Authentication — Google SSO Only (No Username/Password)

**Date:** 2025-04 (planning)
**Status:** Accepted
**Deciders:** Jim Wilen

### Context

TempleHE staff already use Google Workspace. Adding a separate username/password system would create credential management overhead with no benefit.

### Decision

Use **Google OAuth2 / SSO** for all authentication. No username/password login. Customers use Google SSO for the portal. Internal users (Sales, Appraiser, Manager, Admin) use Google SSO scoped to the TempleHE Google Workspace domain.

### Consequences

- Google client ID/secret stored in `fly secrets` (POC) or Secret Manager (GCP). Never in code.
- RBAC enforced server-side by role slug on every request. JWT or session token issued after Google OAuth callback.
- See `dev_plan/01_phase1_infrastructure_auth.md` for the full auth implementation spec.

---

## ADR-005: eSign Provider — Deferred, Interface Stubbed

**Date:** 2025-04 (planning)
**Status:** Deferred — decision needed before Phase 6
**Deciders:** TBD

### Context

Consignment contracts require legally binding e-signatures. Two leading options: DocuSign and Dropbox Sign. Neither has been evaluated for price or API fit at this scale.

### Decision

Stub a `SigningService` interface in Phase 1. Implement the real provider in Phase 6. Decision on provider deferred until Phase 6 starts.

### Candidates

- **DocuSign** — industry standard, higher cost, strong compliance features
- **Dropbox Sign** — lighter, lower cost, good API

---

## ADR-006: Valuation Data — Internal DB + Scraper First, Paid API Later

**Date:** 2025-04 (planning)
**Status:** Accepted
**Deciders:** Jim Wilen

### Context

Paid valuation APIs (IronPlanet, EquipmentWatch) are expensive. The platform can build a competitive dataset by scraping public auction results and combining with its own appraisal history.

### Decision

Build an internal equipment valuation database populated by a Playwright/AI scraper in Phase 5. Stub a `ValuationService` interface. Add the paid API integration behind the same interface later if the internal data proves insufficient.

### Consequences

- `ValuationService` interface is stable. Implementation swaps without touching callers.
- Playwright scraper is an internal service. Legal review of target sites before scraping.

---

## ADR-007: Public Listing Page — Standalone, No Integration with TempleHE Website

**Date:** 2025-04 (planning)
**Status:** Accepted
**Deciders:** Jim Wilen

### Context

TempleHE has an existing website. Integrating with it adds coordination overhead and timeline risk.

### Decision

The public consignment listing page is a **standalone page within this platform** — its own route, its own design. No API integration with the existing TempleHE website at launch. URL/domain decision deferred to Phase 8.

---

## ADR-008: iOS Distribution — TestFlight First, App Store Post-Launch

**Date:** 2025-04 (planning)
**Status:** Accepted
**Deciders:** Jim Wilen

### Context

App Store review adds unpredictable delay. TestFlight can distribute to internal testers immediately.

### Decision

Distribute via TestFlight for internal use during Phase 5. Submit to the App Store during Phase 5 completion to avoid holding up launch. App Store approval is a Phase 5 exit condition.

### Consequences

- Submit early. Apple review averages 1–3 days but can spike. Don't wait until the last day of Phase 5.
- Min-version kill switch built into Phase 5 — Admin Panel can force an app update.
