# Phase 4 — Admin Panel — Sprint Status Report

Branch: `phase4-admin` (off main 2026-04-26)
Plan: `~/.claude/plans/concurrent-humming-rabbit.md`

---

## Sprint 1 — Admin shell + global operations + reports stub + manual transition
COMPLETE 2026-04-26

### What was built
- `api/routers/admin.py` (NEW, 203 lines) — `/admin/operations`, `/admin/operations/export.csv`, `/admin/equipment/{id}/transition`, `/admin/reports`. Admin-only RBAC except `/admin/reports` which also accepts the `reporting` role.
- `api/services/admin_operations_service.py` (NEW, ~280 lines) — listing + filters (status, assignee, customer, overdue) + sort + pagination + CSV serializer.
- `api/services/equipment_status_service.py` (modify) — `record_transition()` accepts `notify_override: bool | None` so the admin override modal can force notifications on or off independent of the registry default.
- `api/schemas/admin.py` (NEW) — request/response shapes.
- `api/main.py` — register the new admin router.
- `web/src/pages/AdminOperations.tsx` (NEW) — table + filters + CSV button + per-row Transition action; auto-refresh every 2 minutes.
- `web/src/components/admin/ManualTransitionModal.tsx` (NEW) — destination dropdown over the 11 Status enum values (mirrored from `equipment_status_machine`), required reason, notify toggle.
- `web/src/pages/AdminReports.tsx` (NEW) — placeholder with the 4 sub-tabs from Feature 4.7.1.
- `web/src/components/Layout.tsx` — split nav into admin / reporting / sales / customer branches; admin no longer falls through to sales.
- `web/src/App.tsx` — register `/admin/operations` + `/admin/reports`; bare `/admin` redirects to operations.
- `web/src/api/admin.ts` (NEW) + `web/src/api/types.ts` (extend) — typed client.

### Key design decisions
1. **`notify_override` semantics:** `None` follows the registry; explicit `True/False` overrides both customer + sales-rep dispatches. Lets admin back-fill silently or force-notify on internal-only transitions.
2. **Audit trail split:** `record_transition()` writes the `StatusEvent` (timeline). The admin endpoint additionally writes an `AuditLog` row with `event_type=equipment_record.status_admin_override`, `actor_role=admin`, the reason, and the dispatch flag — so the timeline alone can't disguise an admin override as a regular sales-rep transition.
3. **Days-in-status anchor:** the latest `StatusEvent.created_at` for the record (falls back to `record.created_at`). NOT `equipment_records.updated_at` — a Postgres trigger (`set_updated_at`) auto-bumps that on every UPDATE, so it can't anchor staleness.
4. **Overdue SQL filter:** correlated subquery `coalesce(MAX(status_events.created_at WHERE rec_id), records.created_at) < cutoff`. Replaces an early `updated_at < cutoff` cut that proved incorrect for the same trigger reason.
5. **Status list on the modal:** hard-coded mirror of the `Status` StrEnum. Sprint 3 will swap for a fetch from the AppConfig metadata endpoint so admins don't need a redeploy when the registry changes.
6. **Reports stub:** wires the `reporting` role end-to-end now; Phase 8 fills the four tabs with real charts.
7. **Layout precedence:** admin role wins over sales (admin can do everything sales can plus more); reporting-only users get a stripped nav with one tab + Account.

### Test results
- 360 / 360 backend tests pass (was 344; +9 in `test_admin_operations.py`, +7 in `test_admin_manual_transition.py`).
- `make lint`: ruff check + ruff format + eslint all green.
- `npx tsc --noEmit`: clean.

### Bugs found and fixed during sprint
- Initial overdue prefilter used `EquipmentRecord.updated_at < cutoff` which silently never matched in tests (the `set_updated_at` trigger reverts the column on every UPDATE). Fixed by switching the predicate to a correlated MAX-StatusEvent subquery; documented inline + in the carry-forward note.
- CSV export endpoint wired the Bearer header through the JS fetch+blob path because plain `<a download>` links don't attach `Authorization`.

### Open issues / follow-ups
- `equipment_record_overdue_threshold_days` AppConfig key — tracked for Sprint 3, currently hard-coded `7` in `admin_operations_service.DEFAULT_OVERDUE_THRESHOLD_DAYS`.
- Status dropdown on the manual-transition modal duplicates the `equipment_status_machine.Status` enum; Sprint 3 swaps for a fetched metadata endpoint.
- E2E coverage (`web/e2e/phase4_admin.spec.ts`) deferred to Sprint 8 (the dedicated phase-gate sprint).
- Lighthouse on `/admin/*` deferred to Sprint 8 per the Phase 4 carry-forward issue in `known-issues.md`.

---

## Sprint 2 — Customer DB management + walk-in customers + user deactivation
COMPLETE 2026-04-26

### What was built
- **Migration 016** — `customers.user_id` becomes nullable, partial unique index `uq_customers_user_id_when_set` replaces the column-level UNIQUE so multiple NULL walk-ins can coexist. New `customers.invite_email` (String 255). CHECK `ck_customers_user_or_invite` requires one of the two. Reversible (downgrade asserts no NULL-user rows first).
- **`api/services/admin_customer_service.py`** (NEW) — `list_customers` (paginated + multi-field search across name/business/email/phone), `get_customer`, `update_customer` (audit diff), `soft_delete_customer` (cascades to equipment records), `create_walkin`, `send_walkin_invite` (BackgroundTasks). Email regex + state uppercase normalization. `_serialize(customer, *, include_records)` skips the equipment relationship when not selectinload'd to avoid MissingGreenlet in async context.
- **`api/services/admin_user_service.py`** (NEW) — `deactivate_user`. Counts open records (excludes terminal statuses) + future calendar events; refuses 409 if reassign target required + missing. Validates reassignee shares a *work role* (sales/sales_manager/admin/appraiser; `customer` doesn't count). Per-record audit + new-assignee notification fan-out.
- **`api/services/email_service.py`** — `send_walkin_invite_email` template.
- **`api/routers/admin.py`** — extended with customer CRUD + `/send-invite` + `/users/{id}/deactivate`.
- **`api/schemas/admin.py`** — `AdminCustomerOut/ListResponse/Create/Patch/EquipmentSummary`, `SendInviteResponse`, `DeactivateUserRequest/Response/OpenWork`.
- **Frontend:** `AdminCustomers.tsx` (list + search + filter chips + walk-in modal), `AdminCustomerEdit.tsx` (form + invite send + soft-delete with confirm), `web/src/api/admin.ts` extension, App.tsx + Layout.tsx wiring.
- **Tests:** 22 new (14 customer + 8 deactivation). 382/382 backend.

### Key design decisions
1. **Walk-in flow** — admin creates customer with `user_id=NULL` + `invite_email` set. Invite is a *separate explicit action* (not auto-sent on create) so admin can capture details before customer interaction. Resolved Architectural Debt #8.
2. **`_WORK_ROLES` reassignment filter** — registration auto-grants `customer` so a naïve role intersection would let any registered user inherit a sales rep's open records. Limited to `{sales, sales_manager, admin, appraiser}`.
3. **Audit per-record on deactivation** — one `equipment_record.deactivation_reassigned` AuditLog row per moved record + one `calendar_event.deactivation_reassigned` per moved event + a single summary `user.admin_deactivated`. The trail tells exactly what moved + why.
4. **Partial unique index for user_id** — replaces the column-level UNIQUE so multiple walk-ins (NULL user_id) coexist freely; the partial index `WHERE user_id IS NOT NULL` keeps the one-customer-per-registered-user invariant.
5. **`_serialize` async-safe** — explicit `include_records` flag + reload via `_load(include_records=True)` after writes that mutate relationships. Caught a MissingGreenlet during initial test run.
6. **CHECK `ck_customers_user_or_invite`** — DB-level guarantee that every customer has a way to be reached (either a user account or an invite address).
7. **UserDeactivationModal frontend deferred** — backend complete + tested. The modal needs a `/admin/users` page to live on; that page is not in Sprint 2's scope. Documented as carry-forward.

### Test results
- 382 / 382 backend tests pass (was 360; +14 in test_admin_customers, +8 in test_admin_user_deactivation).
- `make lint`: ruff + format + eslint all green.
- `npx tsc --noEmit`: clean.
- Migration 016 applied + downgraded + re-upgraded cleanly against local dev DB.

### Bugs found and fixed during sprint
- `_serialize` MissingGreenlet from accessing unloaded `equipment_records` relationship — fixed by `include_records` flag + selective reload.
- Role-overlap check accepted `customer` role because registration auto-grants it — fixed by intersecting against `_WORK_ROLES`.
- Initial overdue test from Sprint 1 mutated `record.updated_at` before realizing the DB trigger reverts it — covered in Sprint 1 status report; mention here only because it informed the Sprint 2 design (no pattern of trying to backdate `updated_at`).

### Open issues / follow-ups
- **UserDeactivationModal UI** — backend ready; UI lands when there's an admin-users page (likely Sprint 4 or 7).
- Customer profile auto-creation on first /me/equipment intake remains; the new walk-in path is alternative, not replacement.
- Sprint 4 should consider exposing the AppConfig "default sales rep" key visibility on the customer record so admin can override per-customer routing without going to /admin/config.
