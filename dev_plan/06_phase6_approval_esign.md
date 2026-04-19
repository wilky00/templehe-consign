# Phase 6 — Appraiser Scoring Engine, Manager Approval & eSign Workflow

> **Prerequisite reading:** `00_overview.md`, `03_phase3_sales_crm.md`, `05_phase5_ios_app.md`
> **Reference data:** `03_implementation_package/06_scoring_and_rules_logic.csv`, `01_checklists/00_condition_scale_and_scoring.md`
> **Estimated scope:** 3–4 weeks
> **Deliverable:** Weighted scoring engine, red flag detection, manager approval workflow, eSign stub with interface, consignment price change re-approval, manual publish gate

---

## Epic 6.1 — Scoring Engine

### Feature 6.1.1 — Weighted Component Score Calculation

**User Story:**
As a Sales Manager, I want the platform to automatically calculate a weighted overall condition score from the appraiser's component ratings so that I have an objective baseline for valuation decisions rather than relying solely on subjective notes.

**Acceptance Criteria:**
- `ScoringService` class implemented in the API (`api/services/scoring.py`)
- Inputs: list of `ComponentScore` records (component name + raw score 0.0–5.0) + asset category
- Component weights loaded from `AppConfig` (seeded from `06_scoring_and_rules_logic.csv`); weights are per-category
- Calculation: `overall_score = Σ(component_score × weight_pct / 100)` for all components in the category
- Result rounded to 2 decimal places
- Score band label determined by `ScoringService.get_band(score)`:
  - 4.50–5.00 → "Premium resale-ready"
  - 3.75–4.49 → "Strong resale candidate"
  - 3.00–3.74 → "Usable with value deductions"
  - 2.00–2.99 → "Heavy discount / repair candidate"
  - 1.00–1.99 → "Project, salvage, or parts-biased"
  - 0.00–0.99 → "Insufficient data"
- `ScoringService` is pure (no DB calls) — inputs passed in, result returned; fully unit-tested
- Score stored on `AppraisalSubmission`: `overall_score DECIMAL(4,2)`, `score_band VARCHAR(100)`
- Recalculation triggered any time component scores are updated

---

### Feature 6.1.2 — Red Flag Detection & Management Review Triggers

**User Story:**
As a Sales Manager, I want the system to automatically flag submissions that have serious issues so that risky equipment gets routed to me for manual review rather than proceeding through the workflow unchecked.

**Acceptance Criteria:**
- `RedFlagService` evaluates the following conditions on each `AppraisalSubmission` (per all categories in `06_scoring_and_rules_logic.csv`):
  - `structural_damage = true` → set `management_review_required = true`; downgrade `marketability_rating` one band (Fast Sell → Average → Slow Sell → Salvage Risk)
  - `active_major_leak = true` → set `management_review_required = true`
  - `missing_serial_plate = true` → set `hold_for_title_review = true`
  - `running_status = Non-Running` → set `management_review_required = true`; set `marketability_rating = Salvage Risk` (unless appraiser has explicitly overridden with a note)
  - `hours_verified = false` → append to `review_notes`: "Verify hours history before pricing"
- Red flags stored on `AppraisalSubmission`: `management_review_required BOOLEAN`, `hold_for_title_review BOOLEAN`, `red_flags JSONB` (array of triggered rule IDs with notes)
- Red flag evaluation runs automatically on submission receipt (server-side, not relying on iOS client flags)
- If `management_review_required = true`, the Sales Manager is notified via their preferred channel: *"[Make Model] (THE-XXXXXXXX) has been flagged for management review: [red flag summary]."*
- `hold_for_title_review = true` blocks the approval workflow — the Manager approval screen shows a warning banner and requires the Manager to explicitly check a "Title review confirmed" checkbox before approving

---

## Epic 6.2 — Manager Approval Workflow

### Feature 6.2.1 — Initial Appraisal Approval

**User Story:**
As a Sales Manager, I want to review completed appraisals and approve the initial purchase offer and consignment price before they are communicated to the customer so that I maintain quality control over every valuation that goes out.

**Acceptance Criteria:**
- Manager approval queue accessible at `/manager/approvals`
- Queue shows all `EquipmentRecord` rows with `status = appraisal_completed` assigned to the logged-in manager (or all records for `admin` role)
- Each queue item shows: make/model, customer name, overall score, score band, marketability rating, appraiser name, submission date, red flag badges
- Clicking an item opens the full Approval Detail view:
  - All appraisal fields from the iOS submission (read-only)
  - All component scores with a visual breakdown chart
  - Required photos gallery (thumbnail grid; click to expand full-size)
  - Comparable sales data (if any were pinned by the appraiser)
  - EXIF metadata for each photo (timestamp, GPS coordinates) — expandable panel
  - Red flag summary (if any)
  - **Approval inputs (Manager-editable):**
    - Purchase Offer Amount (currency input, required)
    - Suggested Consignment Price (currency input, required)
    - Manager Notes (text area, optional)
  - "Approve" button and "Reject with Notes" button
- Record locking applies to the Approval Detail view (Feature 3.5)
- On **Approve:**
  - `AppraisalSubmission.approved_purchase_offer` and `.suggested_consignment_price` populated
  - `EquipmentRecord.status` → `approved_pending_esign`
  - Notification sent to assigned Sales Rep (Feature 3.2.1)
  - Approval event written to `audit_logs`
- On **Reject:**
  - `EquipmentRecord.status` → `rejected` (or back to `appraisal_completed` if the intent is to request re-inspection — Manager selects from a modal: "Reject permanently" or "Send back for re-appraisal")
  - If "Send back for re-appraisal": status reverts to `new_request`; appraiser and sales rep notified
  - Rejection notes stored on the `AppraisalSubmission` record

---

### Feature 6.2.2 — Consignment Price Change Re-Approval

**User Story:**
As a Sales Manager, I want to be automatically notified and required to re-approve when a customer requests a consignment price change that exceeds my configured threshold so that significant pricing decisions always have management sign-off.

**Acceptance Criteria:**
- When a customer submits a `ChangeRequest` with `request_type = UpdateHoursOrCondition` that results in a proposed consignment price change, the `PriceChangeService` evaluates:
  - `change_pct = |new_price - approved_price| / approved_price`
  - If `change_pct > AppConfig('consignment_price_change_threshold_pct')` (default: 10%), set `requires_manager_reapproval = true` on the `ChangeRequest`
- When `requires_manager_reapproval = true`:
  - The record returns to the manager approval queue with a `Consignment Price Change` badge
  - Manager receives a notification: *"Price change re-approval required: THE-XXXXXXXX — [old price] → [proposed price] ([+/- pct]%)"*
  - The Sales Rep cannot advance the eSign workflow until re-approval is complete
- Re-approval workflow same as initial approval (Feature 6.2.1) but only shows the pricing change delta — not the full submission review
- Re-approval or re-rejection events written to `audit_logs`

---

## Epic 6.3 — eSign Workflow

### Feature 6.3.1 — eSign Service Interface (Stubbed)

**User Story:**
As a developer, I want the eSign integration abstracted behind a clean interface so that we can swap providers (DocuSign, Dropbox Sign, etc.) in Phase 7 or later without touching business logic.

**Acceptance Criteria:**
- `SigningService` interface (`api/services/signing.py`) defines:
  - `create_envelope(record_id, customer_email, customer_name, document_data) → envelope_id: str`
  - `get_envelope_status(envelope_id) → status: EnvelopeStatus`
  - `void_envelope(envelope_id, reason: str) → bool`
  - `get_signing_url(envelope_id, return_url: str) → url: str` (for embedded signing)
- `StubSigningService` implementation returns mock data: `envelope_id = "stub-{uuid}"`, `status = EnvelopeStatus.SENT`, signing URL = `"/esign/stub-preview"`
- The stub signing URL renders a simple HTML page (served by the API): *"[Stub] This is where the consignment agreement would be signed. [Sign Now]"* — clicking "Sign Now" calls `POST /api/v1/esign/stub-sign/:envelope_id` which fires the webhook handler with a synthetic `signed` event
- Active implementation selected via `AppConfig('esign_provider')` — currently `stub`; adding a real provider means adding a new class implementing `SigningService` and updating the config value
- All `SigningService` calls logged to `audit_logs`

---

### Feature 6.3.2 — Automated eSign Contract Dispatch

**User Story:**
As a Sales Manager, I want the system to automatically send the consignment agreement to the customer for eSign as soon as I approve the appraisal so that the signing process starts without waiting for a Sales Rep to manually send it.

**Acceptance Criteria:**
- When `EquipmentRecord.status` transitions to `approved_pending_esign`, a Pub/Sub message is published to the `esign-dispatch` topic
- The `ESignWorker` Cloud Run Job consumes the message and:
  1. Generates the consignment contract document (populated with: customer name/address, make/model/serial, approved purchase offer, suggested consignment price, TempleHE terms — see Phase 7 for PDF generation; in Phase 6 use a simple text contract stub)
  2. Calls `SigningService.create_envelope(...)` to send the document for signature
  3. Stores the returned `envelope_id` on the `ConsignmentContract` record with `status = sent`
  4. Sends the customer an email: *"Your consignment agreement for [Make Model] is ready to sign. [Sign Now]"* with a link to the signing flow
- Embedded signing supported: `GET /api/v1/esign/sign/:envelope_id` returns a redirect to `SigningService.get_signing_url(...)` — customer signs within the portal or via the emailed link
- Contract document template stored as a configurable text/HTML template in `AppConfig('esign_contract_template')`

---

### Feature 6.3.3 — eSign Completion Webhook

**User Story:**
As a Sales Rep, I want the platform to automatically update the equipment record when the customer completes the eSign agreement so that the workflow advances without anyone having to manually check the eSign provider.

**Acceptance Criteria:**
- `POST /api/v1/esign/webhook` receives callbacks from the signing provider (or the stub service)
- Webhook payload validated using HMAC signature verification (secret from `AppConfig('esign_webhook_secret')`)
- On `envelope_completed` event:
  - `ConsignmentContract.signed_at` populated
  - `ConsignmentContract.status = completed`
  - `EquipmentRecord.status → esigned_pending_publish`
  - Sales Rep notification dispatched (Feature 3.2.2)
  - Event written to `audit_logs`
- On `envelope_declined` event:
  - `ConsignmentContract.status = declined`
  - `EquipmentRecord.status` reverts to `approved_pending_esign`
  - Sales Rep and Manager notified: *"Customer declined the consignment agreement for THE-XXXXXXXX."*
- Webhook is idempotent — duplicate events do not create duplicate state transitions

---

## Phase 6 Completion Checklist

- [ ] `ScoringService` calculates weighted score correctly for all 15 categories; fully unit-tested
- [ ] Red flag conditions all trigger correctly; marketability downgrade fires on `structural_damage`; `missing_serial_plate` blocks approval with title review checkbox
- [ ] Manager approval queue shows correct records; approval transitions status to `approved_pending_esign` and notifies Sales Rep
- [ ] "Reject — Send back for re-appraisal" reverts status to `new_request`; all parties notified
- [ ] Price change > threshold triggers re-approval queue entry; manager receives notification
- [ ] `StubSigningService` sends mock envelope and returns synthetic signing URL
- [ ] Stub "Sign Now" triggers webhook handler; `ConsignmentContract.signed_at` populated; Sales Rep notified; status = `esigned_pending_publish`
- [ ] eSign webhook is idempotent (sending same event twice does not double-transition status)
- [ ] All approval, rejection, and eSign events in `audit_logs` with before/after state
