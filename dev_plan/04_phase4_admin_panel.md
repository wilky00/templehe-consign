# Phase 4 — Admin Panel & Global Configuration Engine

> **Prerequisite reading:** `00_overview.md`, `01_phase1_infrastructure_auth.md`, `03_phase3_sales_crm.md`
> **Estimated scope:** 3–4 weeks
> **Deliverable:** Full Admin panel — global status view, customer DB management, API configuration, remote global variable control (including iOS app settings), lead routing UI, health monitoring

---

## Epic 4.1 — Global Operations View

### Feature 4.1.1 — All Sales & Consignments Dashboard

**User Story:**
As an Admin, I want a single-screen view of all active sales and consignment records across the entire platform so that I can spot bottlenecks, stale records, and team workload imbalances at a glance.

**Acceptance Criteria:**
- Admin dashboard accessible at `/admin/dashboard`
- Aggregate summary cards at top: Total Active Records, Records by Status (count per status), Overdue (records in a status for > configurable threshold, default 7 days), Pending Manager Approval, Pending eSign
- Main table shows all `EquipmentRecord` rows with columns: Record ID, Customer Name, Make/Model, Status, Assigned Sales Rep, Assigned Appraiser, Created Date, Days in Current Status, Last Activity
- Color highlight on rows where `days_in_current_status` exceeds the configured threshold
- Filterable by: status, assigned rep, assigned appraiser, equipment category, date range, overdue flag
- Sortable by any column
- "Days in Current Status" is a computed column, not stored — calculated from `updated_at` of the last status-change audit log entry
- Export to CSV available (filtered view)
- Refreshes every 2 minutes automatically; manual refresh button

---

## Epic 4.2 — Customer Database Management

### Feature 4.2.1 — Customer Record Editing

**User Story:**
As an Admin, I want to view and edit any customer record so that I can correct data entry errors and manage the customer database directly.

**Acceptance Criteria:**
- Customer list at `/admin/customers` — paginated, searchable by name, email, business name, phone
- Clicking a customer opens a full edit form with all profile fields (same fields as customer registration, Feature 2.1.1)
- Admin can update any field without the customer initiating a change request
- Admin can soft-delete a customer record; deletion cascades to `EquipmentRecord` soft-delete but does not delete `AppraisalSubmission` or `AppraisalReport` records (retained for history)
- Edit and delete actions require the Admin to confirm with a modal dialog: *"Are you sure you want to [action] this customer? This cannot be undone from the UI."*
- All admin edits to customer records written to `audit_logs` with `before_state` and `after_state`
- Admin can view a customer's full equipment history and all associated change requests from this view

---

## Epic 4.3 — API & Integration Configuration

### Feature 4.3.1 — Integration Credentials Management

**User Story:**
As an Admin, I want to configure API credentials for Slack, Twilio, SendGrid, and Google Maps from the Admin panel so that I never need a developer to update integration settings in production.

**Acceptance Criteria:**
- Integration config UI at `/admin/integrations`
- Configurable integrations with test-connectivity buttons:
  - **Slack:** Webhook URL (or Bot Token + Channel ID); "Test" button posts a test message to the configured channel
  - **Twilio:** Account SID, Auth Token, From Phone Number; "Test" button sends an SMS to a specified test number
  - **SendGrid:** API Key, From Email Address, From Name; "Test" button sends a test email to the Admin's own email
  - **Google Maps:** API Key; "Test" button validates the key against the Geocoding API with a sample US address
  - **eSign Provider (Stubbed):** Provider name, API Key, Webhook Secret; "Test" button returns *"Provider is stubbed — connection not validated"* until a real provider is integrated (Phase 6)
  - **Valuation API (Stubbed):** Provider name, API Key; "Test" button returns *"Provider is stubbed"* until Phase 5+
- Credentials are written to GCP Secret Manager via the API — they are never stored in the database in plaintext
- The API reads from Secret Manager on startup; a cache with a 5-minute TTL avoids per-request Secret Manager reads
- Credential values are masked in the UI (shown as `••••••••` after save); Admin can click "Reveal" which fetches the value fresh from Secret Manager (logged to `audit_logs`)
- All credential update events written to `audit_logs`

---

## Epic 4.4 — Global Variable Configuration (Remote Control)

### Feature 4.4.1 — Platform-Wide Variable Management

**User Story:**
As an Admin, I want to remotely configure global platform variables from the Admin panel so that I can tune business logic, thresholds, and UI behavior without a code deployment.

**Acceptance Criteria:**
- Config management UI at `/admin/config`
- All variables stored in the `app_config` key/value table (key, value JSONB, category, updated_by, updated_at)
- Admin UI groups variables by category with inline editing (text inputs, toggles, number inputs, multi-select dropdowns — rendering driven by a `field_type` column on `app_config`)
- Categories and configurable keys (minimum set):

**Category: Intake Form**
  - `intake_fields_visible` — JSON array of field keys shown to customers in the intake form
  - `intake_fields_required` — JSON array of field keys that are required vs optional
  - `intake_fields_order` — JSON array defining display order

**Category: Consignment Rules**
  - `consignment_price_change_threshold_pct` — decimal; if customer requests a price change exceeding this %, the Sales Manager must re-approve (e.g., `0.10` = 10%)
  - `stale_record_threshold_days` — integer; records older than this in any status are highlighted in the admin dashboard
  - `default_sales_rep_id` — UUID; fallback assignment when no routing rule matches

**Category: Calendar**
  - `drive_time_fallback_minutes` — integer; flat buffer used when Google Maps API is unavailable
  - `min_appointment_duration_minutes` — integer; minimum appraisal block length (default: 60)

**Category: Notifications**
  - `enable_sms_notifications` — boolean; master toggle for Twilio SMS
  - `enable_slack_notifications` — boolean; master toggle for Slack webhooks
  - `notification_retry_attempts` — integer; max retry attempts for failed dispatches (default: 3)

**Category: Security**
  - `require_2fa_for_roles` — JSON array of role slugs that must have 2FA enabled
  - `session_access_token_ttl_minutes` — integer (default: 15)
  - `session_refresh_token_ttl_days` — integer (default: 7)

- Saving a config value updates the DB record, clears any in-memory cache on the API, and writes to `audit_logs`
- Config values are read by all services via `ConfigService.get(key)` — no direct `app_config` queries outside of this service

---

### Feature 4.4.2 — iOS App Remote Configuration

**User Story:**
As an Admin, I want to remotely configure what the iOS appraiser app requires in the field so that I can add new photo requirements or checklist items without pushing an App Store update.

**Acceptance Criteria:**
- iOS config section within `/admin/config` under category `iOS App`
- Configurable keys per equipment category (one set per category, 15 categories total):
  - `ios_required_photos_<category_slug>` — JSON array of required photo label strings (e.g., `["4 corner exterior", "Serial plate", "Hour meter", ...]`)
  - `ios_required_checklist_fields_<category_slug>` — JSON array of checklist field keys the appraiser must complete
  - `ios_optional_fields_<category_slug>` — JSON array of optional field keys shown but not blocking submission
- Bulk edit: Admin can paste a JSON array directly into a textarea for advanced editing
- Each category config has a "Preview" button that renders a read-only simulation of what the iOS app will show for that category
- iOS app fetches its configuration from `GET /api/v1/config/ios` (public within authenticated iOS session) — returns the full `AppConfig` subset for `category = 'iOS App'`
- `GET /api/v1/config/ios` response includes a `config_version` hash; iOS app compares this hash on each launch and only re-fetches if the hash has changed (reduces unnecessary network calls)
- Config version hash is a SHA-256 of the serialized config JSON
- Changes to iOS config are visible to the app immediately on next launch or foreground event — no app update required

---

## Epic 4.5 — Lead Routing Configuration UI

### Feature 4.5.1 — Routing Rule Builder

**User Story:**
As an Admin, I want a visual interface to create and manage lead routing rules so that I don't need to write SQL or call an API directly to set up assignment logic.

**Acceptance Criteria:**
- Lead routing UI at `/admin/routing`
- Rule list shows all rules ordered by `priority` with drag-to-reorder (priority auto-updates on reorder)
- "New Rule" button opens a rule creation wizard with:
  - Step 1: Rule Type selection (Ad Hoc | Geographic | Round Robin)
  - Step 2: Conditions — rendered dynamically based on rule type:
    - **Ad Hoc:** Customer email domain (text input, e.g., `acmeconstruction.com`) OR specific Customer ID (lookup field)
    - **Geographic:** Multi-select for State(s) | ZIP list (textarea, comma-separated) | Metro Area (named area from a predefined list + radius slider in miles)
    - **Round Robin:** Ordered list of Sales Reps (drag-to-reorder list); note: this should be the last rule in the waterfall
  - Step 3: Assignment — Sales Rep selector (dropdown, filtered to `sales` role users)
  - Step 4: Review & Save
- Rule can be toggled active/inactive without deleting (status badge on rule list)
- "Test Rule" button: enter a sample customer address/email and see which rule would fire and which rep would be assigned
- Deleting a rule requires confirmation modal
- All rule changes written to `audit_logs`

---

## Epic 4.6 — Platform Health Monitoring

### Feature 4.6.1 — Health Dashboard

**User Story:**
As an Admin, I want a health monitoring view so that I can quickly see if any platform services or integrations are degraded without logging into GCP.

**Acceptance Criteria:**
- Health dashboard at `/admin/health`
- Panels for each service: API (Cloud Run), Database (Cloud SQL), Redis (Memorystore), Pub/Sub (message queue depth), SendGrid, Twilio, Slack, Google Maps, GCS (photo bucket write test)
- Each panel shows: status icon (green/yellow/red), last check time, last error (if any)
- Status check endpoint `GET /api/v1/health` (public, no auth) returns JSON with per-service status — used by Cloud Run's health check probe and the Admin UI
- Health checks run every 30 seconds server-side via a background Cloud Run Job; results stored in Redis for the Admin UI to display without adding health check latency to each UI poll
- If any service shows `red` status, the Admin receives a notification on their preferred channel (rate-limited: max 1 alert per service per 15 minutes)
- Pub/Sub queue depth alert fires if `dead_letter_queue` message count > 0 (means notifications are failing silently)

---

## Epic 4.8 — Dynamic Equipment Category Management

> This Epic replaces the Phase 1 seed-data approach for equipment categories. Categories are no longer fixed — Admins have full CRUD control over every category and all of its attributes. The 15 categories in `01_checklists/` are the default seed data, not a hard limit.

### Feature 4.8.1 — Category CRUD

**User Story:**
As an Admin, I want to create, edit, rename, and deactivate equipment categories from the Admin panel so that I can support new types of equipment (e.g., Forklifts, Aerial Work Platforms, Cranes) or retire categories we no longer handle without any code deployment.

**Acceptance Criteria:**
- Category management UI at `/admin/categories`
- Category list shows all categories with columns: Name, Slug (auto-generated from name, URL-safe), Status (active | inactive), Component Count, Required Photo Count, Created Date
- **Create:** "New Category" button opens a category creation form — only `name` required at creation time; all other attributes (components, photos, etc.) configured in subsequent steps
- **Rename:** Category name editable inline; slug does not auto-update on rename (to avoid breaking existing records) — slug change requires explicit Admin action with a confirmation modal warning: *"Changing the slug will affect all AppConfig keys and iOS config references using this category. Existing appraisal records are not affected."*
- **Deactivate:** Setting a category to `inactive` hides it from the customer intake dropdown and the iOS app category picker; existing `EquipmentRecord` rows with that category are unaffected (historical data preserved)
- **Delete:** Hard delete blocked if any `EquipmentRecord` references the category. Admin sees: *"This category has [N] equipment records and cannot be deleted. Deactivate it instead."*
- Category changes are immediately reflected in: customer intake form dropdown, iOS config endpoint, scoring engine
- All category changes written to `audit_logs`

---

### Feature 4.8.2 — Component Definition & Weight Management

**User Story:**
As an Admin, I want to define the major components for each category and set their scoring weights so that the weighted condition score reflects what actually matters for each machine type.

**Acceptance Criteria:**
- Component management accessible within each category's detail page at `/admin/categories/:slug`
- Component list shows all components for the category with: Name, Weight (%), sortable drag-to-reorder
- **Add Component:** Name (required, text) + Weight % (required, decimal, 0.01–100.00)
- **Edit Component:** Name and weight both editable inline
- **Delete Component:** Removes the component; existing `ComponentScore` records for that component on past appraisals are preserved (orphaned but not deleted — historical integrity)
- **Weight validation:** Running total of all component weights displayed in real-time; a warning banner shows if weights do not sum to 100%: *"Component weights total [X]%. Scoring will normalize to 100% automatically, but it is recommended to balance weights manually."*
- The scoring engine normalizes weights at calculation time: `normalized_weight = weight / sum(all_weights)` — so an imperfect total is non-breaking
- Component order (drag position) controls the display order in the iOS app form and in the PDF report
- Changes take effect for new appraisal submissions immediately; historical submissions retain their original component weights (stored in `component_scores.weight_at_time_of_scoring DECIMAL`)

---

### Feature 4.8.3 — Inspection Prompt Management

**User Story:**
As an Admin, I want to define the inspection prompts (yes/no checklist items) for each category so that appraisers in the field are guided through the specific checks that matter for that machine.

**Acceptance Criteria:**
- Inspection Prompts section within each category detail page
- Prompt list shows all prompts for the category: Prompt Label, Response Type, Required (yes/no), Display Order
- **Add Prompt:** Label (required, text, e.g., "Cold start observed"), Response Type (Yes/No/N-A toggle | Text entry | 1–5 Scale), Required toggle (if required, appraiser cannot submit without answering)
- **Edit Prompt:** All fields editable; changes affect new appraisals only
- **Delete Prompt:** Removes from future appraisal forms; existing answers on past submissions are preserved
- **Reorder:** Drag-to-reorder controls display order in the iOS app
- Maximum of 30 prompts per category (configurable via `AppConfig('max_inspection_prompts_per_category')`, default: 30)
- Changes pushed to iOS via `GET /api/v1/config/ios` on next app launch

---

### Feature 4.8.4 — Attachment / Option Management

**User Story:**
As an Admin, I want to define the list of possible attachments and options for each category so that appraisers can accurately record what is included with the machine.

**Acceptance Criteria:**
- Attachments/Options section within each category detail page
- Attachment list shows: Label, Description (optional), Active status
- **Add Attachment:** Label (required, e.g., "Hydraulic Thumb"), Description (optional)
- **Edit / Deactivate:** Deactivating hides it from the iOS app form for new appraisals; historical records with that attachment checked are unaffected
- No hard limit on attachments per category
- Displayed as multi-select checkboxes in the iOS app and in the appraisal form

---

### Feature 4.8.5 — Required Photo Checklist Management

**User Story:**
As an Admin, I want to define and manage the required photo list for each category so that I can add a new mandatory photo angle (e.g., "Undercarriage Serial Tag") for any machine type without an iOS app update.

**Acceptance Criteria:**
- Required Photos section within each category detail page
- Photo slot list shows: Label, Description, Required toggle, Display Order
- **Add Photo Slot:** Label (required, e.g., "Engine Compartment"), Description (optional helper text shown to appraiser in-app), Required toggle
- **Edit / Delete:** Editable; deleting a required photo slot only affects future appraisals — historical `AppraisalPhoto` records with that slot label are preserved
- **Reorder:** Drag-to-reorder controls display order in the iOS app checklist
- The iOS app's photo checklist rebuilds from this list on each config fetch (same `config_version` hash mechanism as Feature 4.4.2)
- Optional photo slots are also definable (Required = false); they appear in the iOS app after required slots as an "Additional Photos" suggestion list
- The `photo_set_complete` flag on `AppraisalSubmission` is computed as: all slots where `required = true` have a corresponding `AppraisalPhoto` record

---

### Feature 4.8.6 — Red Flag Rule Management

**User Story:**
As an Admin, I want to define the red flag rules for each category so that I can add new automatic management review triggers as we learn what issues are most critical for specific machine types.

**Acceptance Criteria:**
- Red Flag Rules section within each category detail page
- Rule list shows: Condition Field, Condition Value, Triggered Action, Active status
- **Add Rule:** 
  - Condition Field (dropdown of all boolean and enum fields on `AppraisalSubmission`): e.g., `structural_damage`, `active_major_leak`, `running_status`, `hours_verified`, `missing_serial_plate`
  - Condition Operator: `equals` (for enums) | `is true` (for booleans) | `is false`
  - Condition Value: rendered based on field type (e.g., for `running_status`, a dropdown showing Running/Partial/Non-Running)
  - Actions (multi-select checkboxes):
    - Set `management_review_required = true`
    - Set `hold_for_title_review = true`
    - Downgrade `marketability_rating` by one band
    - Set `marketability_rating` to a specific value (override)
    - Append to `review_notes` (with configurable note text)
  - Rule Label / Description (optional internal note)
- **Edit / Deactivate:** Changes apply to new submissions only
- Default rules for all 15 seeded categories are pre-populated from `06_scoring_and_rules_logic.csv`; Admins can add to or modify these defaults

---

### Feature 4.8.7 — Category Export & Import

**User Story:**
As an Admin, I want to export a category's full configuration as JSON and import it to another environment so that I can set up a new category in dev and promote it to production without rebuilding it manually.

**Acceptance Criteria:**
- "Export Category" button on each category detail page downloads a JSON file containing: category name, slug, components (with weights), inspection prompts, attachments, required photo slots, red flag rules
- "Import Category" button at `/admin/categories` accepts a JSON file in the same schema; validates the file and shows a preview before import
- Import creates a new category if the slug does not exist; shows a conflict warning if the slug already exists (option to overwrite or rename on import)
- Import/export events written to `audit_logs`

---

## Epic 4.7 — Admin Reporting Tab (Overview)

> Note: Full reporting implementation is in Phase 8. This Epic provisions the tab skeleton and data access layer so Phase 8 can build directly on it.

### Feature 4.7.1 — Reporting Tab Scaffold

**User Story:**
As an Admin, I want a dedicated Reports tab in the Admin panel so that I know exactly where to go for business performance data.

**Acceptance Criteria:**
- Reports tab accessible at `/admin/reports`
- Tab renders four sub-sections (placeholders in Phase 4, populated in Phase 8):
  1. Sales by Period (Month / Quarter / Year)
  2. Sales by Equipment Type and Location
  3. User & Portal Traffic Metrics
  4. Export Center (CSV/PDF downloads)
- Each sub-section shows a loading placeholder with label: *"Report data coming in Phase 8"*
- The reporting data access role `reporting` can reach `/admin/reports` but not other `/admin/*` routes

---

## Phase 4 Completion Checklist

- [ ] Admin dashboard shows all active records with correct days-in-status calculation
- [ ] Admin can edit and soft-delete customer records; changes appear in audit log with before/after state
- [ ] Slack, Twilio, SendGrid, Google Maps credentials saved to Secret Manager — not the database
- [ ] "Test" buttons for each integration work and return correct success/failure messages
- [ ] `intake_fields_visible` AppConfig change is immediately reflected in the customer intake form (Phase 2) without code deploy
- [ ] `consignment_price_change_threshold_pct` AppConfig change is reflected in the manager approval flow (Phase 6) without code deploy
- [ ] iOS config endpoint returns `config_version` hash; iOS app only re-fetches on hash change
- [ ] Admin can drag-reorder routing rules and priority updates correctly
- [ ] "Test Rule" function returns the correct rule match and rep assignment for sample inputs
- [ ] Health dashboard reflects real service status; red status triggers admin notification (rate-limited)
- [ ] `reporting` role user can access `/admin/reports` but gets 403 on all other `/admin/*` routes
- [ ] Admin creates a new category ("Forklifts") → category appears in customer intake dropdown and iOS config endpoint immediately (no deploy)
- [ ] Admin adds a component with a weight to the new category → component appears in iOS app form for that category
- [ ] Admin adds a required photo slot → iOS config `config_version` hash changes → iOS app reflects new slot on next launch
- [ ] Admin adds a red flag rule (e.g., `hours_verified = false → append review note`) → submitting an appraisal with that condition triggers the rule
- [ ] Admin attempts to hard-delete a category with existing equipment records → deletion blocked, helpful error shown
- [ ] Component weights that don't sum to 100% → scoring engine normalizes them; warning banner shown in Admin UI
- [ ] Category JSON exported → imported into a fresh test environment → all components, prompts, photos, rules, and attachments present correctly
