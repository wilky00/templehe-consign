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

