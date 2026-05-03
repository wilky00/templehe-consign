# Phase 6 Status Report — Approval & eSign

---

## Sprint 1: Scoring Engine + Red Flag Detection — COMPLETE (2026-05-02)

### What was built

| File | Action | Key change |
|---|---|---|
| `api/alembic/versions/028_phase6_approval_columns.py` | NEW | Widen `score_band` VARCHAR(20→100); add `review_notes TEXT` |
| `api/database/models.py` | Modified | `score_band` String(100); `review_notes` nullable Text |
| `api/services/scoring_service.py` | Modified | Phase 6 score band labels + thresholds; fix two `"salvage"` hardcodes to `"Insufficient data"` |
| `api/services/red_flag_service.py` | NEW | Pure `evaluate_rules()` + async `evaluate()`; `RuleSpec` + `RedFlagResult` types; `make_rule()` factory for tests |
| `api/services/notification_templates.py` | Modified | `management_review_flagged_email` + `_sms` templates |
| `api/services/appraisal_submission_service.py` | Modified | `submit()`: red flag eval + conditional manager notification; fix `User.deleted_at` → `User.status == "active"` |
| `api/tests/unit/test_scoring_service.py` | Modified | Phase 6 band label assertions; boundary tests at 3.75 and 4.50 |
| `api/tests/unit/test_red_flag_service.py` | NEW | 22 pure unit tests — all operators, all actions, multi-rule accumulation |
| `api/tests/integration/test_scoring_engine.py` | NEW | 5 integration tests via HTTP — weighted avg, perfect score, low score, recalculation, mismatched weights |
| `api/tests/integration/test_red_flags.py` | NEW | 10 integration tests — no-rule pass-through, equals match, inactive rule, marketability downgrade, hold_for_title, review_notes, manager notification |
| `api/tests/integration/test_appraisal_submissions.py` | Modified | Updated band label assertion (`"good"` → `"Strong resale candidate"`) |

### Key decisions

- `evaluate_rules()` is pure (no DB) — takes `list[RuleSpec]` + flat field dict; the async `evaluate()` wrapper loads DB rules and calls it. Keeps unit tests fast with no fixtures.
- `_extract_fields()` extracts only direct `AppraisalSubmission` columns (`running_status`, `title_status`, `hours_condition`, `marketability_rating`, `serial_number`). Rules keyed to prompt-UUID `field_values` are a Phase 6 follow-up (pending `field_key` slug on `CategoryInspectionPrompt`).
- Legacy `{"flag": "management_review"}` action key from Phase 4 seed data is supported alongside new `{"set_management_review_required": true}`.
- Manager notification filter uses `User.status == "active"` (not `User.deleted_at` — `User` has no such column).
- Test emails use `@example.com` domain (pydantic `EmailStr` rejects `.local`). All emails are unique via `_tag()` UUID suffix to survive re-runs.

### Test results

- Unit: 177/177 passed
- Integration: 497/497 passed
- Coverage: ≥86% (above 85% gate)

### Bugs found and fixed during sprint

1. `scoring_service.py` had two early-return paths that hardcoded `band="salvage"` — fixed to `"Insufficient data"` to match Phase 6 spec.
2. `test_scoring_engine.py` and `test_red_flags.py` used `db: AsyncSession` in test function signatures — pytest fixture is `db_session`. All fixed.
3. `test_red_flags.py` helpers didn't create a `Customer` before `EquipmentRecord` — `customer_id` NOT NULL violation. Fixed.
4. Inline tests in `test_red_flags.py` didn't PATCH `category_id` on the submission — `evaluate()` skips rules when `category_id is None`. Fixed.
5. `_notify_managers_review_required()` referenced `User.deleted_at` which doesn't exist on the `User` model — fixed to `User.status == "active"`.
6. `test_manager_notification_enqueued_when_review_required` needed an active `sales_manager` user to exist for the notification query to return a result — added `_seed_manager()` helper.
7. Hardcoded emails like `"noflag@test.local"` caused `NoResultFound` on re-runs if DB teardown didn't complete — switched to UUID-suffixed `@example.com` emails.

### Open issues

- `field_values` (JSONB, keyed by prompt UUID) is not yet extracted for red flag evaluation. Rules can only fire on the ~5 direct columns. Tracking in `known-issues.md`.


---

## Sprint 2: Manager Approval Workflow — COMPLETE (2026-05-02)

### What was built

| File | Action | Key change |
|---|---|---|
| `api/alembic/versions/029_phase6_approval_workflow.py` | NEW | `rejection_notes TEXT`, `approved_by_id UUID → users`, `approved_at TIMESTAMPTZ` on `appraisal_submissions` |
| `api/database/models.py` | Modified | 3 new nullable columns on `AppraisalSubmission` |
| `api/services/appraisal_submission_service.py` | Modified | `submit()` transitions `EquipmentRecord → "appraisal_complete"` via `record_transition()`; resolves customer user for notification |
| `api/services/approval_service.py` | NEW | `get_queue()`, `approve()`, `reject()` + `AuditLog` writes |
| `api/schemas/approval.py` | NEW | Queue item + decision request/response schemas |
| `api/routers/manager_approvals.py` | NEW | 4 endpoints: GET queue, GET detail, POST approve, POST reject (sales_manager + admin) |
| `api/schemas/appraisal_submission.py` | Modified | `SubmissionOut` extended with 8 new approval-related fields |
| `api/routers/appraisal_submissions.py` | Modified | `_submission_to_out()` updated for new `SubmissionOut` fields |
| `api/main.py` | Modified | Registered `manager_approvals` router |
| `api/services/notification_templates.py` | Modified | `appraisal_rejected_sales_rep_email` + `appraisal_rejected_appraiser_email` templates |
| `api/tests/integration/test_approval_workflow.py` | NEW | 12 integration tests |

### Key decisions

- `submit()` calls `equipment_status_service.record_transition()` to move the equipment record to `"appraisal_complete"`. Resolves the customer user for the customer notification email; walk-in customers with no user account have `customer_user=None` and the notification is silently skipped.
- `approve()` uses `SELECT FOR UPDATE` lock on the submission before writing. The `record_transition()` call to `"approved_pending_esign"` fires the existing `sales_rep_approved_pending_esign` email+SMS via the status machine — no new templates needed for approval.
- `hold_for_title_review` is enforced at the API layer: approving a flagged submission without `title_review_confirmed: true` returns 422.
- `reject(send_back=True)` → `EquipmentRecord.status = "new_request"` + appraiser email; `send_back=False` → `"declined"` (terminal). The assigned sales rep is notified in both cases.
- `AuditLog` is written inline in `approval_service.py` (consistent with `sales_service`, `calendar_service`).
- No per-manager queue filtering — `sales_manager` sees all `"appraisal_complete"` records, consistent with the spec ("all records for admin role" implies the manager queue is also global).

### Test results

- Unit: 177/177 passed
- Integration: 512/512 passed
- Coverage: 88% (above 85% gate)

### Bugs found and fixed during sprint

1. `NotificationJob.recipient_user_id` doesn't exist — field is `user_id`. Fixed in `test_approval_workflow.py`.

### Open issues

- Frontend approval queue page (`/manager/approvals`) is deferred to Sprint 3.
- `field_values` (JSONB, keyed by prompt UUID) is still not extracted for red flag evaluation. Carry-forward from Sprint 1.

---

## Sprint 3: Frontend Manager Approval Queue + eSign Stub + Price Change Re-approval — COMPLETE (2026-05-03)

### What was built

**Backend (eSign):**
- `api/services/signing_service.py` — `SigningService` ABC with `StubSigningService` and `get_signing_service()` factory. `StubSigningService` returns `stub-{uuid}` envelope IDs and serves HTML preview from `/esign/stub-preview/:id`.
- `api/services/esign_service.py` — `dispatch_contract()`: idempotent (no-op if contract already exists); resolves approved submission + customer user; calls `signing_service.create_envelope()`; creates `ConsignmentContract` row with status `sent`; enqueues `customer_esign_ready` email.
- `api/routers/esign.py` — Four endpoints: signing redirect, stub preview HTML page, stub sign (fires `_handle_envelope_completed`), HMAC-validated webhook. Webhook handles `envelope_completed` → `esigned_pending_publish`, `envelope_declined` → `approved_pending_esign` (no-op if already there), unknown events → 200 ignored.
- `api/config.py` — `esign_webhook_secret: str = ""` (empty = HMAC skipped for dev/test).
- `api/services/approval_service.py` — `approve()` calls `esign_service.dispatch_contract()` in a best-effort try/except after flush.

**Backend (price change re-approval):**
- `api/alembic/versions/030_phase6_change_request_price.py` — adds `proposed_consignment_price DECIMAL(12,2)` to `change_requests`.
- `api/services/price_change_service.py` — `evaluate()` reads approved submission's `suggested_consignment_price`, computes pct change, reads `consignment_price_change_threshold_pct` from AppConfig, sets `requires_manager_reapproval = True` and notifies active sales_manager users when threshold exceeded.
- `api/services/change_request_service.py` — allows `update_consignment_price` request type; calls `price_change_service.evaluate()`.
- `api/routers/manager_approvals.py` — `GET /manager/approvals/price-changes` (route placed before `/{submission_id}` to avoid FastAPI path conflict).

**Frontend:**
- `web/src/api/approvals.ts` — full API client for approval queue, detail, approve/reject, and price-change queue.
- `web/src/pages/ManagerApprovals.tsx` — approval queue table (score badge, flag badges, click-to-navigate) + price change re-approval table.
- `web/src/pages/ManagerApprovalDetail.tsx` — full review detail page: ScoreBar visualization, management-review + title-hold alert banners, submission read-only display, ApproveForm + RejectForm.
- `web/src/App.tsx` / `web/src/components/Layout.tsx` — routes and nav links wired.
- `web/src/test/render.tsx` — added `path?` option so `useParams`-dependent pages work in tests.

### Key decisions

- `ConsignmentContract` was already in the DB schema (Phase 5 init); Sprint 3 only added `proposed_consignment_price` to `change_requests` — no new table needed.
- Route ordering: both FastAPI and MSW require specific routes before generic path-param routes (`/price-changes` before `/{submission_id}`, `/price-changes` before `/:id`).
- HMAC validation is opt-in (`esign_webhook_secret = ""`); enabling it in production requires setting the env var.
- Decline handler skips `record_transition` if record is already at `approved_pending_esign` (dispatch doesn't advance the status; a 409 would fire otherwise).

### Test results

- Backend integration: **528/528 passed**
- Backend unit: **177/177 passed**
- Frontend: **126/126 passed**

### Bugs found and fixed

- `logger.info("esign_webhook_received", event=event, ...)` — structlog's `event` is a reserved positional argument; renamed to `webhook_event`.
- `app_config_registry.get_value()` doesn't exist; corrected to `get_typed(...name)`.
- `esign_webhook_secret` not in `Settings` model — added with default `""`.
- MSW handler order: `/price-changes` must precede `/:id` in the handlers array.
- FastAPI route order: `/price-changes` must precede `/{submission_id}` in the router.

### Open issues / carry-forwards

- `field_values` (JSONB, keyed by prompt UUID) is still not extracted for red flag evaluation. Carry-forward from Sprint 1.
- eSign stub is used in all tests; real DocuSign/Dropbox Sign integration is deferred until the provider decision is made (tracked in `project_notes/decisions.md`).
