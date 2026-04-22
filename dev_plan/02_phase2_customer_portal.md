# Phase 2 — Customer Portal & Equipment Intake

> **Prerequisite reading:** `00_overview.md`, `01_phase1_infrastructure_auth.md`, `project_notes/decisions.md` (ADR-012), `project_notes/code_review_phase1.md`
> **Reference data:** `02_schema_and_dictionary/01_normalized_app_field_schema_v1.md`, `03_implementation_package/04_app_input_fields_only.csv`, `03_implementation_package/05_reference_tables.csv`
> **Estimated scope:** 3–4 weeks
> **Deliverable:** Fully functional customer portal — registration, equipment intake, status dashboard, change requests, notifications

---

## Phase 1 Carry-Forward / Fragility Assumptions

Phase 2 builds on the hardened Phase 1 surface documented in `project_notes/code_review_phase1.md`. The following assumptions are now safe to make; each is load-bearing for at least one Phase 2 feature.

- **Refresh token via cookie.** Frontend fetches to auth endpoints must use `credentials: "include"` / `withCredentials: true`. The cookie is HttpOnly + SameSite=Strict, scoped to `/api/v1/auth`. See ADR-012.
- **Rate limiter keyed on the real client IP.** Any new Phase 2 rate-limited endpoint can reuse `middleware.rate_limit.rate_limit_by_ip` / `rate_limit_by_email` without the "everyone shares the edge IP" bug.
- **`GET /api/v1/auth/me`** is live — use it as the bootstrap call for client-side state.
- **Email dispatch is non-blocking.** FastAPI `BackgroundTasks` is the Phase-1 stopgap. Feature 2.2.2 (Submission Confirmation Email) should use the `NotificationService` + `notification_jobs` queue per ADR-001 instead — durability matters once it's customer-facing. Treat `BackgroundTasks` as a temporary bridge for auth flows only.
- **`audit_logs` partitioning + hourly retention sweeper** are live. Schema churn in Phase 2 should keep the `created_at` partition key intact.
- **`get_db` is one-transaction-per-request.** Intake flows that need commit-then-emit semantics instantiate `AsyncSessionLocal()` directly; see ADR-012.

Items still open that touch Phase 2:

- **Equipment category seed data** (`category_components`, `category_inspection_prompts`, `category_photo_slots`, `category_red_flag_rules`) — intake form must either stay category-agnostic until Phase 4 Admin Panel lands or Phase 2 ships partial seeds for the two or three categories needed on day 1. Tracked in `project_notes/known-issues.md`.
- **Content sanitization for user-submitted free-text fields** — `bleach` was removed during Phase 1 hardening because no Phase 1 code consumed it. Phase 2 intake (notes fields on `EquipmentRecord`, `ChangeRequest`, etc.) must re-add `bleach` and call it on write, per `dev_plan/11_security_baseline.md §3`.
- **PII retention / row-level `audit_logs` retention** — deferred to Phase 2 data export & deletion work (`11_security_baseline.md §7`). Row-level retention on `audit_logs` and `user_sessions` / `known_devices` must be decided before real customer data lands on prod.

---

## Epic 2.1 — Customer Registration & Profile

### Feature 2.1.1 — Customer Business Profile Registration

**User Story:**
As a customer, I want to register my business profile so that TempleHE has all the context they need to process my equipment inquiry without me having to repeat myself on every call.

**Acceptance Criteria:**
- Customer registration form captures all required fields:
  - Business Name (required)
  - Submitter Full Name (required)
  - Submitter Title (required)
  - Business Address — Street, City, State, ZIP (all required)
  - Business Phone + Extension (phone required, extension optional)
  - Cell Phone Number (optional)
  - Email Address (required, validated format)
  - Communication Preferences (multi-select: Email, SMS, Phone)
- When the user selects **SMS** as a communication preference, a visible inline warning renders: *"Standard SMS messaging rates may apply based on your carrier plan."* The checkbox must remain selectable after acknowledging — this is a notice, not a blocker.
- On save, a `Customer` record is created linked to the authenticated `User` account
- A single `User` account maps to exactly one `Customer` business profile
- `PATCH /api/v1/customers/me` allows the customer to update their profile at any time
- All profile fields validated server-side with human-readable error messages (no raw 422 JSON)
- Profile page is accessible at `/portal/profile`

---

### Feature 2.1.2 — Customer Dashboard

**User Story:**
As a customer, I want a dashboard that shows all my equipment submissions and their current status so that I always know where things stand without having to call TempleHE.

**Acceptance Criteria:**
- Dashboard accessible at `/portal/dashboard`
- Displays all `EquipmentRecord` rows owned by the authenticated customer
- Each row shows: Equipment Name (make + model), submitted date, unique Record ID, current status badge
- Status badges use distinct colors for each state:
  - `New Request` → gray
  - `Appraisal Scheduled` → blue
  - `Appraisal Completed` → yellow
  - `Published` → green
  - `Withdrawn` → red
- Clicking a row opens the Equipment Detail view
- Dashboard is paginated (25 records per page) with search by Record ID or make/model
- Dashboard updates in real-time via polling every 60 seconds (no WebSocket required in this phase)
- Empty state shown with a CTA to submit equipment when no records exist

---

## Epic 2.2 — Equipment Intake Submission

### Feature 2.2.1 — Equipment Intake Form

**User Story:**
As a customer, I want to submit my equipment details through a guided form so that TempleHE has everything they need to begin the appraisal process.

**Acceptance Criteria:**
- Intake form accessible at `/portal/submit`
- Step 1 — Equipment Identity:
  - Asset Category (required, dropdown from `05_reference_tables.csv` asset_category list)
  - Manufacturer / Make (required, text)
  - Model (required, text)
  - Year (optional, integer, 1950–current year)
  - Serial Number / PIN (required, text)
  - Machine Hours (required, decimal)
  - Ownership Type (required, dropdown: Owned / Financed / Leased / Unknown)
  - Lien Status (optional, dropdown: Clear / Lien Reported / Unknown)
- Step 2 — Condition & Intent:
  - Running Status (required, dropdown: Running / Partial / Non-Running)
  - Overall Cosmetic Condition (required, dropdown: Excellent / Good / Fair / Poor / Inoperable / Not Verified)
  - Acquisition Path (required, dropdown: Consignment / Direct Purchase / Both)
  - Service Records Available (required, Yes / No toggle)
  - Customer Notes (optional, textarea, max 2000 chars)
- Step 3 — Confirmation:
  - Summary of all entered fields for review before submission
  - "Submit Equipment" button triggers form submission
- Form validates each step before advancing (client-side + server-side)
- Multi-item support: after submitting one item, customer is offered "Submit another item" which creates a new `EquipmentRecord` under the same `Customer`
- Admin-configurable fields: the set of fields shown in Step 1 and Step 2 is controlled by `AppConfig` keys (`intake_fields_visible`, `intake_fields_required`) — Admin can add/remove/re-order fields without a code deploy (Phase 4 wires the Admin UI; this phase reads from `AppConfig` defaults)

---

### Feature 2.2.2 — Submission Confirmation Email

**User Story:**
As a customer, I want to receive a confirmation email immediately after submitting equipment so that I have a record of my submission and know what to expect next.

**Acceptance Criteria:**
- On successful `POST /api/v1/equipment-records`, a confirmation email is dispatched via the `NotificationService` (async, via Pub/Sub)
- Email contains:
  - Unique Record ID (UUID, formatted as `THE-XXXXXXXX`)
  - Summary of submitted equipment (make, model, serial, hours)
  - Current status: "New Request — under review"
  - Next steps paragraph: *"A member of our team will reach out within 1–2 business days to discuss your equipment and schedule an on-site appraisal."*
  - Direct link to the customer portal dashboard
  - TempleHE contact information
- Email is sent to the customer's registered email address
- If SMS is in their communication preferences, a brief SMS is also sent via Twilio: *"TempleHE received your equipment request (ID: THE-XXXXXXXX). Check your email for details."*
- Email delivery failure is logged to `audit_logs` and retried up to 3 times with exponential backoff

---

## Epic 2.3 — Equipment Detail & Status Tracking

### Feature 2.3.1 — Equipment Detail View

**User Story:**
As a customer, I want to view the full details of my equipment submission so that I can verify the information on file and track progress at each step.

**Acceptance Criteria:**
- Detail view accessible at `/portal/equipment/:record_id`
- Displays all submitted fields (read-only)
- Displays current status with a visual progress timeline showing all status stages
- Displays the assigned TempleHE Sales Rep name and direct phone number (shown once assigned — `sales` role sets this)
- Displays the scheduled appraisal date/time once set (status ≥ `appraisal_scheduled`)
- Displays a download link for the appraisal PDF report once published (status = `published`)
- Displays the consignment listing price once published
- Customer cannot edit any fields directly on this view (changes go through the Change Request flow)
- If the record has an active change request, a banner shows: *"Your change request is being reviewed."*

---

### Feature 2.3.2 — Status Update Email Notifications

**User Story:**
As a customer, I want to receive an email when my equipment status changes so that I don't have to check the portal constantly.

**Acceptance Criteria:**
- Automated email sent to customer on each of the following status transitions:
  - `new_request → appraisal_scheduled`: includes scheduled date, time, and appraiser name
  - `appraisal_completed → pending_manager_approval`: *"Your equipment has been evaluated. Pricing review is underway."*
  - `approved_pending_esign → esigned_pending_publish` (triggered after eSign): *"Your agreement has been received. Your listing will be published shortly."*
  - `esigned_pending_publish → published`: includes live listing link
- Email template uses TempleHE branding (logo, color scheme, footer with contact info)
- All notification dispatches logged to `audit_logs`

---

## Epic 2.4 — Change Requests

### Feature 2.4.1 — Customer Change Request Submission

**User Story:**
As a customer, I want to request changes to my equipment listing through the portal so that I have a clear, documented channel rather than trying to reach someone by phone.

**Acceptance Criteria:**
- "Request a Change" button visible on the Equipment Detail view for records with status `published` or `esigned_pending_publish`
- Change request form presents exactly three options (radio buttons):
  1. **Delete Listing** — *"I want to remove this equipment from the TempleHE platform."*
  2. **Update Description** — *"I want to change the written description or notes for this listing."*
  3. **Update Hours or Condition** — *"The hours or condition information needs to be corrected."*
- Selecting any option opens a free-text field (max 1000 chars) for the customer to describe what needs to change
- On submit, a `ChangeRequest` record is created with: `equipment_record_id`, `request_type`, `customer_notes`, `status = pending`, `submitted_at`
- Customer cannot submit a second change request while one is already `pending` for the same record; they see a banner indicating the first request is in review
- `GET /api/v1/equipment-records/:id/change-requests` returns the customer's change request history for that record

---

### Feature 2.4.2 — Change Request Routing to TempleHE Employee

**User Story:**
As a Sales Rep, I want to receive an immediate notification when a customer submits a change request on my assigned listing so that I can respond promptly and maintain trust.

**Acceptance Criteria:**
- On `ChangeRequest` creation, the `NotificationService` looks up the assigned Sales Rep for that `EquipmentRecord`
- Notification delivered to the Sales Rep via their configured preferred channel (email | SMS | Slack)
  - **Email:** Subject: `[Action Required] Change Request — THE-XXXXXXXX`, body includes customer name, record ID, request type, customer notes, and a deep link to the record in the Sales dashboard
  - **SMS (Twilio):** *"TempleHE: [Customer Name] submitted a [Request Type] request on THE-XXXXXXXX. Log in to review."*
  - **Slack:** Posts a message to the configured Slack channel (or DM if Slack user ID is mapped) with equipment details and a link
- If no Sales Rep is assigned, notification routes to the default Sales Manager
- Notification dispatch logged to `audit_logs`
- If notification dispatch fails (e.g., Twilio error), the failure is logged and an email fallback is attempted

---

### Feature 2.4.3 — Change Request Resolution

**User Story:**
As a Sales Rep, I want to mark change requests as resolved in the system so that the customer is notified and the record reflects what was done.

**Acceptance Criteria:**
- `PATCH /api/v1/change-requests/:id` (roles: `sales`, `sales_manager`, `admin`) accepts `status` (`resolved | rejected`) and `resolution_notes`
- On resolution, the customer receives an email summarizing the action taken
- If the request type was `Delete Listing`, resolution sets `EquipmentRecord.status = withdrawn`
- If the request type was `Update Description` or `Update Hours or Condition`, the Sales Rep must update the relevant fields before marking resolved (validated server-side)
- Resolved change requests are visible in the customer's Equipment Detail view history
- Change request status transitions written to `audit_logs`

---

## Epic 2.5 — PDF Appraisal Report (Customer View)

### Feature 2.5.1 — PDF Download from Portal

**User Story:**
As a customer, I want to download a PDF copy of my equipment's appraisal report so that I have a professional document I can keep for my records or share with a lender.

**Acceptance Criteria:**
- "Download Report" button appears on the Equipment Detail view once status = `published` and an `AppraisalReport` record exists
- `GET /api/v1/equipment-records/:id/report/pdf` returns a signed Cloud Storage URL (short-lived, 15-minute expiry) pointing to the generated PDF
- If the PDF has not yet been generated, the endpoint returns 202 with a status message; the download button shows a spinner
- PDF generation is handled in Phase 7; this feature only surfaces the download link — the endpoint can return a placeholder PDF in Phase 2 for testing
- Customers can only access PDF for their own records (enforced by ownership check, not just auth)

---

## Phase 2 Completion Checklist

- [ ] Customer completes registration form — SMS warning displays when SMS is selected
- [ ] Customer submits equipment intake — confirmation email received with Record ID `THE-XXXXXXXX`
- [ ] Dashboard displays all equipment records with correct status badges
- [ ] Status transitions trigger correct customer notification emails
- [ ] Customer submits a change request — Sales Rep receives notification on their preferred channel
- [ ] Sales Rep resolves change request — customer receives resolution email
- [ ] Admin can modify `AppConfig` intake field visibility — form reflects changes without code deploy
- [ ] Attempting to access another customer's records returns 403
- [ ] All actions produce `audit_log` entries
