# Phase 8 — Analytics, Reporting & Public Consignment Listing Page

> **Prerequisite reading:** `00_overview.md`, `04_phase4_admin_panel.md`
> **Estimated scope:** 3–4 weeks
> **Deliverable:** Admin reporting suite (sales by period/type/location, user traffic), portal analytics instrumentation, public-facing consignment listing page integrated with the existing TempleHE website

---

## Epic 8.1 — Admin Reporting Suite

### Feature 8.1.1 — Sales by Period Report

**User Story:**
As an Admin, I want to generate sales reports by month, quarter, and year so that I can present performance summaries to leadership and track revenue trends over time.

**Acceptance Criteria:**
- Report accessible at `/admin/reports` → "Sales by Period" tab
- Controls: Period Type selector (Month | Quarter | Year), date range selector, optional filter by Sales Rep
- Report renders a summary table with columns:
  - Period label (e.g., "Q1 2026", "March 2026")
  - Total Equipment Records Published
  - Total Records by Acquisition Path (Consignment count / Direct Purchase count)
  - Aggregate Approved Purchase Offer value (sum, USD)
  - Aggregate Suggested Consignment Price (sum, USD)
  - Average time from `new_request` to `published` (days)
- Line chart showing Published count per period (using a charting library — Recharts or Chart.js on the frontend)
- Bar chart showing Consignment vs Direct Purchase split per period
- "Export CSV" button exports the current filtered view
- "Export PDF" button generates a branded summary PDF (uses the same WeasyPrint pipeline from Phase 7 with a report-specific template)
- Data queried from `equipment_records` joined with `appraisal_submissions`; no raw SQL in route handlers — goes through a `ReportingService`

---

### Feature 8.1.2 — Sales by Equipment Type & Location Report

**User Story:**
As an Admin, I want to see which equipment categories and geographic markets are driving the most volume so that we can focus marketing and hiring in the right areas.

**Acceptance Criteria:**
- Report accessible at `/admin/reports` → "By Type & Location" tab
- Two sub-views:
  **By Equipment Type:**
  - Table: Equipment Category, Record Count, Published Count, Avg. Overall Score, Avg. Approved Offer, Avg. Consignment Price
  - Sortable by any column
  - Pie/donut chart showing record count distribution across categories
  
  **By Location:**
  - Grouping options: State | Metro Area (defined from routing rule areas) | Sales Rep Territory
  - Table: Location, Record Count, Published Count, Avg. Offer, Top Equipment Category
  - US choropleth map visualization (state-level) using D3 or a GeoJSON map component — color intensity by record count; clicking a state filters the table
- Date range filter applies to both sub-views
- Export CSV available for each sub-view
- Location data derived from `customers.business_address` state/zip — parsed and stored as `customers.state` and `customers.zip` on Customer creation (backfilled migration for existing records)

---

### Feature 8.1.3 — User & Portal Traffic Metrics Report

**User Story:**
As an Admin, I want to see how customers are interacting with the portal so that I can identify friction points, high-exit pages, and engagement trends.

**Acceptance Criteria:**
- Report accessible at `/admin/reports` → "Portal Traffic" tab
- Metrics tracked and displayed:
  - Total portal sessions (count + trend vs. prior period)
  - Unique users (authenticated)
  - Page views by page: `/portal/dashboard`, `/portal/submit`, `/portal/equipment/:id`, `/portal/profile`
  - Average time on page (seconds) per page
  - Form abandonment rate on the equipment intake form (sessions that started Step 1 but did not complete Step 3)
  - Click-to-download rate on PDF report (% of published records where customer downloaded the PDF)
  - Change request submission count by type
- Data collection: a lightweight server-side analytics event log (`analytics_events` table: `session_id`, `user_id`, `event_type`, `page`, `metadata JSONB`, `created_at`) — no third-party analytics scripts required (privacy-friendly)
- Events captured by the frontend via `POST /api/v1/analytics/event` (fire-and-forget, no blocking)
- Events: `page_view`, `form_step_start`, `form_step_complete`, `form_abandon`, `pdf_download_click`, `change_request_start`, `change_request_submit`
- Analytics events never contain PII in the `metadata` field — only page names, step numbers, record category labels
- Date range filter + optional user segment filter (new users vs. returning)
- Export CSV available

---

### Feature 8.1.4 — Report Export Center

**User Story:**
As a Reporting User, I want a single place to generate and download any report as a CSV or PDF so that I can share data with stakeholders who don't have system access.

**Acceptance Criteria:**
- Export Center accessible at `/admin/reports` → "Export Center" tab
- Lists all available report types with "Generate CSV" and "Generate PDF" buttons per report
- Large reports (> 5000 rows) are generated asynchronously: user clicks "Generate", receives a notification when ready, downloads via a signed URL (same pattern as appraisal PDFs)
- Generated report files stored in GCS with a 7-day TTL (auto-deleted; not intended for permanent storage)
- Download links expire after 24 hours
- All export actions written to `audit_logs` (who requested what, when)

---

## Epic 8.2 — Analytics Instrumentation (Frontend)

### Feature 8.2.1 — Client-Side Analytics Event Capture

**User Story:**
As an Admin, I want page-level and interaction-level analytics captured automatically so that I don't need to manually instrument every new page.

**Acceptance Criteria:**
- A shared `AnalyticsService` (TypeScript module) wraps `POST /api/v1/analytics/event` calls
- Automatic page view tracking via React Router `useLocation` effect — fires on every route change
- Time-on-page calculated from route enter to route exit; sent on route leave
- Form instrumentation utility: `useFormAnalytics(formName)` hook that wraps standard form state and fires `form_step_start`, `form_step_complete`, `form_abandon` events
- No third-party analytics scripts (no Google Analytics, no Segment) — all data stays on-platform
- Events are batched client-side and sent in a single request every 30 seconds or on page unload (using `navigator.sendBeacon` for unload reliability)
- Analytics events are NOT sent for Admin or internal user sessions (filtered by role on the backend) — metrics should reflect customer behavior only

---

## Epic 8.3 — Public Consignment Listing Page

### Feature 8.3.1 — Public Inventory Listing Page

**User Story:**
As a prospective equipment buyer, I want to browse Temple Heavy Equipment's current consignment inventory so that I can find machines that match my needs.

**Acceptance Criteria:**
- Public listing page lives at `/listings` within this platform — it is a standalone page, independent of the existing TempleHE website. No integration between the two at this time.
- Renders all `PublicListing` records where `status = active`
- Each listing card shows: equipment category, make/model/year, hours, overall condition label, asking (consignment) price, primary photo (first required photo from the appraisal), location city/state, listing date
- Filterable by: equipment category (multi-select), condition (Excellent | Good | Fair | Poor), price range (slider), location (State dropdown), hours range (slider)
- Sortable by: newest first, price low–high, price high–low, hours low–high
- Paginated at 24 listings per page; URL-encoded filter state (shareable/bookmarkable links)
- Each listing card links to a detail page at `/listings/:listing_id`
- Listing detail page shows:
  - All equipment details (make, model, serial, year, hours, condition, attachments)
  - Full photo gallery (all required photos from the appraisal)
  - Asking price (consignment)
  - "Contact Sales" button — opens an inquiry form (name, email, phone, message) that creates a lead in the system and notifies the assigned Sales Rep
  - Assigned Sales Rep name and direct phone number (click-to-call)
  - TempleHE contact information
- SEO-friendly: `<title>`, `<meta description>`, Open Graph tags, and clean URL slugs (e.g., `/listings/2019-cat-336-excavator`)
- Listing page is server-side rendered or uses static generation for SEO (React with Next.js if the listing page is a separate project; or a lightweight server-rendered template from FastAPI if co-located)
- The existing TempleHE website is out of scope — no integration, no shared API calls, no iframe embeds. If that changes in a future phase, it will be explicitly scoped at that time.

---

### Feature 8.3.2 — Listing Management (Admin/Sales)

**User Story:**
As a Sales Rep, I want to manage what appears on the public listing page so that I can take down sold items and update pricing without a developer.

**Acceptance Criteria:**
- `PublicListing` record created automatically when a Sales Rep publishes (Feature 3.1.4)
- `PublicListing` fields: `equipment_record_id`, `listing_title` (auto-generated: "Year Make Model"), `asking_price`, `primary_photo_gcs_path`, `status` (`active | sold | withdrawn`), `published_at`, `sold_at`
- Sales Rep can update `asking_price` on the public listing from the Equipment Record detail view; if the change exceeds the consignment price change threshold (AppConfig), re-approval is triggered (Feature 6.2.2)
- Sales Rep can set `status = sold` (marks it as sold, removes from public listing, updates the record)
- Sales Rep can set `status = withdrawn` (removes from public listing without marking sold)
- Admin can bulk-update listing status
- `GET /api/v1/public/listings` — public endpoint, no auth required, returns active listings only; rate-limited at 60 req/min per IP
- `GET /api/v1/public/listings/:id` — public, no auth, returns single listing detail

---

### Feature 8.3.3 — Inquiry Form & Lead Capture

**User Story:**
As a Sales Rep, I want to be notified when a prospective buyer submits an inquiry on a public listing so that I can respond quickly while their interest is high.

**Acceptance Criteria:**
- Inquiry form on the listing detail page collects: First Name, Last Name, Email, Phone, Message (optional)
- `POST /api/v1/public/inquiries` (no auth required) creates an `Inquiry` record linked to the `PublicListing`
- On submission:
  - The assigned Sales Rep receives a notification (preferred channel): *"New inquiry on [Make Model] listing from [Name] — [email] / [phone]"*
  - The buyer receives an automated confirmation email: *"Thank you for your interest in [Make Model]. A TempleHE sales representative will be in touch shortly."*
- Inquiry form is rate-limited (5 submissions per IP per hour) to prevent spam
- CAPTCHA or honeypot field on the form to reduce bot submissions
- Inquiry records accessible to Sales team from the Equipment Record detail view

---

## Phase 8 Completion Checklist

- [ ] Sales by Period report generates correct counts and aggregate values for a test dataset; CSV export matches table data
- [ ] Sales by Equipment Type correctly groups and sums across all 15 categories
- [ ] US state choropleth map renders and filters correctly on state click
- [ ] Portal traffic metrics are collected from customer sessions but not from admin/sales sessions
- [ ] Form abandonment tracking fires correctly when a customer leaves the intake form mid-way
- [ ] Public listing page renders at `/listings`; filters work; URL state is bookmarkable
- [ ] SEO meta tags and Open Graph tags present on both `/listings` and `/listings/:id`
- [ ] Sales Rep can mark a listing as `sold`; it disappears from public page immediately
- [ ] Inquiry form submission notifies Sales Rep on their preferred channel within 60 seconds
- [ ] Inquiry form rate-limiting blocks > 5 submissions per IP per hour
- [ ] `GET /api/v1/public/listings` rate-limited at 60 req/min; returns only `active` listings
- [ ] Export Center generates async report for large datasets; download link delivered via notification
