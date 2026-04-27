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

---

## Sprint 3 — AppConfig admin UI + iOS config endpoint + RO roles key
COMPLETE 2026-04-26

### What was built
- **7 new AppConfig KeySpecs** in `api/services/app_config_registry.py`: `intake_fields_visible`, `intake_fields_order`, `consignment_price_change_threshold_pct`, `calendar_buffer_minutes_default`, `security_session_ttl_minutes`, `notification_preferences_read_only_roles`, `equipment_record_overdue_threshold_days`. Each has a per-key validator (range checks for ints; canonical-field membership for intake fields) so bad payloads surface as 422 inline.
- **Constants → AppConfig**: `notification_preferences_service.is_read_only_for_role()` is now async + reads from `notification_preferences_read_only_roles` (resolves Architectural Debt #2). `admin_operations_service` has a new `_resolve_overdue_threshold(db, override)` so production reads from `equipment_record_overdue_threshold_days` while tests can still pin.
- **`api/services/intake_visibility_service.py`** (NEW) — `visible_fields(db)` + `field_order(db)` reading the AppConfig keys; admin-ordered fields render first, then canonical tail.
- **`GET /me/equipment/form-config`** — extends the existing customer equipment router. Returns `{visible_fields, field_order}` for the customer intake page.
- **`api/routers/admin_config.py`** (NEW) — `GET /admin/config` returns every KeySpec + live value sorted by `(category, name)`; `PATCH /admin/config/{key}` runs validator → 422 on ValueError, 404 on unknown key. Admin-only RBAC.
- **`api/routers/ios_config.py`** (NEW) — `GET /api/v1/ios/config` returns `{config_version, categories, components, inspection_prompts (current/active), red_flag_rules (current/active), app_config[]}`. SHA-256 over the body with deterministic JSON encoding (`sort_keys=True`, `separators=(",",":")`); same input always hashes to the same hex string. Locked to appraiser/admin/sales/sales_manager.
- **Frontend:** `AdminConfig.tsx` (per-category cards, per-key Save with optimistic refresh + inline ApiError); `ConfigField.tsx` type-driven renderer (string/int/uuid/list[string]); `/admin/config` route; Config tab in admin nav.
- **Tests:** 8 in `test_admin_config.py`, 6 in `test_ios_config.py`, 3 in `test_intake_visibility.py`. 399/399 backend.

### Key design decisions
1. **AppConfig read at request time** — no in-process cache. Org's scale makes the SELECT cost trivial; cache adds invalidation complexity. Revisit if a perf budget surfaces.
2. **Hash-based iOS cache** — deterministic SHA-256 over the body avoids both timestamps and ETags. Phase 5 iOS code: cache the body + hash, on launch fetch the hash, refetch full body iff hash differs.
3. **Intake field visibility = denylist by absence** — `intake_fields_visible` defaults to all canonical fields; admin removes a field by editing the list. The canonical tuple lives next to the spec so a code reader can see the universe.
4. **Reorder semantics** — admin's order applies to fields in the list; unmentioned canonical fields render at the bottom in canonical order. Drops unknown slugs (typo guard).
5. **Per-key 422 with validator's message** — surface goes straight to the admin form's Alert, no schema-level validation guesswork.
6. **`security_session_ttl_minutes` registered but not consumed yet** — Phase 5+ wires it into `auth_service.create_access_token`. Registering early lets admin see the knob.
7. **iOS endpoint NOT customer-accessible** — bundle leaks all categories + AppConfig values; cheap RBAC scoping prevents accidental leakage if a customer-facing component starts calling `/ios/config`.
8. **`is_read_only_for_role` made async** — both call sites in `me_notifications.py` updated; no downstream sync paths broken.

### Test results
- 399 / 399 backend tests pass (was 382; +8 admin_config + 6 ios_config + 3 intake_visibility).
- `make lint`: ruff + format + eslint all green.
- `npx tsc --noEmit`: clean.

### Bugs found and fixed during sprint
- iOS-config draft assumed `CategoryComponent.weight` — the actual field is `weight_pct` (Numeric). Switched to `weight_pct` and stringified for stable JSON encoding (Decimal isn't JSON-serializable; the body is hashed so encoding has to be deterministic).
- `is_read_only_for_role` sync→async required updating both call sites in `me_notifications.py` (now `await ... is_read_only_for_role(db, role_slug=role)`).

### Open issues / follow-ups
- **Customer intake page** (`web/src/pages/IntakeForm.tsx`) doesn't yet consume `/me/equipment/form-config` — fields are still hard-coded. Backend is ready; React refactor lands in Sprint 8 or as a follow-up before phase close.
- **`security_session_ttl_minutes` consumer wiring** — one-line addition to `auth_service.create_access_token`; deferred to keep Sprint 3 scoped to registry + UI.
- **AppConfig in-process cache** — not built; revisit if dashboards show latency budget pressure.

---

## Sprint 4 — Lead routing admin UI + priority uniqueness + JSON Schema
COMPLETE 2026-04-26

### What was built
- **Migration 017** — deterministic backfill of duplicate priorities (ROW_NUMBER offset by created_at within each (rule_type, priority) bucket); partial UNIQUE INDEX `uq_lead_routing_rules_type_priority ON lead_routing_rules (rule_type, priority) WHERE deleted_at IS NULL`. Reversible.
- **`lead_routing_service.reorder_priorities`** — atomic two-phase renumber under SELECT FOR UPDATE: scratch-space negatives → final positives. Rejects partial id lists with 422 so unmentioned rules can't end up duplicating a slot.
- **`lead_routing_service.test_rule`** — read-only synthetic match. Reuses `_ad_hoc_matches` / `_geo_matches`; new `_metro_matches_synthetic` skips geocode when caller supplies lat/lng. round_robin reports next rep without claiming.
- **`lead_routing_service._check_priority_slot_free`** — pre-flight on create_rule + update_rule so the partial UNIQUE INDEX surfaces as 409 not 500.
- **`schemas/routing.py`** — discriminated-union per rule_type (`AdHocConditions`, `GeographicConditions`+`MetroArea`, `RoundRobinConditions`); `parse_conditions` dispatches by rule_type. Service `_validate_conditions` now delegates to it. Resolves Architectural Debt #4.
- **`routers/admin_routing.py`** — `POST /reorder` and `POST /{id}/test` endpoints. Admin-only.
- **Frontend:** `AdminRouting.tsx` (tabs per rule_type, `@dnd-kit`-driven sortable list, per-row Edit/Test/Delete), `RoutingRuleForm.tsx` (form switches per rule_type), `RoutingRuleTester.tsx` (synthetic input + result panel). `/admin/routing` route + Routing tab in admin nav. Installed `@dnd-kit/core` + `@dnd-kit/sortable` + `@dnd-kit/utilities`.

### Key design decisions
1. **Two-phase renumber, not deferrable constraint** — Postgres can't make a *partial* UNIQUE INDEX deferrable (deferrability requires a constraint, which doesn't support partial). Scratch negatives + SELECT FOR UPDATE is the canonical workaround.
2. **Partial UNIQUE INDEX (`WHERE deleted_at IS NULL`)** — soft-deleted rules don't block re-use of their priority slot; admin can deactivate then re-create at the same number.
3. **Pydantic dispatch over inline if/else** — `parse_conditions(rule_type, raw)` lives in `schemas/routing.py`, the variant models become OpenAPI types, and `service._validate_conditions` is a thin wrapper that maps `ValidationError`/`ValueError` → 422.
4. **Reorder endpoint requires complete bucket** — passing only the moved IDs would let other rules silently inherit a conflicting slot. 422 with the missing/unknown sets in the detail message.
5. **`test_rule` round_robin doesn't claim** — admin can debug rotation without polluting the `round_robin_index` counter. Different from `route_for_record` which claims atomically.
6. **@dnd-kit over alternatives** — smaller bundle, active maintenance, accessible-by-default keyboard sensors.

### Test results
- 425 / 425 backend tests pass (was 399; +15 unit routing schema + 6 test_rule + 5 reorder/uniqueness).
- `make lint`: ruff + format + eslint + tsc all green.
- Migration 017 applied + downgraded + re-upgraded cleanly against local dev DB.

### Bugs found and fixed during sprint
- IntegrityError on duplicate priority bubbled to 500. Fixed with `_check_priority_slot_free` pre-flight + clean 409.
- Naive single-pass renumber would violate the UNIQUE INDEX when row A wants row B's slot. Fixed with the negative-scratch two-phase pattern.

### Open issues / follow-ups
- Drag-reorder uses optimistic re-fetch on success; full optimistic UI with rollback-on-error is a future polish.
- Ad-hoc form's `assigned_user_id` is a free UUID input — swap to autocomplete when a user-picker exists.
- Geographic metro lat/lng entry is manual; integrate with Google Maps geocoding (Sprint 7 territory) for "type a city name".

---

## Sprint 5 — Notification template registry + cross-cutting Architectural Debt
COMPLETE 2026-04-26

Largest sprint of Phase 4. Resolves Architectural Debt items #1, #5, #6, #9, #11.

### What was built
- **Migration 018** — `equipment_record_watchers`, `calendar_event_attendees` (with backfill), `notification_template_overrides`. All cascade on parent delete.
- **`notification_templates.py`** — Jinja2-driven registry with autoescape per channel, `StrictUndefined` for loud failure on missing vars, 9 templates covering existing inline composers. `render_with_overrides(db, name, vars)` consults the overrides table; falls back to code defaults. Resolves Architectural Debt #1.
- **`lock_registry.py`** — `LockableResource` registry (type, display_name, audit_prefix, reference_loader). `record_locks` router delegates type validation + reference lookup. Resolves Architectural Debt #6.
- **`watchers_service.py`** — add/remove/list/watcher_user_ids. Idempotent ON CONFLICT. Dispatch fan-out wired into `record_transition` so watchers receive customer-facing status emails. Resolves Architectural Debt #9.
- **CalendarEvent mirror invariant** — `before_flush` listener auto-mirrors `appraiser_id` into `calendar_event_attendees` with role='primary'. New events ORM-add for FK ordering; dirty events use raw INSERT. Resolves Architectural Debt #11.
- **`unified_notification_prefs_service.py`** — read view merging `customers.communication_prefs` + `notification_preferences`. Resolves Architectural Debt #5.
- **`admin_templates.py` router** — `GET` lists every registered template + override status; `PATCH` writes/deletes the override row.
- **`admin.py` router extension** — watcher CRUD endpoints + `/users/{id}/notification-summary`.
- **Frontend:** `AdminNotificationTemplates.tsx` — per-category cards, per-template subject + body editor with variable picker chips, save/revert. `/admin/notification-templates` route + Templates nav tab.

### Key design decisions
1. **One template per (name, channel) pair** — splitting `record_lock_overridden` into email + SMS variants keeps the registry's name-as-key invariant clean.
2. **`StrictUndefined` Jinja2** — missing variables raise UndefinedError; better to fail loudly during dev.
3. **Per-channel autoescape** — HTML body autoescapes (XSS protection); SMS body doesn't (would corrupt `&` etc.).
4. **Mirror invariant uses ORM-add for new events** — raw `pg_insert` pre-flush violates parent FK because the join INSERT runs before the parent. ORM-add lets SQLAlchemy figure out FK ordering. Pre-populate `obj.id = uuid.uuid4()` so the relationship binds.
5. **Watchers get a dedicated job template name** (`status_update_watcher`) so list-by-template queries can distinguish customer vs watcher dispatches.
6. **Override deletion via `delete=true` PATCH flag** — admin's "Revert to default" path; cleaner than a separate DELETE endpoint.

### Test results
- 457 / 457 backend tests pass (was 425; +32 across 6 new test files: 12 unit + 20 integration).
- `make lint` clean (ruff + format + eslint).
- `npx tsc --noEmit` clean.
- Migration 018 applied + downgraded + re-upgraded cleanly.

### Bugs found and fixed during sprint
- Mirror-invariant FK violation on new events → ORM-add fix.
- Pre-flush `obj.id = None` → pre-populate UUID.
- SMS test asserted old template name → updated to `record_lock_overridden_sms`.

### Open issues / follow-ups
- **Multi-attendee calendar UI** — backend + mirror complete; admin schedule modal accepting multiple attendees deferred to Sprint 8.
- **Sales-side watchers section on `SalesEquipmentDetail`** — backend ready; UI deferred to Sprint 8.
- **`auth_service` inline composers** (verification, password reset) — not yet migrated to the registry; Sprint 8 cleanup since spec doesn't require admin-editable copy for those.
- **Live template preview** — current admin UI shows variable chips but no render preview. Add when admin requests it.

---

## Sprint 6 — Dynamic Equipment Category Management + Versioning + Export/Import (2026-04-27)

Epic 4.8 + Architectural Debt #10. Brings `equipment_categories` to the same versioned model as inspection prompts + red-flag rules; ships full admin CRUD + JSON export/import; surfaces a "weights don't sum to 100%" banner so admins notice scoring drift.

### What was built
- **Migration 019** — `equipment_categories.version` + `replaced_at`; replaces column-level `UNIQUE(slug)` with partial unique index `WHERE replaced_at IS NULL AND deleted_at IS NULL`. Mirrors migration 014. **Resolves Architectural Debt #10.**
- **`api/services/category_versioning_service.py`** (extend) — `current_category_by_slug` + `supersede_category(...)` mirroring the prompt + rule supersedes.
- **`api/services/admin_category_service.py`** (NEW, ~700 LoC) — full CRUD: list/get/create/update (supersede)/deactivate/soft_delete + components + inspection prompts (versioned) + red-flag rules (versioned) + attachments + photo slots; weight-warning logic (active weights must sum to 100 ± 0.5%); idempotent `import_from_payload(...)` (slug-keyed, additive merges, supersedes on body change). Hard-delete blocked when `equipment_records` reference category.
- **`api/routers/admin_categories.py`** (NEW) — full HTTP surface (~290 LoC): CRUD + sub-resource endpoints + `GET /{id}/export.json` + `POST /admin/categories/import`. Admin-only RBAC.
- **`api/schemas/admin.py`** (extend) — `CategoryOut` / `CategoryDetail` (with `weight_total` + `weight_warning`) / `CategoryListResponse` + per-child create/patch + `CategoryExportPayload` / `CategoryImportResult`. `weight_pct` constraint flipped to `lt=100` to match `Numeric(6, 4)` storage.
- **`api/routers/health.py`** — `_EXPECTED_MIGRATION_HEAD = "019"`.
- **Frontend:** `AdminCategories.tsx` (NEW, list + create modal + import modal), `AdminCategoryEdit.tsx` (NEW, header actions + 5-tab edit + rename modal), `ComponentWeightWarning.tsx` (NEW). Routes + admin nav extended. Types + API client extended.
- **`.gitleaks.toml`** (NEW) — extends defaults; allowlists `^project_notes/.*\.md$` (folded into Sprint 6 PR per Jim 2026-04-27, lands before Mon 2026-05-04 08:00 UTC scheduled run).

### Key design decisions
1. **Category supersede covers all identity-affecting edits** (rename, slug, status) — and pure `display_order` edits also supersede so the audit trail stays consistent. Single edit path beats split UPDATE-vs-supersede heuristic.
2. **Hard-delete blocked when records reference** — returns 409 with the count. Admin must deactivate (preferred — keeps history) or reassign records first. No surprise cascades.
3. **Import idempotency keys on `slug`, lowercase-trim** — components match by name; prompts + rules match by label. Body-diff drives supersede; missing items don't trigger deletes (additive merge only).
4. **`weight_warning` tolerance is 0.5%** — absorbs floating-point sums; banner explicitly notes runtime normalization so admins know nothing breaks if they ignore.
5. **Component max weight `lt=100`** — matches storage; "100% in one component" was always degenerate.

### Test results
- **104 unit + 370 integration green** (was 102 unit + 364 integration after Sprint 5; Sprint 6 added 24 new tests).
- 11 integration `test_admin_categories.py` (CRUD/duplicate-slug/rename-supersede/weight-warning/prompt-supersede/delete-blocked/delete-empty/deactivate/RBAC/partial-unique-index).
- 3 integration `test_category_export_import.py` (fresh-slug create / supersede-on-changed-prompt / idempotent re-import).
- 3 integration `test_category_versioning.py` extended (category supersede / slug lookup / deleted-skip).
- `make lint` clean (ruff + format + eslint).
- `npx tsc --noEmit` clean; `npm run build` clean.
- Migration 019 applied cleanly against staging-shape DB.

### Bugs found and fixed during sprint
- `weight_pct: float = Field(ge=0, le=100)` triggered `NumericValueOutOfRangeError` because `Numeric(6, 4)` caps at `9.9999`. Fixed schema to `lt=100`; updated tests to use multi-component splits.
- First weight-warning logic flagged empty categories as misconfigured. Suppressed when `len(active_components) == 0` — that's "not configured yet", not a problem.
- `_EXPECTED_MIGRATION_HEAD = "018"` in `routers/health.py` broke health checks the moment migration 019 ran (cascading to `test_health.py` + `test_rbac.py::test_security_headers_present` + `test_auth_flows.py::test_health_still_works`). Bumped to `"019"`.

### Open issues / follow-ups
- **Photo-slot + attachment edit UI** — backend ships; frontend lists are visible but the edit forms are stubbed to "coming with iOS work" since iOS is the primary consumer. Sprint 8 or Phase 5.
- **Component + red-flag-rule edit-in-place UI** — list + add ship; prompt edit-in-place ships (single-line label); component weight editor + rule body editor deferred to Sprint 8.
- **`_EXPECTED_MIGRATION_HEAD` follow-up** — derive head dynamically from alembic config so future migrations don't re-trip this gotcha. Sprint 8 cleanup.
- **Category-level "weights must sum to 100" validator** — current validation is per-row only; runtime scorer normalizes regardless. Sprint 8.

### Architectural Debt resolved (running tally across Phase 4)
| # | Item | Sprint |
|---|---|---|
| #1 | Notification template registry | 5 |
| #2 | RO roles via AppConfig | 3 |
| #3 | Routing priority uniqueness | 4 |
| #4 | Routing JSON Schema (discriminated union) | 4 |
| #5 | Two-prefs unified read | 5 |
| #6 | Lock registry | 5 |
| #8 | Walk-in customers | 2 |
| #9 | Watchers | 5 |
| #10 | Category versioning | **6** |
| #11 | Multi-attendee calendar | 5 |
| #16 | Inline composer side-effects → registry | 5 |

10 of 12 architectural debt items resolved (per phase plan). Remaining: #7, #12, #13, #14, #15.
