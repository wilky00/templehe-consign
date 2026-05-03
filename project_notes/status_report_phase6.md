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
