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
- Object Storage: Cloudflare R2 (immutable key naming — R2 does not support object versioning)
- Async Jobs: Postgres `jobs` table drained by scheduled Fly Machines
- Secrets: `fly secrets` per app
- Edge: Cloudflare WAF (Managed ruleset), CDN, Full (Strict) TLS, HSTS preload

**GCP target stack (post-migration):**
- Compute: Cloud Run (three GCP projects: `temple-dev`, `temple-staging`, `temple-prod`)
- Database: Cloud SQL Postgres 16, private IP, PITR
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

---

## ADR-009: Phase 1 Auth — Email/Password + TOTP (No SSO in Phase 1)

**Date:** 2026-04-20
**Status:** Accepted (supersedes ADR-004 scope for Phase 1 only)
**Deciders:** Jim Wilen

### Context

ADR-004 specified Google SSO only for authentication. During Phase 1 planning, the decision was made to defer Google OAuth implementation and build a working email/password system first for faster iteration. Google SSO can be added behind the `SSOService` stub without changing existing auth flows.

### Decision

Phase 1 implements **email/password + optional TOTP 2FA** only. Google OAuth is stubbed (`SSOService` interface) and documented in `docs/fly-provisioning.md`. No staff-only SSO in Phase 1.

### Consequences

- `password_hash` column is not nullable until SSO is implemented (diverges from original schema note).
- Google SSO implementation is a Phase 1 or Phase 2 add-on, scheduled when Jim confirms timing.

---

## ADR-011: POC Database Hosting — Neon over Fly Postgres

**Date:** 2026-04-20
**Status:** Accepted
**Deciders:** Jim Wilen

### Context

Fly.io offers a built-in Postgres option. The question was whether to use it instead of Neon for the POC, given that Fly is already our compute host and consolidating vendors has operational appeal.

### Decision

Use **Neon Postgres** for the POC, not Fly Postgres.

### Rationale

**Fly Postgres is not a managed service.** It is a Fly Machine running Postgres in a VM that you own and operate. Backups, failover, and recovery are the operator's responsibility. For a one-engineer team on an 8–24 hour SLA, any database incident that requires hands-on recovery is unacceptable.

**Neon is fully managed.** Automatic failover, connection pooling (PgBouncer built in), and point-in-time recovery are included. No operational burden on the operator.

**Neon's branching model fits the dev workflow.** Neon treats database branches like git branches — `dev`, `staging`, and `prod` are branches of the same project. Schema migrations can be tested against a branch before being promoted. This is a natural fit for the three-environment Fly setup and mirrors how Cloud SQL environments would be managed on GCP.

**Autoscale to zero.** Neon's serverless compute scales to zero when idle. Fly Postgres keeps a VM running 24/7 regardless of traffic. At POC scale, this matters for cost.

**Migration to GCP is identical either way.** The app only knows `DATABASE_URL`. Swapping Neon → Cloud SQL is one env var change per app. Fly Postgres → Cloud SQL is the same swap. The migration path is not easier or harder with either choice.

**Cost.** Neon's free tier covers the dev branch comfortably. Fly Postgres starts at ~$5–7/month for the smallest always-on machine.

### Tradeoffs

- Neon adds a second vendor dashboard during the POC period (Fly + Neon). Acceptable given the operational benefits.
- Neon's serverless cold-start latency (~100–300ms after sustained idle) is not a concern at POC scale with keepalive health checks in place.

### Postgres Version

**Use Postgres 16** across all environments (local dev, Neon, and eventual Cloud SQL). Rationale: Postgres 17 was released Oct 2024 and Cloud SQL support for it is recent; Postgres 16 has a longer track record in GCP's managed environment and has no meaningful feature gaps for this project. `docker-compose.yml` and Neon branches are both pinned to 16. Upgrade to 17 when Cloud SQL support matures.

### Consequences

- Neon project `temple-he` with branches `dev`, `staging`, `prod`. PITR enabled on `prod` branch (requires Neon Pro — upgrade before any real customer data lands).
- `DATABASE_URL` is the only app-level coupling to Neon. No Neon-specific SDK or client code anywhere in the application.
- `docker-compose.yml` pinned to `postgres:16.9-alpine` to match Neon and Cloud SQL target.
- See Manual Tasks doc section 4 for provisioning steps.

---

## ADR-012: Phase 1 Hardening — Remediations from Pre-Phase-2 Review

**Date:** 2026-04-21
**Status:** Accepted
**Deciders:** Jim Wilen

### Context

After Phase 1 Sprint 5 landed the full infrastructure + auth stack, a triaged code review (`project_notes/code_review_phase1.md`) surfaced 35 findings across auth, validation, error handling, state, secrets, observability, dependencies, and dead code. Several were ship-stoppers for Phase 2 (refresh tokens not delivered, rate limiter keyed on the wrong IP, 2FA enable/disable required no password re-auth, python-jose CVEs, email sends blocking the request path). This ADR records the design decisions made while hardening Phase 1 before Phase 2 begins.

### Decisions

1. **Refresh tokens are delivered via an HttpOnly + SameSite=Strict cookie scoped to `/api/v1/auth`.** Not a bearer body field. `/refresh` and `/logout` read the cookie; `/logout` clears it. `/2fa/verify` and `/2fa/recovery` also set the cookie on successful elevation from partial token. Cookie `secure` is toggled on `settings.is_production`.

2. **JWT signing moves from `python-jose` to `PyJWT`.** python-jose is effectively unmaintained with two open CVEs (algorithm confusion, JWT bomb DoS). PyJWT defaults to rejecting `alg=none` and is actively maintained. All JWT call sites (auth service, auth middleware, structured-logging middleware, tests) migrated in one pass.

3. **Email dispatch is non-blocking via FastAPI `BackgroundTasks`, with a `_safe_send` decorator that logs-and-swallows.** This is a Phase-1 stopgap — not a durable queue. Phase 2's intake confirmation email (feature 2.2.2) uses `NotificationService` via the `notification_jobs` Postgres queue per ADR-001. Service functions that dispatch email take an optional `background_tasks: BackgroundTasks | None` and fall back to inline `await` for tests and scripts.

4. **2FA enable and disable require the current password in addition to the TOTP code.** A stolen access token alone is no longer sufficient to bind or unbind the account from an authenticator. Wrong password emits a `user.2fa_reauth_failed` audit event.

5. **Client IP resolution prefers `CF-Connecting-IP` (Cloudflare) → `X-Forwarded-For` first entry → socket peer.** Centralized as `middleware.rate_limit.get_client_ip()`. Documented trust boundary: requests that bypass both Cloudflare and Fly's proxy can forge these headers, but only affect their own rate-limit bucket. No cross-user impact.

6. **Observability: the logging middleware never re-verifies JWTs.** Instead, `middleware.auth.get_current_user` stashes `user_id` on `request.state` after successful decode; the logging middleware reads it from the ASGI scope. `request_id.py` sets a Sentry tag per request. 5xx responses log at `error`; uncaught exceptions get `logger.exception` with class + traceback.

7. **`audit_logs` is partitioned monthly on `created_at`.** Migration 003 rewrites the flat table. In PG 16 the parent trigger and indexes propagate to all partitions. Migration 004 adds `fn_sweep_retention()` (deletes stale `rate_limit_counters`, `webhook_events_seen`, long-expired/revoked `user_sessions`) and `fn_ensure_audit_partitions()` (creates partitions for current + next two months, advisory-locked). A `temple-sweeper` Fly Machine invokes both hourly via `scripts/sweep_retention.py`.

8. **`get_db` auto-commit behavior is kept and documented.** One DB transaction per request is the right default for simple CRUD. Services that need multi-step work (commit record → fire event → open new tx) must instantiate `AsyncSessionLocal()` directly rather than relying on the FastAPI dependency. Comment in `api/database/base.py:42-50`.

9. **CORS locked to explicit methods and headers.** `allow_methods=["GET","POST","PUT","PATCH","DELETE","OPTIONS"]`, `allow_headers=["Authorization","Content-Type","X-Request-ID"]`. Credentials still allowed since the origin list is constrained.

10. **Trivy scanner: `ignore-unfixed: false`.** Suppressions require per-CVE entries in `.trivyignore` with justification. Unfixed-but-exploitable CVEs surface instead of silently suppressing.

### Deferred items (recorded here for provenance)

- **TOTP `MultiFernet` rotation** → Phase 5 sprint 0 (`dev_plan/05_phase5_ios_app.md`, `dev_plan/11_security_baseline.md §14`).
- **Prometheus `/metrics` endpoint** → later phase (`11_security_baseline.md §14`).
- **boto3 → aioboto3 evaluation** → not planned; flagged for reconsideration if R2 becomes hot.
- **PII retention for `user_sessions`, `known_devices`, `audit_logs` row-level** → Phase 2 data export/deletion work (`11_security_baseline.md §7`).

### Consequences

- `.env.example`, README, `docs/fly-provisioning.md`, CI `$GITHUB_ENV` no longer reference `JWT_REFRESH_SECRET`. Deployments can drop the secret next rotation.
- Web frontend uses `withCredentials: true` on auth-adjacent fetches so the cookie rides along. If staging origin ≠ API origin, verify `SameSite=Strict` doesn't break the cross-origin cookie during staging smoke.
- The hourly `temple-sweeper` machine must be provisioned via `fly machine run . --app temple-sweeper --schedule hourly` before Phase 2 traffic exercises the rate limiter or the webhook dedup table.

### References

- Working branch: `phase1-hardening` (14 commits; single PR to `main`).
- Code review: `project_notes/code_review_phase1.md` + Outline https://kb.saltrun.net/doc/baXdhfglbk.
- Resolution table: same document, "Remediation status" section.

---

## ADR-010: Session and Rate Limiting Storage — Postgres Tables in POC

**Date:** 2026-04-20
**Status:** Accepted
**Deciders:** Jim Wilen

### Context

ADR-002 bans Redis in POC. The auth spec references Redis for refresh token storage. These are reconciled here.

### Decision

Use two Postgres tables in the POC:
- `user_sessions` — opaque refresh tokens (SHA-256 hashed). Replaces Redis session store.
- `rate_limit_counters` — fixed-window counters keyed by endpoint+identity. Replaces Redis rate limiter.

Both are accessed via `SessionService` and `RateLimitService` interfaces. The GCP migration swaps both implementations to Redis Memorystore with zero application code changes.

### Performance

- At POC scale (< 20 users, < 100 req/min), overhead is negligible (~1ms per session lookup, ~2ms per rate limit check).
- Expired `user_sessions` rows cleaned lazily on read + periodic vacuum.
- `rate_limit_counters` pruned daily by a lightweight cron query.

### Consequences

- `user_sessions` and `rate_limit_counters` are present in the initial Alembic migration.
- No Redis dependency in the POC environment (docker-compose.yml has only Postgres + Mailpit).
