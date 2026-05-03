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

