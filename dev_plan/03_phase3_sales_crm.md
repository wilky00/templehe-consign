# Phase 3 — Sales CRM, Lead Routing & Shared Calendar

> **Prerequisite reading:** `00_overview.md`, `01_phase1_infrastructure_auth.md`, `02_phase2_customer_portal.md`, `project_notes/decisions.md` (ADR-012)
> **Estimated scope:** 4–5 weeks
> **Deliverable:** Sales rep dashboard, lead routing engine with waterfall rules, shared calendar with automated conflict resolution and drive time buffering, click-to-call, automated notifications

---

## Phase 1 Carry-Forward Notes

- **`audit_logs` is already monthly-range-partitioned on `created_at`** as of Phase 1 hardening (migration 003, ADR-012). Phase 3's high-volume audit traffic (lead routing, calendar events, lock overrides) uses the partitioned table unchanged — nothing to do here beyond normal `_audit()` calls.
- **Hourly retention sweeper** (`temple-sweeper` Fly Machine) keeps `rate_limit_counters` / `webhook_events_seen` / expired `user_sessions` in check. If Phase 3 adds new ephemeral tables, extend `fn_sweep_retention()` and include them in `scripts/sweep_retention.py` rather than spinning up another cron.

---

## Epic 3.1 — Sales Representative Dashboard

### Feature 3.1.1 — Grouped Customer Record View

**User Story:**
As a Sales Rep, I want my dashboard to show customer records grouped by customer so that when a business submits multiple pieces of equipment I can manage them together as a single account rather than a flat list of machines.

**Acceptance Criteria:**
- Sales dashboard accessible at `/sales/dashboard`
- Records are grouped by `Customer` (parent level) with collapsible child rows for each `EquipmentRecord`
- Parent row shows: Customer business name, submitter name, cell phone (click-to-call), total items, date of first submission, assigned sales rep name
- Child row shows: make/model, serial, status badge, assigned appraiser, scheduled appraisal date, Record ID
- Dashboard defaults to showing only records assigned to the logged-in Sales Rep
- Toggle to "All Records" available for `sales_manager` and `admin` roles
- Filterable by: status, assigned rep, assigned appraiser, equipment category, submission date range
- Sortable by: customer name, submission date, status, scheduled appraisal date
- Paginated at 50 records per page with search by customer name, Record ID, or serial number

---

### Feature 3.1.2 — Individual Equipment Record View (Sales)

**User Story:**
As a Sales Rep, I want to open an individual equipment record and see everything relevant to that machine so that I have all the context needed to manage the customer relationship without switching screens.

**Acceptance Criteria:**
- Record detail view accessible at `/sales/equipment/:record_id`
- Displays: all customer intake fields, current status with history timeline, assigned sales rep and appraiser, scheduled appraisal date/time, appraisal submission data (once submitted), valuation data, manager approval status, eSign status, listing price
- Record is locked when opened for editing; lock indicator shown in UI: *"You are editing this record"* or *"This record is being edited by [Name]"*
- Lock acquired via `POST /api/v1/record-locks` on record open; released on close or 15-minute inactivity
- Heartbeat: frontend sends `PUT /api/v1/record-locks/:record_id/heartbeat` every 60 seconds while editing is active
- Click-to-call: all phone numbers rendered as `tel:` links with a phone icon — tapping initiates a call on mobile or opens the default calling app on desktop
- "Assign Sales Rep" and "Assign Appraiser" dropdowns pull from users with those roles
- Changes to assignment saved via `PATCH /api/v1/equipment-records/:id`

---

### Feature 3.1.3 — Cascade Assignment

**User Story:**
As a Sales Rep, I want to assign a sales rep and appraiser to all of a customer's equipment records at once so that I don't have to set the same assignments individually on 10 different machines.

**Acceptance Criteria:**
- "Apply to All" (cascade) button appears on the Customer parent row in the dashboard
- Clicking opens a modal: "Assign Sales Rep" dropdown + "Assign Appraiser" dropdown + confirmation checkbox: *"Apply these assignments to all [N] equipment items for [Customer Name]"*
- On confirm, `PATCH /api/v1/customers/:customer_id/cascade-assignments` updates all `EquipmentRecord` rows for that customer where `status = new_request` (does not override already-assigned records in later statuses)
- If any records are in a status that blocks reassignment, the modal warns: *"[N] records in progress will not be changed."*
- Cascade action written to `audit_logs` as a single event with `target_type = customer`, listing all affected record IDs in `after_state`

---

### Feature 3.1.4 — Manual Publish

**User Story:**
As a Sales Rep, I want to manually publish a listing to the public inventory page after the customer completes the eSign agreement so that I retain final control over when a listing goes live.

**Acceptance Criteria:**
- "Publish Listing" button visible only when `EquipmentRecord.status = esigned_pending_publish`
- Button triggers `POST /api/v1/equipment-records/:id/publish`
- Server validates: `status = esigned_pending_publish`, a completed `ConsignmentContract` exists with `signed_at` populated, an `AppraisalReport` exists
- On success, `status` transitions to `published`, a `PublicListing` record is created/updated, and a status email is sent to the customer
- If any validation fails, the endpoint returns 400 with a specific message (not a generic error)
- Publish action requires `sales` or higher role; `customer` cannot trigger this

---

## Epic 3.2 — Automated Notifications for Sales Workflow

### Feature 3.2.1 — Manager Approval Notification

**User Story:**
As a Sales Rep, I want to receive an email when my Sales Manager approves the initial appraisal price so that I know I can move forward with the eSign process.

**Acceptance Criteria:**
- When `EquipmentRecord.status` transitions to `approved_pending_esign` (triggered by Manager Approval in Phase 6), the `NotificationService` dispatches an email to the assigned Sales Rep
- Email subject: `[Approved] Appraisal for THE-XXXXXXXX — Ready for eSign`
- Email body includes: customer name, equipment make/model, approved purchase offer amount, suggested consignment price, link to the record in the Sales dashboard
- If the Sales Rep has SMS as their preferred channel, an SMS is also sent: *"Manager approved THE-XXXXXXXX. Log in to initiate eSign."*
- Notification dispatch logged to `audit_logs`

---

### Feature 3.2.2 — eSign Completion Notification

**User Story:**
As a Sales Rep, I want to be notified the moment a customer completes the eSign agreement so that I can publish the listing without delay.

**Acceptance Criteria:**
- When `ConsignmentContract.signed_at` is populated (eSign webhook in Phase 6), the `NotificationService` dispatches a notification to the assigned Sales Rep
- Notification delivered via their preferred channel (email | SMS | Slack)
- Email: *"[Customer Name] has signed the consignment agreement for [Make Model] (THE-XXXXXXXX). The listing is ready to publish."* with a direct "Publish Now" deep link
- SMS: *"TempleHE: [Customer Name] signed the agreement for THE-XXXXXXXX. Ready to publish."*
- Notification logged to `audit_logs`

---

## Epic 3.3 — Lead Routing Engine

### Feature 3.3.1 — Lead Routing Rule Configuration (Admin)

**User Story:**
As an Admin, I want to define lead routing rules so that new customer submissions are automatically assigned to the right Sales Rep without manual intervention.

**Acceptance Criteria:**
- Lead routing rules stored in `lead_routing_rules` table: `id`, `rule_type` (ad_hoc | geographic | round_robin), `priority` (integer, lower = higher priority), `conditions JSONB`, `assigned_user_id`, `is_active`, `created_by`, `created_at`
- Three rule types supported:
  - **Ad Hoc (Manual):** Assigns a specific customer or submission to a specific Sales Rep by customer ID or email domain
  - **Geographic:** Assigns based on customer address — supports matching by: US State (2-letter code), ZIP Code (exact or range), Metro Area (predefined polygon or named area with configurable radius in miles)
  - **Round Robin:** Catch-all that cycles through an ordered list of Sales Reps (stored as a JSON array on the rule)
- Admin UI for rule management in Phase 4; this feature implements the data model and API:
  - `GET /api/v1/admin/routing-rules` — paginated list
  - `POST /api/v1/admin/routing-rules` — create rule
  - `PATCH /api/v1/admin/routing-rules/:id` — update rule (priority, conditions, assigned user, active status)
  - `DELETE /api/v1/admin/routing-rules/:id` — soft delete

---

### Feature 3.3.2 — Rule Execution Waterfall

**User Story:**
As an Admin, I want the system to evaluate routing rules in a defined priority order so that overlapping rules don't cause conflicts and the most specific rule always wins.

**Acceptance Criteria:**
- On `EquipmentRecord` creation, the `LeadRoutingService` evaluates rules in this order:
  1. **Ad Hoc rules** — evaluated first; if a rule matches the customer ID or email domain, assign immediately and stop
  2. **Geographic rules** — evaluated in ascending `priority` order; first matching geographic rule assigns and stops; matching logic:
     - State: customer address state matches rule state list
     - ZIP: customer ZIP is in the rule's ZIP list (supports comma-separated or ranges like `30301-30399`)
     - Metro Area: customer address geocoded via Google Maps Geocoding API; distance to metro center ≤ configured radius
  3. **Round Robin** — if no ad hoc or geographic rule matched, the round-robin rule fires; the `round_robin_index` on the rule is incremented atomically (using Redis `INCR` to avoid race conditions) and the next Sales Rep in the list is selected
- If no rule matches at all, the record is assigned to a default Sales Rep configured in `AppConfig` (key: `default_sales_rep_id`)
- Assignment written to `EquipmentRecord.assigned_sales_rep_id`; assignment event written to `audit_logs` with `trigger = lead_routing, rule_id = <id>, rule_type = <type>`
- `LeadRoutingService` is testable in isolation with mock rule sets (unit tested)

---

### Feature 3.3.3 — Manual (Ad Hoc) Override

**User Story:**
As a Sales Manager, I want to manually reassign any equipment record to a different Sales Rep so that I can correct routing errors or handle special cases.

**Acceptance Criteria:**
- `PATCH /api/v1/equipment-records/:id` with `assigned_sales_rep_id` triggers reassignment (roles: `sales_manager`, `admin`)
- Manual reassignment bypasses the routing engine entirely
- Reassignment event written to `audit_logs` with `trigger = manual_override`
- The newly assigned Sales Rep receives a notification: *"You have been assigned equipment record THE-XXXXXXXX ([Make Model] for [Customer Name])."*

---

## Epic 3.4 — Shared Calendar & Appraisal Scheduling

### Feature 3.4.1 — Shared Calendar View

**User Story:**
As a Sales Rep, I want to see a shared calendar showing all scheduled appraisals across the team so that I can find open time slots and avoid conflicts.

**Acceptance Criteria:**
- Shared calendar accessible at `/sales/calendar`
- Calendar displays `CalendarEvent` records; each event shows: appraiser name, customer name, equipment make/model, location city/state
- Three views: Month, Week, Day — standard calendar grid
- Events color-coded by appraiser
- Filter by appraiser (multi-select dropdown)
- Clicking an event opens the linked Equipment Record detail
- **Editing:** `sales`, `sales_manager`, and `admin` can all create, edit, cancel, and reschedule events. Every create/update/delete writes an `audit_logs` entry with actor role + before/after state so manager + admin can audit sales-rep changes after the fact.
- Calendar data fetched from `GET /api/v1/calendar/events?start=<ISO>&end=<ISO>&appraiser_id=<id>`

---

### Feature 3.4.2 — Schedule Appraisal with Conflict Resolution

**User Story:**
As a Sales Rep, I want to book an appraisal appointment for a specific appraiser and have the system automatically prevent double-bookings so that two appraisals are never scheduled at the same time for the same person.

**Acceptance Criteria:**
- "Schedule Appraisal" action available on Equipment Records with status `new_request`
- Scheduling form collects: Appraiser (dropdown, role = `appraiser`), Proposed Date, Proposed Start Time, Site Address (pre-filled from equipment record customer address, editable)
- On submit, `POST /api/v1/calendar/events` runs a conflict check before saving:
  - Queries all existing `CalendarEvent` rows for the selected appraiser where the proposed time window overlaps with any existing event (including drive time buffer — see Feature 3.4.3)
  - If a conflict is found, the API returns 409 with details: *"[Appraiser Name] is already scheduled at [Time] — drive time from the prior appointment would not allow arrival until [Calculated Time]. Next available slot: [Suggested Time]."*
  - If no conflict, the event is saved and `EquipmentRecord.status` transitions to `appraisal_scheduled`
- Conflict check is atomic — performed inside a database transaction to prevent race conditions when two reps schedule simultaneously
- Appraiser receives a push notification (mobile, Phase 5) and an email with appointment details
- Customer receives a status notification (Feature 2.3.2)

---

### Feature 3.4.3 — Google Maps Drive Time Buffer

**User Story:**
As a Sales Rep, I want the calendar to automatically calculate the drive time from an appraiser's previous appointment to the new one so that I never accidentally schedule back-to-back appraisals at sites that are hours apart.

**Acceptance Criteria:**
- When scheduling a new appraisal, the system queries the appraiser's most recent preceding `CalendarEvent` that day
- If a preceding event exists, the system calls the Google Maps Distance Matrix API with:
  - Origin: preceding event's `site_address`
  - Destination: new event's `site_address`
  - Mode: `driving`, `departure_time: now` (to get traffic-aware estimate)
- The API response `duration_in_traffic` is added as a buffer between the end of the preceding event and the proposed start of the new event
- If the proposed start time is within the drive time buffer, the scheduling attempt is blocked with a specific conflict message (see Feature 3.4.2)
- Drive time buffer is also applied looking forward (previous event must end + drive time ≤ new event start)
- Google Maps API key stored in Secret Manager; billing account configured on GCP project
- Drive time result cached in Redis for 6 hours per origin/destination pair to minimize API call volume
- If the Google Maps API call fails, the system falls back to a configurable flat buffer (default: 60 minutes, managed via `AppConfig` key `drive_time_fallback_minutes`)

---

### Feature 3.4.4 — Appraisal Appointment Editing and Cancellation

**User Story:**
As a Sales Manager, I want to reschedule or cancel an appraisal appointment so that I can accommodate changes without losing the associated equipment record.

**Acceptance Criteria:**
- `PATCH /api/v1/calendar/events/:id` allows updating: appraiser, date/time, site address (roles: `sales_manager`, `admin`)
- Updating date/time or appraiser re-runs the full conflict check and drive time buffer validation
- `DELETE /api/v1/calendar/events/:id` cancels the appointment; `EquipmentRecord.status` reverts to `new_request`
- On cancellation, appraiser and customer both receive notification of the cancellation
- All calendar event changes written to `audit_logs`

---

## Epic 3.5 — Record Locking (Pessimistic Concurrency)

### Feature 3.5.1 — Record Lock Lifecycle

**User Story:**
As a Sales Rep, I want to know when another user is editing the same record I'm viewing so that I don't overwrite their changes without realizing it.

**Acceptance Criteria:**
- `POST /api/v1/record-locks` body: `{ "record_id": "<uuid>", "record_type": "equipment_record" }` — acquires lock; returns 200 if acquired, 409 if already locked with `{ "locked_by": "<user name>", "locked_at": "<ISO>", "expires_at": "<ISO>" }`
- Lock stored in Redis with a TTL of 900 seconds (15 minutes); also written to `record_locks` DB table for audit
- `PUT /api/v1/record-locks/:record_id/heartbeat` — resets TTL to 900 seconds; returns 200 if lock still valid, 404 if lock expired
- `DELETE /api/v1/record-locks/:record_id` — releases lock; only the lock owner can release (unless override role)
- Frontend polling: the edit form sends heartbeat every 60 seconds while open; if heartbeat returns 404 (lock expired), the form shows: *"Your editing session timed out. Your changes may not have been saved."*
- Non-editable views (read-only) do not acquire a lock

---

### Feature 3.5.2 — Admin/Manager Lock Override

**User Story:**
As a Sales Manager, I want to break a stale lock on a record so that work can continue when someone left a record open accidentally.

**Acceptance Criteria:**
- `DELETE /api/v1/record-locks/:record_id/override` available to `sales_manager` and `admin` roles only
- Override removes the Redis key and marks the `record_locks` DB row with `overridden_by` and `overridden_at`
- The user whose lock was broken receives a notification (their preferred channel): *"Your editing lock on [Make Model] (THE-XXXXXXXX) was released by [Manager Name]."*
- Override action written to `audit_logs`

---

## Phase 3 Completion Checklist

- [x] Sales dashboard groups records by customer; cascade assignment updates all child records correctly
- [x] Lead routing engine evaluates ad hoc → geographic → round-robin waterfall; assignment written to audit log with rule ID
- [x] Geographic routing correctly matches State, ZIP, and Metro Area (radius) conditions
- [x] Round-robin uses atomic Redis counter and does not double-assign under concurrent load (test with 2 simultaneous submissions)
- [x] Calendar conflict check blocks scheduling when proposed time overlaps existing event + drive time buffer
- [x] Google Maps drive time is fetched, cached in Redis, and used in conflict calculation
- [x] Drive time fallback fires when Google Maps API is unavailable
- [x] Record lock acquired on edit, heartbeat resets TTL, inactivity timeout releases lock
- [x] Manager can override lock; broken-lock notification sent to original lock holder
- [x] Manual publish button works only when status is `esigned_pending_publish` and signed contract exists
- [x] Sales rep receives email when manager approves; receives notification when customer completes eSign
