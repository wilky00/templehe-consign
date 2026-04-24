# Temple Heavy Equipment — Appraisal & Consignment Platform
## Project Overview & Architecture Reference

> **Reading order for Claude Code:** Read this file first in every session, then `project_notes/decisions.md` (ADR log — authoritative for "why the architecture looks the way it does"), then `10_operations_runbook.md` and `11_security_baseline.md` for operational and security baseline, then the phase file for the feature you are building. Cross-reference `01_checklists/`, `02_schema_and_dictionary/`, and `03_implementation_package/` in the master bundle for field-level detail. When a POC vs target question comes up, `ADR-001` is the source of truth.
>
> **Supporter profile:** This platform is built for a SMB (10–20 employees) with no in-house IT. It is supported remotely by a single operator (Jim) on an 8–24 hour SLA. Every architectural and operational choice is right-sized to that reality — cheap, automatable, and recoverable by one person.
>
> **Hosting posture (per `ADR-001`):** The POC and MVP launch run on **Fly.io + Neon Postgres + Cloudflare R2 + Cloudflare WAF/CDN** (target: $0–30/month at small production scale, secure per §11). The platform is architected to migrate to **GCP (Cloud Run + Cloud SQL + Memorystore + Cloud Storage + Pub/Sub)** without application-code change once the migration trigger is met. See `12_gcp_production_target.md` for the target architecture and `13_hosting_migration_plan.md` for the cutover runbook.

---

## 1. Project Summary

Temple Heavy Equipment (TempleHE) operates a heavy equipment appraisal and consignment business. This platform replaces manual workflows with a fully integrated system covering:

- A **customer-facing web portal** for equipment intake and status tracking
- An **internal CRM** for sales reps, appraisers, and managers
- A **native iOS app** for field appraisers (iPad/iPhone)
- An **admin panel** for configuration, routing rules, and reporting
- A **public-facing consignment listing page** that stands as its own independent page within this platform (separate from the existing TempleHE website — no integration between the two at this time)

---

## 2. Tech Stack

### Backend API
- **Runtime:** Python 3.12+
- **Framework:** FastAPI with Pydantic v2 for request/response validation
- **Async:** asyncio throughout; no sync DB calls in request path
- **Standards:** See `.claude/docs/python.md` and `.claude/docs/api-design.md`

### Frontend Web (Portal + Admin + Sales + Manager)
- **Framework:** React 18 with TypeScript (strict mode)
- **State:** React Query for server state, Zustand for local UI state
- **Styling:** Tailwind CSS with a shared design token file
- **Standards:** See `.claude/docs/react.md`, `.claude/docs/typescript.md`, `.claude/docs/design-system.md`

### iOS App (Appraiser)
- **Language:** Swift 5.9+
- **UI Framework:** SwiftUI
- **Target:** iOS 16+ (iPhone and iPad)
- **Distribution:** TestFlight (internal) + App Store (public, post-launch)
- **Offline:** Core Data for local cache; background sync via URLSession background tasks

### Database
- **Primary:** PostgreSQL 16 — Neon (POC) → Cloud SQL (target). Same wire protocol; same SQL.
- **Cache / Lock Store:** Postgres advisory locks + a `record_locks` row for visibility (POC, no Redis) → Memorystore Redis (target). The `RecordLockService` interface is identical across both.
- **Standards:** See `.claude/docs/database.md`

### Cloud Infrastructure
**POC (today):**
- **Compute:** Fly Machines — six apps (`temple-{api,web}-{dev,staging,prod}`); scale-to-zero on dev/staging
- **Database:** Neon Postgres — one project with three branches (`dev`, `staging`, `prod`); PITR on prod
- **Object Storage:** Cloudflare R2 buckets with object versioning enabled. Phase 1 provisions `temple-he-photos`, `temple-he-reports`, `temple-he-backups`. Phase 2 adds `temple-he-legal` (ToS/privacy archive per `11_security_baseline.md` §6); the retention enforcer (`11_security_baseline.md` §7) provisions `temple-he-audit-archive` when it ships.
- **Async Jobs:** Postgres `jobs` table drained by scheduled Fly Machines; nightly `pg_dump` → R2 via dedicated Fly Machine
- **Edge:** Cloudflare Free — WAF (Managed ruleset), CDN, DDoS, edge rate limiting on `/api/*`, Full (Strict) TLS, HSTS preload
- **Secrets:** `fly secrets` per app; deploy tokens scoped per app, rotated quarterly
- **Standards:** See `10_operations_runbook.md` for Fly-native ops

**Target (post-migration, per `12_gcp_production_target.md`):**
- **Compute:** Cloud Run services in three GCP projects (`temple-dev`, `temple-staging`, `temple-prod`)
- **Database:** Cloud SQL Postgres 16, private IP, PITR enabled
- **Object Storage:** Cloud Storage buckets with versioning + lifecycle policies
- **Async Jobs:** Pub/Sub + Cloud Run Jobs
- **Secrets:** Secret Manager + Workload Identity Federation (no static keys)
- **Standards:** See `.claude/docs/gcp.md`

### Integrations
| Service | Purpose | Config Location (POC → Target) |
|---|---|---|
| Google SSO (OAuth2) | Authentication | `fly secrets` → Secret Manager |
| Twilio | SMS notifications | Admin Panel + `fly secrets` → Admin Panel + Secret Manager |
| Slack Webhooks | Internal team alerts | Admin Panel + `fly secrets` → Admin Panel + Secret Manager |
| SendGrid | Transactional email | `fly secrets` → Secret Manager |
| Google Maps Platform | Drive time calc, iOS routing | `fly secrets` → Secret Manager |
| eSign Provider (TBD) | Consignment contracts | Stubbed — `SigningService` interface |
| Valuation API (TBD) | Equipment comps | Stubbed — `ValuationService` interface |
| Playwright / AI Agent | Web scraping for comps | Internal service, Phase 5+ |

---

## 3. Personas

| Persona | Role Slug | Description |
|---|---|---|
| Customer | `customer` | Equipment owner submitting items for appraisal or consignment |
| Sales Rep | `sales` | TempleHE employee who owns customer relationships and publishes listings |
| Appraiser | `appraiser` | Field tech who evaluates equipment on-site using the iOS app |
| Sales Manager | `sales_manager` | Approves appraisal valuations and re-approves price changes |
| Admin | `admin` | Full system access, configuration, routing rules, user management |
| Reporting User | `reporting` | Read-only access to analytics and report generation |

---

## 4. Core Data Models (Summary)

Full field-level detail is in `02_schema_and_dictionary/01_normalized_app_field_schema_v1.md` and `02_schema_and_dictionary/01_data_dictionary_complete.csv`.

### Key Entities
- **Customer** — business and contact info; one customer can have many equipment records
- **EquipmentRecord** — one machine; child of Customer; has status, assignments, and appraisal data
- **AppraisalSubmission** — the completed field appraisal payload from the iOS app; child of EquipmentRecord
- **AppraisalPhoto** — individual photo with EXIF metadata; child of AppraisalSubmission
- **ComponentScore** — per-component score (0–5); child of AppraisalSubmission
- **AppraisalReport** — generated PDF record; references AppraisalSubmission
- **ConsignmentContract** — eSign document record; child of EquipmentRecord
- **ChangeRequest** — customer-initiated change; types: Delete, UpdateDescription, UpdateHoursCondition
- **LeadRoutingRule** — routing rule configuration; Admin-managed
- **CalendarEvent** — appraisal appointment; linked to EquipmentRecord + Appraiser
- **AuditLog** — immutable event log for all state transitions
- **RecordLock** — pessimistic lock with heartbeat TTL; backed by Postgres advisory locks + a `record_locks` row in POC, by Redis after GCP migration. The `RecordLockService` interface stays identical.
- **AppConfig** — key/value store for Admin-managed global variables (including iOS config)
- **NotificationPreference** — per-employee channel preference (email | sms | slack)

### EquipmentRecord Status Flow
```
New Request
  → Appraisal Scheduled
  → Appraisal Completed
  → Pending Manager Approval
  → Approved — Pending eSign
  → eSigned — Pending Publish
  → Published
  → (terminal) Withdrawn / Rejected
```

---

## 5. Equipment Categories

Categories are **fully dynamic** — Admins have complete CRUD control over every category and all of its attributes via the Admin Panel (Phase 4, Epic 4.8). No code deployment is required to add, rename, or remove a category, or to change any of its attributes.

**Each category is defined by:**
- Name and URL-safe slug
- Component list (name + scoring weight %) — weights auto-normalize if they don't sum to 100%
- Inspection prompts (label, response type, required flag, display order)
- Attachment/option list (label, active flag)
- Required photo checklist (label, helper text, required flag, display order)
- Red flag rules (condition field + value → triggered actions)

**Default seed categories (from `01_checklists/`):**
1. Articulated Dump Trucks, 2. Rigid Frame Dump Trucks, 3. Backhoe Loaders, 4. Dozers, 5. Excavators, 6. Mini Excavators, 7. Wheel Loaders, 8. Skid Steers, 9. Compact Track Loaders, 10. Motor Graders, 11. Telehandlers, 12. Wheel / Ag Tractors, 13. Crawler Loaders, 14. Scrapers, 15. Rollers / Compactors

These are the starting point, not a fixed list. New categories (e.g., Forklifts, Aerial Work Platforms, Cranes) can be added by an Admin at any time and will appear immediately in the customer intake form, the iOS app, and all scoring/reporting logic. Categories can be exported/imported as JSON for environment promotion.

**Data model:** Categories are stored in a `equipment_categories` table, not in `AppConfig`. Each related entity (components, prompts, attachments, photo slots, red flag rules) has its own normalized table with a foreign key to `equipment_categories`. The iOS config endpoint assembles and returns the full category tree.

---

## 6. Scoring System

Source: `03_implementation_package/06_scoring_and_rules_logic.csv`

- Each major component is scored 0–5 (see `01_checklists/00_condition_scale_and_scoring.md`)
- Component weights vary by machine category
- Weighted overall score = Σ(component_score × weight_percent / 100)
- Score bands:
  - 4.50–5.00 → Premium resale-ready
  - 3.75–4.49 → Strong resale candidate
  - 3.00–3.74 → Usable with value deductions
  - 2.00–2.99 → Heavy discount / repair candidate
  - 1.00–1.99 → Project, salvage, or parts-biased
  - 0.00–0.99 → Not enough verified information

### Red Flag Triggers (all categories)
- `structural_damage = true` → set `management_review_required`, downgrade marketability one band
- `active_major_leak = true` → set `management_review_required`
- `missing_serial_plate = true` → set `hold_for_title_review`
- `running_status = Non-Running` → set `management_review_required`, set `marketability_rating = Salvage Risk` (unless overridden)
- `hours_verified = false` → append review note

---

## 7. Record Locking (Pessimistic Concurrency)

- Lock acquired when any user begins editing a record
- POC: Postgres `pg_try_advisory_lock(hash(record_id))` + a `record_locks` row tracking `(record_id, user_id, acquired_at, last_heartbeat_at)` for visibility/admin override; effective TTL of 15 minutes enforced by the heartbeat sweeper. Target (post-GCP migration): Redis key with a 15-minute TTL and identical heartbeat semantics.
- Heartbeat signal from the client resets the lock every 60 seconds while editing is active
- On inactivity timeout (no heartbeat for 15 min), lock auto-releases
- Admin and Sales Manager roles can manually override (break) any lock
- All lock events written to AuditLog
- The `RecordLockService` API is the same on both stacks — only the implementation swaps at migration

---

## 8. Notification Architecture

- All outbound notifications dispatched via a `NotificationService` class
- Per-employee `NotificationPreference` controls channel: `email`, `sms`, or `slack`
- Notification events are enqueued (POC: `notification_jobs` Postgres table drained by a scheduled Fly Machine; target: Pub/Sub topic + Cloud Run Job consumer) and dispatched to SendGrid / Twilio / Slack webhook. The `NotificationService` API is the same across stacks.
- Customer-facing notifications always go to the email + preferred channel on their profile

---

## 9. Testing Strategy

Full spec in `09_testing_strategy.md`. Summary:

- **Unit tests** (pytest / Vitest / XCTest) — run on every commit; 85% coverage minimum on all service classes
- **Integration tests** (FastAPI TestClient + real test DB) — run on every PR; every endpoint has happy path, auth failure, RBAC failure, and validation failure cases
- **E2E tests** (Playwright for web, XCUITest for iOS) — run against staging after each phase deploy; a phase is not complete until its E2E gate passes in CI
- **Accessibility** — axe-core scans in Playwright E2E; Lighthouse ≥ 90 on all customer-facing pages
- **Security** — OWASP ZAP DAST scan post-Phase 1; `gitleaks` secret scanning on every PR; dependency audits on every PR

---

## 10. Development Phases

| Phase | File | Focus |
|---|---|---|
| 1 | `01_phase1_infrastructure_auth.md` | Platform infra (Fly.io + Neon + Cloudflare + R2), DB schema, Auth, RBAC, security middleware, observability |
| 2 | `02_phase2_customer_portal.md` | Customer registration, intake, dashboard, change requests, ToS/privacy, data export/deletion |
| 3 | `03_phase3_sales_crm.md` | Sales dashboard, lead routing, shared calendar, scheduling |
| 4 | `04_phase4_admin_panel.md` | Admin panel, global config, remote iOS config, health, **dynamic category CRUD**, staff departure handoff |
| 5 | `05_phase5_ios_app.md` | iOS appraiser app, offline sync, photos, dynamic checklists, min-version kill switch, Crashlytics |
| 6 | `06_phase6_approval_esign.md` | Scoring engine, manager approval, eSign stub, publish, webhook security |
| 7 | `07_phase7_pdf_reports.md` | Dynamic PDF appraisal report generation |
| 8 | `08_phase8_analytics_listing.md` | Reporting, analytics, public consignment listing page |
| — | `09_testing_strategy.md` | E2E framework, per-phase test gates, performance baselines, security scanning |
| — | `10_operations_runbook.md` | Fly.io-native runbook — environment architecture, deploy/rollback, backups, monitoring, incident response, onboarding |
| — | `11_security_baseline.md` | Password reset, rate limits, XSS/CSP, secrets rotation, email/SMS compliance, webhook security (platform-agnostic) |
| — | `12_gcp_production_target.md` | Documented GCP target architecture — three-project layout, Cloud Run + Cloud SQL + Memorystore + Pub/Sub, WIF, Terraform outline |
| — | `13_hosting_migration_plan.md` | Fly → GCP cutover playbook — pre-migration readiness, cutover-day timing (T-90 → T+120), rollback, sunset |
| — | `project_notes/decisions.md` | ADR log (ADR-001: Fly.io POC + GCP target). Required reading each session. |

---

## 11. Global Engineering Rules (from CLAUDE.md)

- All new files start with a 2-line `ABOUTME:` comment block
- Never hardcode secrets — use `fly secrets` per app today (Secret Manager after GCP migration); load via env vars only
- WCAG 2.1 AA minimum on all UI; Lighthouse accessibility score ≥ 90
- TDD: tests written alongside implementation
- Scope guard: if a task touches more than 3 files, stop and confirm approach
- No `--no-verify` on commits
- Pin all base image versions; never use `latest`
- Match existing code style in any file touched

---

## 12. Gaps & Deferred Decisions (Logged for Future Phases)

Operational, security, and DR concerns are addressed in `10_operations_runbook.md` and `11_security_baseline.md`. The items below are product/business decisions that still need a human call before their phase begins.

| Item | Decision Needed By | Notes |
|---|---|---|
| eSign provider (DocuSign vs Dropbox Sign) | Phase 6 start | Stubbed behind `SigningService` interface |
| Paid valuation API (IronPlanet vs EquipmentWatch) | Phase 5+ | Internal DB + Playwright scraper first |
| Public listing page URL / domain | Phase 8 | Needs TempleHE web team coordination |
| SOC 2 compliance scope | Post-launch | Not targeted for initial launch; baseline controls in `11_security_baseline.md` cover SMB needs. Revisit if an enterprise buyer requires it. |
| App Store review timing | Phase 5 completion | Submit early to avoid launch delay |
| Twilio A2P 10DLC brand/campaign registration | Phase 1 completion | ~2 week approval window; start during Phase 1. Required by US carriers before any SMS goes out. See `11_security_baseline.md` §5. |
| SendGrid SPF/DKIM/DMARC DNS records | Phase 1 completion | Needs TempleHE domain admin to add records. See `11_security_baseline.md` §5. |
