# Phase 3 Status Report — Sales CRM, Lead Routing & Shared Calendar

**Branch:** `phase3-sales-crm` (cut from `main` at commit `a42ad7b` on 2026-04-24)
**Phase spec:** `dev_plan/03_phase3_sales_crm.md`
**Started:** 2026-04-24

---

## Sprint 1 — Record Locking + Duplicate Change-Request Guard

**Completed:** 2026-04-24
**Scope:** Epic 3.5 (Record Locking, manager override) + Phase 2 Sprint 3 carry-over (duplicate change-request guard).

### Built

| Layer | File | Notes |
|---|---|---|
| Migration | `api/alembic/versions/009_phase3_change_request_resolution_and_uniqueness.py` | Adds `change_requests.resolved_by`; partial UNIQUE index forcing one pending per record. |
| Model | `api/database/models.py` (ChangeRequest) | `resolved_by` FK column. |
| Service | `api/services/record_lock_service.py` | POC impl — unique-constraint-as-primitive, 15-min TTL, self-heal stale rows. Redis-swap stable. |
| Schema | `api/schemas/record_lock.py` | `LockAcquireRequest`, `LockInfoOut`, `LockConflictOut`. |
| Router | `api/routers/record_locks.py` | POST acquire · PUT heartbeat · DELETE release · DELETE override. Audit every state transition. |
| Service fix | `api/services/change_request_service.py` | Catch `IntegrityError` on duplicate pending → 409. |
| Infra | `api/main.py`, `api/routers/health.py` | Wire router, bump `_EXPECTED_MIGRATION_HEAD` → `"009"`. |

### Key decisions

1. **Postgres unique constraint is the lock's atomic primitive.** ADR-002 offered `pg_try_advisory_lock` as the acquire mechanism; we chose the table's UNIQUE constraint on `(record_id, record_type)` instead. Simpler code, visible in `psql`, and the unique index guarantees at-most-one active lock row. Advisory locks are session-scoped and would muddy forensic SQL.
2. **Release deletes the row.** The `overridden_by` / `overridden_at` columns on the Phase 1 `record_locks` schema go unused in the POC — the audit trail lives in `audit_logs`. Keeping them in the schema is harmless and documents intent; dropping them is future scope only if we rewrite.
3. **One-pending-per-record enforced at the DB, not just the service.** The partial unique index means the rule can't be violated from any callsite (direct SQL, seed script, future sales endpoint). The service-layer 409 is just the translation.
4. **Redis-swap contract locked in.** The service exports four functions with stable signatures: `acquire(record_id, record_type, user_id) → LockInfo`, `heartbeat(...) → LockInfo`, `release(...) → bool`, `override(...) → LockInfo | None`. Every test hits only these. Swapping the bodies to `SET NX PX 900000` + `PEXPIRE` at GCP migration keeps every caller green. Noted as a Phase 3 addendum to ADR-013 (to be committed when Sprint 3's round-robin lands the same pattern).

### Tests added (12)

- `test_record_locks.py` (10): acquire happy + audit, 409 with locked_by body, same-user refresh, replaces expired lock from other user, heartbeat refresh, heartbeat 404 (no lock / non-owner), release (owner deletes, idempotent on missing), manager override (happy + audit + prior-holder info in before_state), customer forbidden from override (403), cross-record isolation.
- `test_change_requests.py` (2): second pending request on same record → 409 with "already pending" copy; new request accepted after first is resolved (partial index only binds pending rows).

### Test results

- `make test-api`: **209/209 passed, 95.86% coverage** (85% floor).
- No prior tests regressed (Phase 2 baseline was 195/195).

### Bugs found + fixed

None introduced; the duplicate-change-request guard was carry-over from Phase 2's known-issues list (now closed).

### Open follow-ups for later sprints

- **Expired-lock sweeping**: Sprint 1 self-heals a stale lock on the next acquire. Scale-out via `fn_sweep_retention()` (extend in Sprint 3 or 4 migration) — not urgent at POC volume.
- **Sales dashboard lock integration** (Sprint 2): the `/sales/equipment/{id}` detail page must acquire on open, heartbeat every 60s, release on close / navigation.
- **No new manual tasks** for Jim — zero new secrets, DNS records, or third-party setups required this sprint.

### Next

- **Sprint 2 — Sales Dashboard + Record View + Cascade + Manual Publish + Change-Request Resolution.** Starts after this close-out commit lands.

---

## Sprint 2 — Sales Dashboard + Record View + Cascade + Manual Publish + Change-Request Resolution

**Completed:** 2026-04-24
**Scope:** Epic 3.1 + 3.2 + 3.3 + 3.6 + parts of Epic 3.7 in `dev_plan/03_phase3_sales_crm.md`.

### Built

| Layer | File | Notes |
|---|---|---|
| Schema | `api/schemas/sales.py` | All Sales request/response shapes. `AssignmentPatch` uses `model_fields_set` so "unset" and "null" are distinguishable. |
| Service | `api/services/sales_service.py` | `list_dashboard`, `get_record_detail`, `ensure_lock_held`, `apply_assignment`, `cascade_assignment`, `publish_record`. Publish validates status + signed contract + appraisal report and upserts `PublicListing`. |
| Service | `api/services/change_request_service.py` | New `resolve_change_request`. Withdraw-resolve flips record to `withdrawn`. Customer resolution email via NotificationService (idempotency key per-id/status). |
| Router | `api/routers/sales.py` | `GET /sales/dashboard`, `GET /sales/equipment/{id}`, `PATCH /sales/equipment/{id}`, `PATCH /sales/customers/{id}/cascade-assignments`, `POST /sales/equipment/{id}/publish`, `PATCH /sales/change-requests/{id}`. All behind `require_roles("sales","sales_manager","admin")`. |
| Router | `api/main.py` | Wires `sales_router`. |
| Frontend API | `web/src/api/sales.ts`, `web/src/api/types.ts` | Typed wrappers + Phase 3 types. |
| Hook | `web/src/hooks/useRecordLock.ts` | Acquire on mount, heartbeat every 60s, release on unmount; exposes LockState for UI. |
| Component | `web/src/components/CascadeAssignModal.tsx` | Bulk reassignment UI for a customer's `new_request` rows. |
| Component | `web/src/components/RecordLockIndicator.tsx` | Banner states — acquiring, held, expired, conflict (manager override), error. |
| Component | `web/src/components/PhoneLink.tsx` | `tel:` helper. |
| Component | `web/src/components/Layout.tsx` | Sales-side nav for `sales / sales_manager / admin`. |
| Component | `web/src/components/ui/StatusBadge.tsx` | Added Phase 3 statuses. |
| Page | `web/src/pages/SalesDashboard.tsx` | Grouped-by-customer; scope toggle (mine / all) for managers; cascade button per group. |
| Page | `web/src/pages/SalesEquipmentDetail.tsx` | Lock-aware detail view. Assignment form disabled unless lock held. PublishCard gated on status + contract + appraisal. Inline change-request resolver. |
| Routes | `web/src/App.tsx` | `/sales`, `/sales/equipment/:id` — `ProtectedRoute + Layout`. |

### Key decisions

1. **Lock required for PATCH assignment.** `ensure_lock_held()` in the service layer; UI acquires on mount via `useRecordLock`. 409 if no lock — renders the conflict banner with manager-override button (sales_manager / admin only).
2. **Cascade only touches `status='new_request'` rows.** Later-status rows are returned in `skipped_record_ids` + `skipped_reason` so the modal surfaces what was left alone. Protects against cascading backwards through a rep's late-stage work.
3. **Publish transitions to `listed`**, not `published`. Matches the code vocabulary already in `equipment_status_service._CUSTOMER_EMAIL_STATUSES`. Record must be in `esigned_pending_publish` with signed `ConsignmentContract` + ≥1 `AppraisalReport`. Missing gates render in the PublishCard.
4. **Withdraw-on-resolve** — resolving a `withdraw`-type change request calls `record_transition(to_status='withdrawn')`. All other resolve paths leave record status untouched. Rejection never changes record status.
5. **Cross-record reads** are open to any `sales / sales_manager / admin`. Dashboard listing is scoped by default to `assigned_sales_rep_id == caller`; managers flip to `scope=all` in the UI.
6. **Patch semantics preserve nullability.** `AssignmentPatch` relies on `model_fields_set` so a body of `{"assigned_appraiser_id": null}` clears an assignment, while absence of the field leaves it untouched.

### Tests added (26)

- `test_sales_dashboard.py` (6): scope=mine hides other-rep records; scope=all exposes everything for managers; customer grouping preserves submission order; submission_at rollup; cross-role 403; status filter.
- `test_sales_assignment.py` (5): PATCH with held lock succeeds + audits; PATCH without lock 409; explicit null clears assignment; no-op patch 422; cascading side effects (notification to new rep).
- `test_cascade_assignment.py` (4): cascade updates only `new_request`; skipped records returned with reason; partial patches (rep only / appraiser only); scope-manager path.
- `test_manual_publish.py` (5): happy path transitions to `listed` + creates PublicListing; wrong status 409; missing signed contract 409; missing appraisal 409; re-publish upserts PublicListing.
- `test_change_request_resolution.py` (6): resolve + email enqueued; reject no status change; withdraw-resolve flips record to `withdrawn`; already-resolved 409; cross-role 403; idempotent email key.

### Test results

- `make test-api`: **235/235 passed, 96.16% coverage** (85% floor).
- Frontend: `npm run build` clean, `npm run lint` clean.

### Bugs found + fixed

- Frontend lint tripped on a leftover `// eslint-disable-next-line no-console` directive — removed; the base config already tolerates `console.warn`.

### Open follow-ups for later sprints

- **User pickers for sales_rep / appraiser.** Today the CascadeAssignModal + assignment form take raw UUIDs. Phase 4 (Admin Panel) ships the searchable picker component. No blocker for Phase 3; reps can paste IDs for dogfooding.
- **Lead routing wiring.** Sprint 3 introduces the routing engine; the new-record email fan-out to the assigned rep already lands via NotificationService once the `assigned_sales_rep_id` is written.
- **Lock sweep.** Still covered by the fresh-acquire self-heal. `fn_sweep_retention()` extension deferred until POC volume demands it.

### Next

- **Sprint 3 — Lead Routing Engine.** Ad-hoc → geographic → round-robin. Builds on the AssignmentPatch surface this sprint shipped.

---

## Sprint 3 — Lead Routing Engine + Admin API + Assignment Notifications

**Closed: 2026-04-25** — backend complete, all tests green, branch `phase3-sales-crm` (one commit on top of Sprint 2's `5b04e49`).

**Scope:** Epic 3.3 (Features 3.3.1 ad-hoc, 3.3.2 geographic, 3.3.3 round-robin) plus the admin CRUD API for routing rules and the assignment-notification email path. Metro-area routing deferred to Sprint 4 with the calendar/geocoding work.

### What landed

**Routing waterfall (`api/services/lead_routing_service.py`).** Single public entry `route_for_record(db, *, record, customer)` returns `RoutingDecision(assigned_user_id, rule_id, rule_type, trigger)`. Order: ad-hoc match (customer_id or email_domain, first match wins) → geographic (state_list / zip_list with exact + range, ascending priority) → round-robin (lowest-priority active RR rule, atomic counter) → AppConfig `default_sales_rep_id` fallback → unassigned. The matchers are pure functions; the counter and AppConfig reads are the only DB-touching helpers.

**Atomic round-robin without Redis.** `_claim_next_round_robin` issues `UPDATE lead_routing_rules SET round_robin_index = round_robin_index + 1 WHERE id = :id RETURNING round_robin_index` and selects `rep_ids[(returned_index - 1) % len(rep_ids)]`. Postgres row lock serializes concurrent intakes. Tested end-to-end (`test_round_robin_cycles_through_reps` — three intakes assign a, b, a; counter reads 3). Documented as part of **ADR-014**: same semantics as Redis `INCR`; swap-path preserved for the GCP migration.

**Routing hook in customer intake.** `equipment_service.submit_intake` calls `_route_and_assign` after `db.flush() + db.refresh()`. The whole call is wrapped in `try/except Exception` — any crash logs `lead_routing_failed` and leaves the record unassigned (intake is **never** blocked on a routing fault). An `equipment_record.routed` audit row is written in every branch (`trigger ∈ {lead_routing, default_sales_rep, unassigned}`), so managers always have forensic context for an unassigned record.

**Assignment notifications, single chokepoint.** New `equipment_service.enqueue_assignment_notification(db, *, record, assigned_user_id, trigger)` is the only place `record_assigned` emails are queued. Idempotency key `record_assigned:{record_id}:{user_id}:{trigger}` — distinct triggers don't collide, so an auto-route + manual reassignment correctly sends two emails (rep gets one when the record lands, another when ownership changes). `sales_service.apply_assignment` (Sprint 2) now invokes this with `trigger="manual_override"` only on a real change.

**Admin CRUD API (`api/routers/admin_routing.py`).** `/admin/routing-rules` GET/POST/PATCH/DELETE behind `require_roles("admin")` only — sales managers cannot author rules. Schemas in `schemas/routing.py` use `RoutingRulePatch.extra="forbid"` and `model_fields_set` so explicit `null` clears `assigned_user_id` while a missing field leaves it alone. Service-level validation (`_validate_conditions`) rejects malformed bodies per rule_type with 422; `_require_sales_role` enforces that `assigned_user_id` resolves to `sales / sales_manager / admin`. DELETE is soft (sets `deleted_at` + flips `is_active=false`); `?include_deleted=true` is the forensic escape hatch.

**Migration 010.** Adds `lead_routing_rules.created_by` (FK users, nullable for seeded rules), `created_at` (server_default now()), `deleted_at`. Creates partial index `ix_lead_routing_rules_active ON (priority) WHERE deleted_at IS NULL AND is_active = true` to keep the waterfall query lean as the rule set grows. Health check `_EXPECTED_MIGRATION_HEAD` bumped to `"010"`.

### Test results

- `make test-api`: **269/269 passed** (≥85% coverage floor maintained).
- New test files:
  - `tests/unit/test_lead_routing_service.py` — 16 tests on the matchers (ad_hoc / geo / zip helpers / round-robin parsing / `_normalize_zip` parametric).
  - `tests/integration/test_lead_routing.py` — 11 tests through the real intake endpoint: ad_hoc by customer_id (assignment + audit + notification), ad_hoc by email_domain, geographic by state, geographic by zip range, ad_hoc precedence over geographic, round-robin cycling with counter assertion, AppConfig fallback (`trigger='default_sales_rep'`), unassigned trail, routing failure does not block intake (RuntimeError mocked), soft-deleted rule excluded, inactive rule excluded.
  - `tests/integration/test_admin_routing_rules.py` — 7 tests: admin POST 201 + `created_by` captured, sales_manager 403, round_robin requires non-empty `rep_ids` (422), assigned_user must have sales role (422 against customer-role user), sparse PATCH preserves untouched fields, explicit-null PATCH clears `assigned_user_id`, DELETE soft-deletes (row preserved, excluded by default, surfaced via `?include_deleted=true`).

### Bugs found + fixed

- **SQLAlchemy identity-map masked the round-robin counter assertion.** The atomic `UPDATE … RETURNING` runs through raw SQL via `text(...)`; re-querying `LeadRoutingRule` returned the cached instance with a stale `round_robin_index`. Fixed in the test by selecting the column scalar (`select(LeadRoutingRule.round_robin_index).where(...)`) which bypasses the identity map. The production code path was always correct — `_claim_next_round_robin` reads the counter from the `RETURNING` clause directly.

### Open follow-ups for later sprints

- **Admin UI** for rule CRUD — Phase 4 ships the React pages over the API delivered this sprint. The schemas and validation are stable; the UI is purely additive.
- **Metro-area geographic matching** (`condition.metro_area = {center_lat, center_lon, radius_miles}`) — Sprint 4 once Google geocoding lands. Today the matcher silently skips `metro_area` keys (`test_geo_skips_metro_area_silently`).
- **`default_sales_rep_id` AppConfig key** — intentionally unset; admin chooses one via Phase 4's settings UI. Until then, dev/staging intakes with no matching rule produce `trigger='unassigned'` audit rows by design.
- **iOS push assignment notifications** — Phase 5 alongside email; both will route through `enqueue_assignment_notification` so idempotency stays consistent.

### Next

- **Sprint 4 — Scheduling + Shared Calendar + Drive-Time + Metro-Area Routing.** Calendar events, appraiser availability, drive-time buffers via Google Distance Matrix, and the metro-area routing rules that drop into the existing waterfall.

---

## Sprint 4 — Shared Calendar, Scheduling, Drive-Time, Metro-Area Routing

**Closed: 2026-04-25** — backend exhaustively tested (291/291 backend tests green); frontend type-checks + lints clean and builds without errors but was **not** interactively browser-verified this sprint (deferred to Sprint 6 Playwright gate).

**Scope:** Epic 3.4 in full (Features 3.4.1 calendar view, 3.4.2 schedule + atomic conflict, 3.4.3 Google Maps drive-time buffer, 3.4.4 edit/cancel) plus Sprint 3's deferred metro-area routing matcher.

### What landed

**Postgres-backed caches (`migration 011`).** Two new tables — `drive_time_cache` (composite PK on origin/dest hashes, 6h TTL) and `geocode_cache` (address_hash PK, 30d TTL) — both indexed on `expires_at` for the retention sweeper. Seeds `AppConfig.drive_time_fallback_minutes = 60`. Same Redis-swap contract pattern as record locks (ADR-013) and the round-robin counter (ADR-014); GCP migration drops in `SETEX` without touching the public `services/google_maps_service.py` surface.

**Google Maps integration that works without a key (`services/google_maps_service.py`).** Distance Matrix + Geocoding clients with read-through cache. SHA-256 of lowercased + stripped string is the cache key. **Returns `None` on every failure mode and never raises** — no API key, network timeout, non-OK status, malformed body all collapse to the same sentinel. Callers treat `None` as "use the AppConfig fallback minutes" (calendar) or "this rule does not match" (metro-area routing). Tests run end-to-end without a key; httpx is mocked at the transport layer so live API calls never happen in CI.

**Calendar service with atomic conflict detection (`services/calendar_service.py`).** `list_events`, `create_event`, `update_event`, `cancel_event`. Conflict path opens `SELECT … FOR UPDATE` over the appraiser's same-day events; concurrent schedule attempts serialize on the row lock. Drive-time buffer applied either side: real Distance Matrix call (cached) → fallback minutes when unavailable. Returns a `CalendarConflict` dataclass on collision; the router maps it to a 409 with structured body `{detail, next_available_at, conflicting_event_id}` so the UI can offer a one-click reschedule. Status transitions go through `equipment_status_service.record_transition` (`new_request → appraisal_scheduled` on create, revert on cancel). Every mutation writes an audit row with `actor_role` so manager / admin can review sales-rep changes after the fact.

**Three new notification templates.** `appraisal_scheduled_appraiser`, `appraisal_cancelled_appraiser`, `appraisal_cancelled_customer`. Idempotency keys keyed on `event_id`, distinct from the customer-side `status_appraisal_scheduled` (which fires from `record_transition` for free, Phase 2 chokepoint). All four route through `notification_service.enqueue` so Phase 5's iOS push channel can drop in alongside email without touching the call sites.

**Metro-area routing carry-forward (`lead_routing_service._metro_matches`).** New rule shape `{"metro_area": {"center_lat", "center_lon", "radius_miles"}}` slots into the existing geographic loop **after** the state/zip matchers. The matcher builds a single-string address from `customer.address_street + city + state + zip`, geocodes via the cached `google_maps_service.geocode`, and computes haversine distance in statute miles. Falls through silently when geocode returns `None`. `_validate_conditions` extended to accept metro_area as a valid geographic-rule shape with type/positive-radius checks.

**HTTP surface (`routers/calendar.py`).** GET / POST / PATCH / DELETE `/calendar/events` behind `require_roles("sales", "sales_manager", "admin")` per spec line 179 (sales role can author edits; audit captures who). `_hydrate_event` re-fetches with explicit `selectinload` chain so serialization never lazy-loads outside a greenlet — same trap Phase 2 hit on intake photos.

**Frontend (`react-big-calendar` skinned to match Tailwind).** New `/sales/calendar` page with month / week / day views. Eight-tone appraiser color palette via `eventPropGetter`, cycles for >8 appraisers. Multi-select filter chips with aria-pressed; click event → record detail. New `ScheduleAppraisalModal` component wired from the `SalesEquipmentDetail` page for `new_request` records — gated behind the existing record lock; renders the 409 conflict with `next_available_at` in local time. New nav link in `Layout.tsx`. Build clean, lint zero warnings.

### Test results

- `make test-api`: **291/291 passed** (≥85% coverage floor maintained).
- New test files:
  - `tests/integration/test_google_maps_service.py` — 10 tests covering both APIs end-to-end with httpx mocks: no-key fallback, blank inputs, cache hit on second call (verified by counting calls), HTTP error → None, non-OK Google status → None, falls back to `duration` when `duration_in_traffic` absent, geocode case-insensitive cache hit, ZERO_RESULTS handled, AppConfig fallback minutes returns seeded 60.
  - `tests/integration/test_calendar.py` — 10 tests: create happy path with status transition + audit + appraiser email + customer email, non-appraiser rejected, schedule blocked when not in `new_request`, overlapping event 409 with structured body, drive-time buffer blocks via fallback path, different appraisers don't conflict, PATCH reschedule re-runs conflict check, cancel reverts status + dual emails, list filters by appraiser + window, customer 403.
  - `tests/integration/test_lead_routing.py` (extended) — 2 metro-area tests: assigned when geocode places customer in radius (mocked at 5 mi from Atlanta center), unassigned when geocode is far (Boise outside Atlanta radius).
- Frontend: `tsc -b && vite build` clean (1286 modules, 460 KB main JS); `eslint` zero warnings.

### Bugs found + fixed

- **Greenlet-less lazy-load on calendar event serialization.** Initial router fetched the persisted event then walked `event.equipment_record.customer` without `selectinload` chain — exact trap Phase 2 hit on intake photos. Fixed via `_hydrate_event` helper that re-fetches with explicit eager-load.
- **`httpx.Response.raise_for_status` needs an attached request.** Test mocks initially constructed `httpx.Response(200, json=…)` directly; calling `raise_for_status()` on that errored. Fix: attach `httpx.Request("GET", url)` in every fake.

### Open follow-ups for later sprints

- **Google Maps API key provisioning** — full Cloud Console setup steps and cost expectation captured in `known-issues.md` (free credit covers ~40k calls / month; our POC volume is 3-4 orders of magnitude under). Until provisioned, drive-time math uses the 60-min fallback and metro-area rules silently no-op. Direct overlap conflicts still work without a key.
- **Searchable appraiser / sales-rep / customer pickers** — Phase 4 (Admin Panel) ships the picker; the schedule modal takes raw UUIDs today. Acceptable for dogfooding.
- **Cache retention sweep** — `drive_time_cache` + `geocode_cache` rows accumulate until manually cleaned. Next migration that touches `fn_sweep_retention()` should add both. Not urgent at POC volume.
- **Interactive browser verification** — calendar UI was not exercised in a browser this sprint. Type-check + build + lint all green; behavioral verification is the Sprint 6 Playwright + axe + Lighthouse gate's job.

### Next

- **Sprint 5 — Automated workflow notifications + per-employee notification-preference UI (Epic 3.2).** Manager approval emails (3.2.1), eSign completion emails (3.2.2). Plus the per-user notification-preference page that lets sales reps opt out of specific notification types.
- **Sprint 6 — Phase 3 Gate.** Playwright E2E for the calendar + sales detail flows; axe-core accessibility checks; Lighthouse ≥ 90.

