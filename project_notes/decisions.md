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

## ADR-013: Phase 2 Customer Portal — Notification Queue, Right-to-Erasure, Access Response Shape

**Date:** 2026-04-24
**Status:** Accepted
**Deciders:** Jim Wilen

### Context

Phase 2 shipped the customer portal end-to-end: registration with ToS/Privacy consent, equipment intake with reference numbers, photo upload to R2, status timeline with customer-facing emails, change requests, GDPR-lite data export, and 30-day-grace account deletion. Several decisions made during implementation deserve their own ADR entry so future phases can build on the same contract.

### Decisions

1. **`notification_jobs` durable queue = Postgres, claimed via `SELECT … FOR UPDATE SKIP LOCKED` using `clock_timestamp()`.** Enqueue is idempotent on an optional `idempotency_key` (UNIQUE partial index when NOT NULL). Failures retry with exponential backoff (30s → 1m → 5m → 30m → 6h, cap 5 attempts). Tests and dev can run `scripts/notification_worker.py` as a single-pass drain (`WORKER_SINGLE_PASS=1`); prod/staging run it as a long-running Fly Machine per `infra/fly/temple-notifications.toml`. This is the concrete implementation of the `NotificationService` interface promised in ADR-001.

2. **Customer-facing status emails are enqueued from a single entry point: `equipment_status_service.record_transition()`.** Six watched destinations (`appraisal_scheduled`, `appraisal_complete`, `offer_ready`, `listed`, `sold`, `declined`) each enqueue one message, keyed as `status_update:{record_id}:{to_status}` so retries + bounce-back same-status transitions don't duplicate. Phase 3 sales-rep endpoints will call this same function; no parallel transition paths.

3. **Right-to-erasure = pseudonymization, not hard delete.** At grace expiry (`fn_delete_expired_accounts()`), `users.email`, `users.first_name`, + the `customers` PII fields are nulled or replaced with `[deleted]` markers; `status` → `deleted`; session secrets are wiped. Equipment records, consignments, and appraisal history remain as business facts, detached from the scrubbed identity. Deleted users can no longer authenticate — any surviving access token 401s via the `middleware.auth.get_current_user` status check. This trades "full row removal" (which would cascade into business-critical tables and break reporting) for a cleaner defense of the retention promise: the identity is gone, the transaction record stays.

4. **`audit_logs` PII scrubber bypasses the append-only trigger via a session GUC, not a role or role-grant.** `fn_scrub_audit_pii(days)` sets `templehe.pii_scrub='on'` for the duration of its transaction; the trigger body explicitly recognizes that GUC and yields. Application-code UPDATEs and DELETEs against `audit_logs` outside that function are still blocked. Rationale: the scrubber runs as the same DB user as the app, so role-based trigger bypass would require an elevated connection and a second pool. A GUC is narrower (only the scrubber stored proc sets it), easier to audit in the trigger body, and survives pg_dump/restore.

5. **Reference numbers are Crockford-32 encoded, format `THE-XXXXXXXX` (8 chars).** Crockford-32 chosen over base32 to drop ambiguous glyphs (I/1, O/0) — customers read these over the phone to sales reps. `secrets.token_bytes(5)` → Crockford encode → take first 8 chars, uppercase. UNIQUE constraint on `equipment_records.reference_number` with regenerate-on-collision loop. Collision probability at POC volume is vanishingly small; the retry loop is belt-and-suspenders.

6. **Cross-customer record access returns 404, not 403.** Spec (Phase 2 Gate in `dev_plan/09_testing_strategy.md`) says "returns 403". We deliberately return 404 instead so the response shape doesn't differentiate "this record doesn't exist" from "this record exists but you can't see it" — no ID-space enumeration. This posture is enforced in `equipment_service.get_record_for_user` and asserted in `test_equipment_intake.py`. It supersedes the "403" wording in the spec for every customer-scoped record lookup.

7. **Email verification on web uses React Query, not a `useEffect`+`useMutation`.** StrictMode double-mount fires the verification token at `/auth/verify-email` twice; the first succeeds and flips the user to `active`, the second 400s on an already-consumed token. `useQuery` dedupes by key and caches the success state, which is the right primitive for a one-shot idempotent read on page load. Future one-shot token-gated reads should follow this pattern.

8. **macOS networking traps neutralized at the config boundary.**
   - `smtp_host` defaults to `127.0.0.1` (not `localhost`) because macOS's getaddrinfo returns `::1` first and Mailpit binds IPv4; the fallback took ~35s per email.
   - `smtplib.SMTP(..., local_hostname="localhost", timeout=10)` skips `socket.getfqdn()` which hangs ~35s on macOS mDNS with no responder.
   - Vite's `/api` proxy `target` is `http://127.0.0.1:8000` for the same IPv6-first reason.
   Same trap class — IPv6-preferring resolver vs. IPv4-only listener on macOS. Any future outbound localhost connection from Python or Node dev should pin to 127.0.0.1 explicitly.

### Consequences

- `temple-notifications` + `temple-sweeper` Fly apps must be created before production handles real customer data (see `known-issues.md`). Without `temple-notifications`, the portal accepts submissions and fills the queue silently; no user-facing regression, but emails never leave.
- The notification queue's `idempotency_key` index is a PK-shaped UNIQUE partial index. Future services enqueuing notifications should pick collision-free keys (e.g., `status_update:<record_id>:<status>`, `export:<export_id>`) so retries remain safe.
- `fn_delete_expired_accounts()` does not cascade through equipment_records. Any future Phase 3+ report that joins users ↔ equipment_records must handle the `users.status='deleted'` case; anonymized users appear as `[deleted]` rather than disappearing.
- Phase 3 sales-rep change-request resolution endpoints will reuse `record_transition()` for status updates, reuse `NotificationService.enqueue` for resolution emails, and must add the "one pending change request at a time" guard documented in `known-issues.md`.
- Frontend tests for any token-consumed endpoint (email verify, password reset confirm) should use `useQuery` not `useMutation` to survive StrictMode.

### References

- Working branch: `phase2-customer-portal` (6 commits; single PR #28 to `main`, merged at `a42ad7b` on 2026-04-24).
- Phase spec: `dev_plan/02_phase2_customer_portal.md`.
- Deferrals + follow-ups: `project_notes/known-issues.md` (prod-go-live bundle + duplicate change-request + SMS warning copy).

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

---

## ADR-014: Phase 3 Sprint 3 — Lead Routing Engine

**Date:** 2026-04-25
**Status:** Accepted
**Deciders:** Jim Wilen

### Context

Phase 3 Sprint 3 ships the lead routing engine (Epic 3.3) that auto-assigns incoming `equipment_records` to a sales rep at intake time. The waterfall — ad-hoc → geographic → round-robin → AppConfig fallback — is straightforward, but two implementation choices warrant their own ADR entry so Phase 4 (admin UI), Phase 5 (iOS push), and the GCP migration build on the same contract.

### Decisions

1. **Round-robin counter uses `UPDATE … RETURNING` on a Postgres row, not Redis `INCR`.** ADR-002 bans Redis in POC, so the rotation index lives in `lead_routing_rules.round_robin_index`. The atomic-claim path (`services/lead_routing_service._claim_next_round_robin`) issues a single statement: `UPDATE lead_routing_rules SET round_robin_index = round_robin_index + 1 WHERE id = :id RETURNING round_robin_index`. Postgres's row-level lock serializes concurrent intakes; each sees a distinct counter value, same semantics as Redis `INCR`. The rep is selected with `rep_ids[(returned_index - 1) % len(rep_ids)]` so the very first intake against a fresh rule lands on `rep_ids[0]`. GCP migration can swap to `redis.incr` without touching the public service signature.

2. **Routing is non-blocking on intake.** `equipment_service.submit_intake` calls `_route_and_assign` after `db.flush() + db.refresh()` and before the customer confirmation enqueue. The whole call is wrapped in `try/except Exception` — if routing crashes (bad rule data, race with admin edits, transient DB issue), we log `lead_routing_failed` and the record stays unassigned. Customers always see their submission accepted; a manager triages the orphan from the dashboard. Tested in `test_routing_failure_does_not_block_intake`.

3. **Soft delete via `deleted_at` timestamp, never row removal.** `LeadRoutingRule.deleted_at` (added in migration `010`) preserves historical rules so audit rows that reference `rule_id` keep resolving. Soft-deleted rules are excluded from the waterfall via the partial index `ix_lead_routing_rules_active ON (priority) WHERE deleted_at IS NULL AND is_active = true`. `GET /admin/routing-rules?include_deleted=true` is the escape hatch for forensics.

4. **`AppConfig.default_sales_rep_id` is the floor.** When no rule matches, the engine reads `AppConfig` key `default_sales_rep_id` (shape `{"user_id": "<uuid>"}`). If the key is unset or the user is invalid, the record stays unassigned and the audit row is written with `trigger='unassigned'` so managers can reconcile. The default rep is set by admins via Phase 4's settings UI; for the POC it's set directly in the DB.

5. **One shared `record_assigned` notification template, idempotency keyed by trigger.** Both routing-time assignment (`trigger='lead_routing'` or `'default_sales_rep'`) and manual reassignment via the Phase 3 Sprint 2 PATCH (`trigger='manual_override'`) use the same `record_assigned` template. The idempotency key is `record_assigned:{record_id}:{user_id}:{trigger}` — distinct triggers don't collide, so a manual reassignment after auto-routing produces two emails (correct UX: the rep gets one when the record lands, another when ownership shifts).

6. **Service-level condition validation before persistence.** The Pydantic schemas accept any `dict` for `conditions`; `services/lead_routing_service._validate_conditions` enforces the rule-type-specific shape (ad_hoc needs `condition_type` + `value`; geographic needs at least one of `state_list` / `zip_list`; round_robin needs a non-empty `rep_ids` list). A malformed rule body returns 422 instead of silently never matching. Same guardrail runs on PATCH.

7. **Geographic metro-area matching is deferred to Sprint 4.** The matcher silently skips `metro_area` keys without erroring (`test_geo_skips_metro_area_silently`). Sprint 4's calendar work brings Google geocoding; metro-area routing slots in then without breaking existing rules.

### Consequences

- Migration `010` extends `lead_routing_rules` with `created_by`, `created_at`, `deleted_at` and the partial active-rules index. The pre-existing table from Phase 1's initial migration kept its `round_robin_index`, `priority`, `is_active`, `conditions` (JSONB), and `assigned_user_id` columns.
- `services/equipment_service.enqueue_assignment_notification` is the single chokepoint for assignment emails — both the routing path and `services/sales_service.apply_assignment` call it. Phase 4's bulk-reassignment tooling and Phase 5's iOS-push integration should call this same function rather than enqueueing parallel emails.
- The atomic counter is exercised by `test_round_robin_cycles_through_reps` (3 sequential intakes → assignments [a, b, a], counter = 3). Concurrent intake serialization is delegated to Postgres row locks; no application-level mutex.
- Admin RBAC on `/admin/routing-rules` is `admin`-only; sales managers cannot author rules. Phase 4's settings UI inherits this restriction.
- `default_sales_rep_id` is **not** seeded by `scripts/seed.py` — it stays unset until an admin chooses one in Phase 4. Until then, dev/staging intakes with no matching rule produce `trigger='unassigned'` audit rows by design.

### References

- Working branch: `phase3-sales-crm`.
- Phase spec: `dev_plan/03_phase3_sales_crm.md` Epic 3.3.
- Implementation: `api/services/lead_routing_service.py`, `api/routers/admin_routing.py`, `api/alembic/versions/010_phase3_lead_routing_audit_columns.py`.
- Tests: `api/tests/unit/test_lead_routing_service.py` (16 tests), `api/tests/integration/test_lead_routing.py` (11 tests), `api/tests/integration/test_admin_routing_rules.py` (7 tests).

---

## ADR-015: Phase 3 Sprint 4 — Shared Calendar, Drive-Time Buffer, Metro-Area Routing

**Date:** 2026-04-25
**Status:** Accepted
**Deciders:** Jim Wilen

### Context

Phase 3 Sprint 4 ships Epic 3.4 in full (calendar + scheduling + Google Distance Matrix drive-time buffer + edit/cancel) and the Sprint 3 carry-forward (metro-area routing rules). Several decisions warrant their own ADR so Phase 4 (Admin Panel), Phase 5 (iOS push), and the GCP migration build on the same contract.

### Decisions

1. **Drive-time + geocode caches live in Postgres for the POC.** Two new tables in migration `011`: `drive_time_cache(origin_hash, dest_hash, duration_seconds, fetched_at, expires_at)` with composite PK and 6h TTL, plus `geocode_cache(address_hash, lat, lon, fetched_at, expires_at)` with 30d TTL (addresses move rarely; longer cache reduces API call volume substantially). Both are read-through: services check the cache first, hit the API only on miss, write back. This is the same Redis-swap-contract pattern as record locks (ADR-013) and the round-robin counter (ADR-014). GCP migration swaps to `SETEX 21600` / `SETEX 2592000` without touching the public service surface in `services/google_maps_service.py`.

2. **`google_maps_service` returns `None` on every failure mode — never raises.** No API key configured (`settings.google_maps_api_key=""`), network timeout, non-OK Google status, malformed response body — all collapse to `None`. Callers (`calendar_service` + `lead_routing_service`) treat `None` as documented sentinels: the calendar substitutes the AppConfig fallback minutes (`drive_time_fallback_minutes`, seeded to 60); the metro-area matcher falls through to the next geographic rule. This keeps the calendar and intake paths working in dev / test / staging *without* a key, and prevents a flaky API from dropping a customer's intake.

3. **Conflict detection uses `SELECT … FOR UPDATE` over the appraiser's day window.** `calendar_service._check_conflict` opens a row lock on the appraiser's same-day events before checking the proposed window. Concurrent schedule attempts serialize on that lock; only the first wins, the second sees the conflict. Drive-time buffer is applied on both sides — the new event must start `buffer` after the previous event ends AND end `buffer` before the next event starts. Buffer source: real Distance Matrix call (cached) → fallback minutes when the call fails or is unconfigured. Tested with `test_drive_time_buffer_blocks_when_addresses_far_apart` using the fallback path.

4. **409 response carries `next_available_at` and `conflicting_event_id`.** The router returns a structured JSON body (not just a `detail` string) so the UI can offer a one-click reschedule to the next slot. The schema (`CalendarConflictResponse`) is deliberately distinct from FastAPI's default 422 body shape; clients must check status before parsing.

5. **Calendar editing is open to `sales`, `sales_manager`, and `admin`.** Per spec line 179 (updated 2026-04-24), all three roles can create / edit / cancel / reschedule. Audit rows capture `actor_role` so managers can review sales-rep changes via the audit trail. Customer role is rejected at the RBAC dependency.

6. **Schedule transitions `new_request → appraisal_scheduled`; cancel reverts to `new_request`.** Both transitions go through `equipment_status_service.record_transition` so the customer status email (`status_appraisal_scheduled` template, Phase 2 Sprint 3) fires for free on schedule. Cancel does not re-fire the status email — it sends the dedicated `appraisal_cancelled_customer` template instead, since "we cancelled your appointment" is a different message than "your status changed". Idempotency key for cancel email: `appraisal_cancelled_customer:{event_id}`.

7. **Metro-area routing geocodes the customer address, applies haversine vs metro center.** New rule shape: `{"metro_area": {"center_lat": …, "center_lon": …, "radius_miles": …}}`. The matcher (`lead_routing_service._metro_matches`) builds a single-string address from `customer.address_street + city + state + zip`, geocodes via the cached `google_maps_service.geocode`, and computes the haversine distance in statute miles. This sits **after** the existing state/zip matchers in the geographic loop — a rule with `state_list` AND `metro_area` matches if either path hits, so admins can layer broad state coverage with a tighter Atlanta-metro carve-out without writing two rules.

8. **`appraisal_scheduled_appraiser` and `appraisal_cancelled_appraiser` are dedicated templates.** Distinct from `record_assigned` (lead routing / manual reassignment). The appraiser cares about a different surface — when, where, and a reference to the equipment record. Idempotency keys: `appraisal_scheduled:{event_id}:{user_id}` and `appraisal_cancelled:{event_id}:{user_id}`. Same template chokepoint pattern as ADR-014 #5.

9. **`react-big-calendar` skinned to match Tailwind, not hand-rolled.** A custom calendar grid would re-invent month/week/day pagination, accessibility, and keyboard navigation. The lib's stock CSS imported once; appraiser color coding via `eventPropGetter`; click-to-detail via `onSelectEvent`. The eight-tone palette in `pages/SalesCalendar.tsx` cycles for >8 appraisers — a contract surface for future "global appraiser color settings" if it matters.

### Consequences

- Migration `011` adds two cache tables + the `drive_time_fallback_minutes` AppConfig key (seeded to 60). The hourly `fn_sweep_retention()` function should drop expired rows from both caches in the next migration that touches it; for now the caches grow until manually cleaned. Tracked in `known-issues.md` as a follow-up.
- The Distance Matrix + Geocoding integrations require a Google Maps API key for live behavior. Today both fall back to the AppConfig minutes / silent no-op. Provisioning steps + cost expectations documented in `known-issues.md` "OPEN — Google Maps API key not provisioned".
- Calendar UI works without a key — direct overlap conflicts are exact, drive-time buffer just applies a flat 60-min minimum. This is acceptable for POC + early staging.
- Phase 4 (Admin Panel) ships:
  - The searchable user picker (sales rep / appraiser / customer) the calendar modal hand-rolls today
  - The CRUD UI for `lead_routing_rules` the API delivered in Sprint 3
  - The settings page that edits `drive_time_fallback_minutes` and (if Jim provides one) `default_sales_rep_id`
- Phase 5 (iOS) reuses `appraisal_scheduled_appraiser` for push notifications — both routes will go through `notification_service.enqueue` so idempotency stays consistent.
- Phase 3 Sprint 6 gate (Playwright + axe + Lighthouse) covers the calendar UI E2E. This sprint did **not** browser-verify the page — I verified TypeScript build + ESLint zero-warnings, but interactive UI testing is deferred to the gate sprint per project convention.

### References

- Working branch: `phase3-sales-crm`.
- Phase spec: `dev_plan/03_phase3_sales_crm.md` Epic 3.4 + Phase 1 Carry-Forward Notes.
- Implementation: `api/services/google_maps_service.py`, `api/services/calendar_service.py`, `api/routers/calendar.py`, `api/schemas/calendar.py`, `api/alembic/versions/011_phase3_drive_time_geocode_caches.py`, `api/services/lead_routing_service.py` (`_metro_matches`).
- Tests: `api/tests/integration/test_google_maps_service.py` (10), `api/tests/integration/test_calendar.py` (10), metro-area additions to `api/tests/integration/test_lead_routing.py` (+2). Full backend gate **291/291**.
- Frontend: `web/src/api/calendar.ts`, `web/src/pages/SalesCalendar.tsx`, `web/src/components/ScheduleAppraisalModal.tsx`, `web/src/components/Layout.tsx` (Calendar nav link), `web/src/App.tsx` (`/sales/calendar` route), `web/src/pages/SalesEquipmentDetail.tsx` (ScheduleCard).

---

## ADR-016: Phase 3 Sprint 5 — Workflow Notifications + Per-Employee Channel Preferences

**Date:** 2026-04-25
**Status:** Accepted
**Deciders:** Jim Wilen

### Context

Phase 3 Sprint 5 wires Epic 3.2 (manager-approval + eSign-completion sales-rep notifications), Feature 3.5.2 (lock-override notification to the prior holder), and the per-employee notification preferences UI. The Phase 6 triggers for the Epic 3.2 transitions don't exist yet — manager approval and eSign webhook are Phase 6 work — so Sprint 5 wires the *dispatch* on the existing `record_transition` chokepoint and lets Phase 6 plug the trigger in by simply calling `record_transition(to_status=...)`. Decisions captured here for Phase 4 (admin panel — needs the channel-pref data model), Phase 6 (eSign — needs the trigger contract), and Phase 5 (iOS push — needs the channel-resolution path).

### Decisions

1. **Sales-rep dispatch lives on `equipment_status_service.record_transition`, not on a Phase 6 webhook handler.** Adding a `_SALES_REP_NOTIFY_STATUSES = {"approved_pending_esign", "esigned_pending_publish"}` set + a `_notify_sales_rep` helper inside the same service the customer-email block already uses keeps a single chokepoint for "status changed → tell people". Phase 6's eSign webhook calls `record_transition(to_status="esigned_pending_publish", ...)` and the sales-rep notification fires for free; same for the manager-approval endpoint and `approved_pending_esign`. No new wiring needed at trigger time.

2. **Idempotency key: `sales_rep_status:{record_id}:{to_status}`.** Distinct from the customer-email key (`status_update:{record_id}:{to_status}`) so the same transition can deliver both, but a re-fired transition collapses each to one delivery. Same chokepoint pattern as ADR-014 #5 + ADR-015 #8.

3. **`notification_preferences_service.resolve_channel` collapses Slack to email.** No Slack dispatch path exists in `notification_service` — Phase 4/8 ships the Slack integration. Until then, accepting a Slack preference but routing through email keeps the user-facing model honest (your preference is recorded; we'll honor it the moment Slack ships) without enqueueing guaranteed-fail rows. SMS without a phone number falls back to email for the same reason — better email delivery than a queue full of failed SMS jobs.

4. **One row per user — `UNIQUE(user_id)` on `notification_preferences`.** The Phase 1 schema allowed multiple rows per user (one per channel); no caller ever wrote that way. The spec language is "preferred channel" (singular). Migration `012` adds the constraint and the upsert path uses `INSERT ... ON CONFLICT (user_id) DO UPDATE`. The `User.notification_preference` relationship switches to `Mapped[NotificationPreference | None]` with `uselist=False`.

5. **Two role-based gates: `is_hidden_for_role` (configurable) and `is_read_only_for_role` (hardcoded).** Customer is RO by default — they only have one channel (email) in practice and don't need the picker. The hidden-roles flag (`app_config` key `notification_preferences_hidden_roles`, default `[]`) lets an admin hide the page from any role entirely without a code change — same shape as the future YAML-seeded admin config (see #7). Editing the policy is two flags, not one combined "visibility" enum, because hiding and reducing-to-RO are conceptually different operations and tend to apply to different roles.

6. **Lock-override notification goes through the same `resolve_channel` path.** `routers/record_locks.py:override_lock` calls `_notify_prior_lock_holder` after the audit log writes; idempotency key `lock_overridden:{record_id}:{prior_user_id}`. SMS-preferred users get a short message; everyone else gets HTML email. Skipped silently when the prior user is gone or inactive — no good user-facing recovery for an orphan FK and the audit row already captured the override.

7. **Org-wide configurable settings get a YAML escape hatch (Phase 4).** Sprint 5 lands the first such flag (`notification_preferences_hidden_roles`) seeded by alembic for now. Phase 4 (Admin Panel) ships `scripts/seed_config.py` to read a `config/*.yaml` and upsert into `app_config` + `lead_routing_rules`; UI writes to DB only, YAML is seed/recovery state, drift is visible via `seed_config.py --check`. Per-user state (notification_preferences, equipment records) stays DB-only — YAML is for org-wide config that benefits from git-audited history. See `dev_plan/04_phase4_admin_panel.md` Pre-flight (added in this commit).

### Consequences

- Migration `012` adds the unique constraint + seeds the visibility flag; `_EXPECTED_MIGRATION_HEAD` bumps to `"012"` in `routers/health.py`.
- Phase 6 eSign + manager-approval triggers become a one-line call (`record_transition(...)`); no notification wiring added at that layer.
- Phase 5 iOS push reuses the same `resolve_channel` shape — when an iOS user opts into push, that's a fourth channel value the resolver returns, and `notification_service` gains a `_dispatch_push` branch. Public surface unchanged.
- The `account/notifications` route exists; nav link added for both customer + sales-side flows. The page is built but not browser-verified this sprint — interactive UI verification deferred to Phase 3 Sprint 6 gate.
- `notification_preferences_hidden_roles` is the first AppConfig key intended for the YAML-seed pattern; format chosen (`{"roles": [...]}`) so the YAML loader can read+validate without a dedicated enum.

### References

- Working branch: `phase3-sales-crm`.
- Phase spec: `dev_plan/03_phase3_sales_crm.md` Epic 3.2 + Feature 3.5.2 + Phase 1 Carry-Forward Notes.
- Implementation: `api/alembic/versions/012_phase3_notification_preferences_unique_and_visibility.py`, `api/services/notification_preferences_service.py`, `api/services/equipment_status_service.py` (sales-rep notify block), `api/routers/me_notifications.py`, `api/routers/record_locks.py` (override notify), `api/schemas/notification_preferences.py`, `api/database/models.py` (relationship + unique constraint), `api/main.py` (router mount), `api/routers/health.py` (head bump).
- Tests: `api/tests/integration/test_notification_preferences.py` (7), `api/tests/integration/test_sales_rep_status_notifications.py` (6), `api/tests/integration/test_record_locks.py` (+2 override-notify). Full backend gate **307/307** at 96% coverage.
- Frontend: `web/src/api/notifications.ts`, `web/src/api/types.ts` (notification types), `web/src/pages/AccountNotifications.tsx`, `web/src/App.tsx` (`/account/notifications` route), `web/src/components/Layout.tsx` (Notifications nav link, both flows).

---

## ADR-017: Phase 3 Sprint 6 — Playwright + axe Gate, Test-Infrastructure Decisions

**Date:** 2026-04-25
**Status:** Accepted
**Deciders:** Jim Wilen

### Context

Phase 3 Sprints 2, 4, and 5 each deferred interactive UI verification to the Sprint 6 gate. Sprint 6 closes the loop with E2E specs covering the sales dashboard, calendar, record locking, and notifications page across sales + customer roles, plus an axe pass for zero Critical/Serious. Decisions here govern how the Phase 3 specs share state with the API, how durable-queue notifications get verified end-to-end, and which Phase 3 UX gaps the spec asserts vs. flags.

### Decisions

1. **Phase 3 specs share a deterministic test fixture, not per-test isolation.** The seeder (`scripts/seed_e2e_phase3.py`) reuses fixed emails (`e2e-phase3-sales@example.com`, `…-manager@`, `…-appraiser@`, `…-customer@`) across modes; each spec re-seeds. The trade-off: random per-test users would let specs run in parallel cleanly, but the per-IP login limiter + per-email login limiter + Mailpit cross-test noise made parallelism unreliable for Phase 2 already (spec is `workers: 1`). With sequential execution, deterministic fixtures are cheaper and the Mailpit subject-match pattern stays simple. The cost is that every seed mode owns aggressive cleanup of the test customer's prior records, all future calendar events, notification preferences, rate-limit counters, and failed-login state — captured in `_purge_customer_records`, `_purge_future_calendar_events`, `_reset_notification_prefs`, `_reset_rate_limits`. Test-only operations; never invoked from production.

2. **Notification worker runs in CI as a backgrounded process.** Phase 3 introduces durable-queue notifications (lock-override email, sales-rep status emails) that the API enqueues but doesn't dispatch in-band. The worker (`scripts/notification_worker.py`) is the production drain; backgrounding it in the e2e job mirrors prod and lets `phase3_record_locking.spec.ts` assert the email arrives in Mailpit. `WORKER_POLL_INTERVAL=1` shortens the prod default of 5s for tighter test waits. Worker log uploads on failure for triage. Alternative considered: drain the queue manually from the test via a one-shot script (`WORKER_SINGLE_PASS=1`). Rejected because it diverges from prod and would mask a worker-side bug.

3. **Lighthouse stays at unauth `/login` + `/register`.** Auth-gated routes (`/sales`, `/sales/equipment/:id`, `/account/notifications`) aren't covered by Lighthouse CI in the POC. The static-dist + auth-injection wiring is non-trivial and the value-per-engineering-hour ratio is poor for a 15-person internal app; perf budget gating on auth pages can land in Phase 4 if it earns its keep. Accessibility for those pages IS gated — via axe-core in `phase3_accessibility.spec.ts`, which is the mode that catches the issues we actually ship around (labels, ARIA roles, keyboard reachability).

4. **react-big-calendar's empty `role="row"` gets two axe rules disabled, scoped to the calendar route only.** `aria-required-children` and `aria-required-parent` fire on the library's empty-week containers. The bug is upstream and the workaround is to wrap each row, which is invasive third-party patching. Disabling the two rules just for `/sales/calendar` keeps the rest of the suite strict. Documented inline in `phase3_accessibility.spec.ts` so future reviewers see the scope. Phase 4 (admin grid) revisits this pattern — likely the same library, likely the same exception.

5. **Manager auto-acquire after override is a known UX gap, asserted as the user sees it today.** When a manager overrides a lock, the backend deletes the prior holder's lock but does NOT acquire one for the manager. The next heartbeat 404s and the page shows "Your editing session timed out" rather than "You are editing this record." The spec asserts the conflict banner clears (the user-visible side-effect) and notes the gap rather than asserting the manager-held state. Fixing it is a small frontend change (call `acquireLock` after `overrideLock` instead of `refreshLock`) but out-of-scope for Sprint 6; tracked for a Phase 4 quality pass alongside the lock-picker UI.

6. **Mailpit subject match keys on the run-unique reference number.** `waitForEmailBody(toEmail, fixture.reference_number)` ties the assertion to the just-overridden record. Earlier draft used a static substring like `"your editing lock on"`, which matched stale emails from prior runs. The locking spec also calls `clearInbox()` at the start as belt-and-suspenders; either alone is enough but together they make spec re-runs against the same Mailpit instance trivially safe.

7. **Per-user notification-preference state is reset in the seeder, not via a UI logout-relogin pattern.** A spec that switches the sales rep to SMS leaks that preference to subsequent specs (e.g., the locking spec, where SMS dispatch routes through Twilio and "skips" because Twilio isn't wired in CI). `_reset_notification_prefs` runs in every relevant seed mode. Preferred over a UI-driven reset because (a) the UI doesn't have a "clear preferences" affordance, and (b) DB-level reset is one atomic step vs. multiple browser interactions.

### Consequences

- Phase 3 e2e gate is 10 specs; combined with Phase 2's 12 specs the suite is 22 specs in ~30s locally against vite preview + uvicorn + worker + Mailpit.
- Worker step in CI adds ~5s startup + ongoing 1s polling cost during the e2e job. Worth it for the lock-override coverage.
- The Phase 3 Completion Checklist in `dev_plan/03_phase3_sales_crm.md` is fully covered between this E2E gate and the Sprint 1–5 integration tests. Phase 3 closes here.
- The deferred manager-auto-acquire UX gap is documented in progress.md and ADR-017; Phase 4 reviews and decides whether to fix as part of the admin lock-picker work or earlier.

### References

- Working branch: `phase3-sprint6-gate`.
- Phase spec: `dev_plan/03_phase3_sales_crm.md` Phase 3 Completion Checklist.
- Implementation: `web/e2e/phase3_calendar.spec.ts` (extended), `web/e2e/phase3_sales_dashboard.spec.ts`, `web/e2e/phase3_record_locking.spec.ts`, `web/e2e/phase3_notifications.spec.ts`, `web/e2e/phase3_accessibility.spec.ts`, `web/e2e/helpers/api.ts` (shared `seedPhase3`), `web/e2e/helpers/mailpit.ts` (`waitForEmailBody`), `scripts/seed_e2e_phase3.py` (per-mode cleanup + new modes), `.github/workflows/ci.yml` (notification worker step).
- Test gate: 22/22 e2e green locally (12 Phase 2 + 10 Phase 3).

---

## ADR-018: Phase 3 → Phase 4 Pre-work — Architectural Debt Fixes

**Date:** 2026-04-25
**Status:** Accepted (commits in flight on `phase4-prework`; Commit 3 = multi-role users follows as a separate PR)
**Deciders:** Jim Wilen

### Context

The Phase 3 close-out architectural debt review surfaced 16 items across the Phase 3 surface area that Phase 4 will be built on top of. Four were Critical/High enough that fixing them now is materially cheaper than fixing after Phase 4 builds on them. The other 12 were intentionally deferred into Phase 4's scope (each fix lives naturally inside a Phase 4 epic). This ADR captures the pre-work decisions; the deferred items are documented in `dev_plan/04_phase4_admin_panel.md` § Architectural Debt to Address.

### Decisions

1. **Equipment status state machine extracted to `services/equipment_status_machine.py`.** The canonical set of `equipment_records.status` values + per-status metadata + transition rules now live in one module. Replaces inline `_FORBIDDEN_TRANSITIONS` denylists, `_CUSTOMER_EMAIL_STATUSES` / `_SALES_REP_NOTIFY_STATUSES` sets, and the `display` dict scattered across `equipment_status_service`, `calendar_service`, `sales_service`, `change_request_service`, `equipment_service`. Migration 013 installs a Postgres CHECK constraint enumerating the same values; a unit-test drift guard parses the migration's `_VALID_STATUSES` tuple and asserts equality with the runtime registry.

   Adding a new status: one row in `_REGISTRY` + bump migration 013's tuple + the drift-guard test passes. Phase 4 admin "manually transition this record" UI reads `all_status_values()` and `is_forbidden_transition()` instead of inventing its own copy of the rules.

   `withdrawn` status (used inline by `change_request_service` but not in the prior registry) was added during this work — caught by the CHECK constraint immediately.

2. **AppConfig key registry shipped as `services/app_config_registry.py`.** Each `app_config.key` registers a `KeySpec(name, category, field_type, description, default, parser, serializer, validator)`. Five existing keys registered (`tos_current_version`, `privacy_current_version`, `drive_time_fallback_minutes`, `default_sales_rep_id`, `notification_preferences_hidden_roles`). Existing JSONB shapes preserved per-spec so no data migration was required — the `default_sales_rep_id` keeps `{"user_id": "<uuid>"}`, `drive_time_fallback_minutes` keeps `{"minutes": <int>}`, etc.

   `legal_service`, `google_maps_service`, `lead_routing_service`, `notification_preferences_service` all migrated to `get_typed(db, key)`. Raw `select(AppConfig.value).where(AppConfig.key == ...)` removed from those four sites. Phase 4 admin form for global variables iterates `all_specs()` and writes through `set_typed()` so per-key validators run on every write. The YAML-seed loader (planned Phase 4 per ADR-016 #7) MUST also call `set_typed()` so YAML and UI enforce the same schema.

3. **Inspection prompt + red-flag rule versioning shipped (migration 014).** Both tables gained `version` (int, default 1) and `replaced_at` (nullable timestamptz). Edits via `category_versioning_service.supersede_*` insert a new row with `version + 1` and flip `replaced_at` on the old. `replaced_at IS NULL` = current; partial index keeps the "current rows for this category" lookup a single seek.

   `AppraisalSubmission.field_values` and `.red_flags` JSONB shapes gained docstring updates: writers MUST embed the version that was answered (`prompt_version` / `rule_version`) so Phase 7 PDF reports stay historically accurate. The legacy keyed-by-id dict shape is documented as legacy-on-read; no rows in production with that shape so no data migration was needed.

   `category_versioning_service.inspection_prompt_version_at(prompt_id, instant)` and `red_flag_rule_version_at(rule_id, instant)` provide the "what was current when this appraisal was authored" temporal query Phase 7 needs.

4. **Multi-role users (Critical #1) deferred to a follow-up PR on the same branch.** Schema (`users.role_id` → `user_roles` join table) + middleware + schemas + frontend + ~15 test fixtures all need to move atomically. Bundling it into the prework PR would have inflated the diff to 50+ files; splitting keeps Commits 1–2 narrowly reviewable. The follow-up PR ships the join table, `User.roles` relationship, `require_roles()` intersection check, `CurrentUser.roles` schema (with `primary_role` for back-compat), frontend `Layout.tsx` update, and seeder fixture rewrites.

5. **Notification template registry (Critical #2) deferred to Phase 4 proper.** Inline composers in `equipment_status_service`, `routers/record_locks`, `auth_service` each have a small enough surface area that the natural extraction lives next to Phase 4's "edit email copy" admin feature. Documented as a Phase 4 pre-flight item; will use the same registry shape as the AppConfig registry (KeySpec/all_specs/get/set) so admin UI patterns stay consistent.

### Consequences

- Migrations 013 + 014 land additive + reversible. Health check expected migration head bumps to `014`.
- The runtime registry pattern (`Status` + `KeySpec`) is now established as the project's idiom for "Phase 4 admin needs to introspect this." Future debt fixes follow the same shape.
- The drift-guard test pattern (parse the migration file, assert equality with the runtime constant) is a cheap insurance policy worth replicating when migrations duplicate runtime constants — most notably the pending notification template registry will need it for the inverse direction (template registry → migration seed).
- `services/category_versioning_service.py` is the only write path for category prompt + red-flag rule edits. Phase 4 admin CRUD MUST go through it; bypassing into a raw UPDATE is a regression caught only at PDF report regeneration time months later.
- Phase 4 dev plan § Architectural Debt to Address enumerates the 12 deferred items with a one-paragraph fix sketch each, so Phase 4 sprint planning can absorb them without re-deriving the analysis.

### References

- Working branch: `phase4-prework`.
- Architectural review prompt: `docs/review-prompts.md` (the "Phase boundary debt" section).
- Implementation: `api/services/equipment_status_machine.py`, `api/services/app_config_registry.py`, `api/services/category_versioning_service.py`, migrations 013 + 014, refactors across `equipment_status_service`, `calendar_service`, `sales_service`, `change_request_service`, `equipment_service`, `legal_service`, `google_maps_service`, `lead_routing_service`, `notification_preferences_service`.
- Tests: `api/tests/unit/test_equipment_status_machine.py` (12), `api/tests/unit/test_app_config_registry.py` (15), `api/tests/integration/test_category_versioning.py` (7). Full backend gate **341/341** (was 319 + 22 new pre-work tests).
- Deferred items: `dev_plan/04_phase4_admin_panel.md` § Architectural Debt to Address.

---

## ADR-019: Phase 3 → Phase 4 Pre-work — Multi-Role Users

**Date:** 2026-04-25
**Status:** Accepted
**Deciders:** Jim Wilen

### Context

The fourth Critical item from ADR-018 (multi-role users). Split into its own PR per the prework packaging plan because the diff touches middleware, schemas, every test that flips roles, the registration path, and the frontend type — bundling it would have inflated the prework PR (#31) past reviewable size.

Phase 1's `users.role_id` FK enforced one role per user. The moment Phase 4 admin lets Jim grant a sales rep the appraiser role too (so the rep can cover field shifts), the FK breaks down. Migrating data and rewriting RBAC after Phase 4's admin UI ships costs strictly more than doing it now.

### Decisions

1. **`user_roles` join table is the live source of truth for `require_roles()`.** Migration 015 adds `(user_id, role_id, granted_at, granted_by)`, primary key `(user_id, role_id)`, indexes on both columns. ON DELETE CASCADE on user_id (drop the user → drop the grants); ON DELETE RESTRICT on role_id (don't accidentally drop a built-in role); ON DELETE SET NULL on granted_by (admin who issued the grant may leave the company).

2. **`users.role_id` is preserved as the user's *primary* role, not retired.** The primary role drives default landing-page routing in the SPA (`Layout.tsx`'s sales-vs-customer split) and the snapshot in `audit_logs.actor_role` (the role the user was acting as for that action — semantically a single string, not a set). Multi-role users have one primary + N secondary grants. Phase 4 admin "change primary role" is `set_primary_role()` — flips `users.role_id` AND inserts the join row in one operation.

3. **Mirror invariant: every `users.role_id` write also writes a `user_roles` row.** Enforced via a SQLAlchemy `before_flush` event listener in `database/models.py`. The listener catches every dirty/new User where `role_id` changed and emits an idempotent `INSERT ... ON CONFLICT DO NOTHING` against `user_roles`. Without this, raw assignments like `user.role_id = role.id` (used in 12 test files + future admin paths we haven't built yet) would silently break the invariant; the listener centralizes the enforcement so callers don't have to know.

   For raw-SQL writers (the seeders), the listener doesn't fire — those have an explicit `INSERT INTO user_roles` next to the user insert. The auth_service.register_user path also issues an explicit `user_roles_service.grant()` call after the first flush, since the User's auto-generated id isn't visible to the listener until after that flush.

4. **`CurrentUser` schema gains `roles: list[str]`; `role: str` is preserved as the primary role.** Backwards-compatible — clients that only read `role` (today: every existing call site) keep working unchanged; `Layout.tsx` updates to check the full `roles` set so a sales rep who also has the customer role still gets the sales-side shell. `useMe.ts` returns the same shape; the type lives in `web/src/api/types.ts`.

5. **`require_roles(*slugs)` checks set intersection.** A user passes if at least one of their granted roles is in the allowed set. Reads through `user_roles_service.role_slugs_for_user()` so the join table is the single read path; eliminates the prior `select(Role)` join that only saw the primary role.

6. **`revoke()` refuses to remove the primary role.** The mirror invariant requires `users.role_id` to have a corresponding `user_roles` row; revoking the primary would break it. Phase 4 admin's "change primary role" flow is `set_primary_role()` — flips primary AND ensures the join row exists, so the prior primary stays grantable as a secondary.

### Consequences

- Migration 015 adds the table + backfills every existing user's primary role into a `user_roles` row in the same transaction. Production rollout is one-step; no data migration sequencing required.
- Health check expected migration head bumps to `015`.
- The mirror invariant + before_flush listener mean Phase 4 admin's "grant role" UI is a one-call-to-`grant()` operation; it doesn't have to think about the primary-vs-secondary distinction.
- Tests that flip `user.role_id` directly (12 files, ~12 sites) keep working unchanged thanks to the listener — no test refactor needed for this PR.
- `notification_jobs.actor_role` and `audit_logs.actor_role` continue to hold a single role string (snapshot of the role the user was acting as for that request). Phase 4 may add an `acting_as` UI control that lets a multi-role user explicitly pick which role the action audits as; for now the primary role is the snapshot.

### References

- Working branch: `phase4-prework-multirole` (off `phase4-prework`).
- Implementation: `api/alembic/versions/015_phase4_prework_multirole_users.py`, `api/database/models.py` (UserRole + User.roles + User.role_grants + before_flush mirror listener), `api/services/user_roles_service.py` (grant / revoke / set_primary_role / role_slugs_for_user), `api/middleware/rbac.py` (intersection check), `api/routers/auth.py` (CurrentUser.roles populated via the service), `api/schemas/auth.py` (CurrentUser.roles field), `api/services/auth_service.py` (registration grants customer role explicitly), `web/src/api/types.ts` (CurrentUser.roles), `web/src/components/Layout.tsx` (sales-side check across all roles), `scripts/seed.py` + `scripts/seed_e2e_phase3.py` (raw-SQL paths write the join row).
- Tests: `tests/integration/test_rbac.py` extended with two new cases — multi-role user passes both checks; revoke refuses the primary. Full backend gate **344/344** (was 341 + 3 new RBAC tests).
- Phase 4 admin user-management UI now plugs into `user_roles_service.grant()` / `revoke()` / `set_primary_role()` rather than inventing its own write path.
