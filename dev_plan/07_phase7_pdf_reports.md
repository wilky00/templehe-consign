# Phase 7 — Dynamic PDF Appraisal Report Generation

> **Prerequisite reading:** `00_overview.md`, `06_phase6_approval_esign.md`
> **Estimated scope:** 2–3 weeks
> **Deliverable:** Fully generated, branded PDF appraisal report covering all required sections; downloadable by customer and internal team

---

## Architecture Notes

- PDF generation runs as an async Cloud Run Job triggered by a Pub/Sub message — never in the API request path
- Library: **WeasyPrint** (Python) for HTML-to-PDF rendering; allows rich templating with Jinja2 and full CSS control
- Template files stored in `api/templates/pdf/`
- Generated PDFs stored in GCS bucket `templeHE-reports/` with path: `reports/{record_id}/{appraisal_id}.pdf`
- Signed URL (15-min expiry) returned to the client for download; PDFs never served directly from the API
- Photo optimization for PDF: images fetched from GCS, re-compressed to 60% JPEG quality at max 800×800px for inline gallery embedding (separate from the originals stored at 80% quality)

---

## Epic 7.1 — PDF Template & Data Assembly

### Feature 7.1.1 — Report Data Assembly Service

**User Story:**
As a developer, I want a dedicated service that assembles all the data required for a PDF report so that the template layer stays clean and data logic is testable.

**Acceptance Criteria:**
- `ReportDataService.build_report_data(appraisal_submission_id) → ReportData` (a Pydantic model)
- `ReportData` model contains all sections needed by the template (see Feature 7.1.2 through 7.1.6)
- If any required section is missing (e.g., no photos), the service raises a `ReportDataIncompleteError` with a specific message indicating what is missing
- `ReportDataService` is fully unit-tested with fixture data

---

### Feature 7.1.2 — Equipment Details Section

**User Story:**
As a customer, I want the PDF to clearly show the factual details of my equipment so that I have an accurate record of what was evaluated.

**Acceptance Criteria:**
- Section renders:
  - Manufacturer / Make
  - Model
  - Serial Number / PIN
  - Model Year
  - Machine Hours (as recorded) + Hours Verified indicator
  - Running Status
  - Cab Type
  - Emissions Tier
  - Overall Cosmetic Condition (label + color-coded badge)
  - Asset Category
  - Attachments/Options present (comma-separated list)
  - Service Records Available (Yes / No)
  - Major Rebuild History (if populated)
  - Transport Notes (if populated)
- All field labels render even if value is empty (shown as "Not recorded")
- Unique Record ID (`THE-XXXXXXXX`) displayed prominently at the top of the report

---

### Feature 7.1.3 — Valuation & Pricing Section

**User Story:**
As a customer, I want the PDF to show the approved purchase offer and consignment price alongside the comparable sales data that supported the valuation so that I can see how the number was arrived at.

**Acceptance Criteria:**
- Section renders:
  - Approved Purchase Offer Amount (formatted as USD currency)
  - Suggested Consignment Price (formatted as USD currency)
  - Overall Condition Score (decimal + score band label)
  - Score breakdown table: each component name, raw score (0–5), weight (%), weighted contribution
  - Marketability Rating (label)
  - Comparable Sales table (if any pinned comps exist): Sale Price, Sale Date, Make/Model/Year, Hours, Source
  - Red Flags Summary (if `management_review_required = true` or any flags triggered) — rendered as a clearly labeled notice box, not buried in text
  - Manager Notes (if populated)
  - Appraisal Date

---

### Feature 7.1.4 — Verified Photography Gallery

**User Story:**
As a customer and as TempleHE management, I want the PDF to include a photo gallery of all required photos taken by the appraiser so that the report is a complete record of the equipment's condition.

**Acceptance Criteria:**
- Gallery section renders all `AppraisalPhoto` records associated with the `AppraisalSubmission`
- Photos are displayed in a grid layout (2 columns on A4, 3 columns on US Letter — determined by `AppConfig('pdf_page_size')`)
- Each photo cell shows:
  - The compressed photo image (re-compressed for PDF embedding as described in architecture notes)
  - Slot label (e.g., "Engine Compartment", "Hour Meter")
  - Capture timestamp (formatted: "April 15, 2026 at 10:32 AM")
  - GPS location (formatted: "30.3322° N, 97.7431° W" or city/state if reverse-geocoded)
  - Required photo indicator (checkmark badge for required slots, no badge for optional)
- Photos are sorted: required photos first (in checklist order), then optional photos
- If `gps_missing = true` for a photo, a small warning icon shown with tooltip text: "GPS data unavailable for this photo"
- If `gps_out_of_range = true` (photo taken far from site), a warning icon shown

---

### Feature 7.1.5 — Personnel Information Section

**User Story:**
As a customer, I want the PDF to show who evaluated my equipment and who my sales contact is so that I have direct contact information if I have questions.

**Acceptance Criteria:**
- Section renders for the Appraiser:
  - Full name
  - Title ("Certified Appraiser" or role label from user record)
  - Direct phone number (formatted)
  - Email address
- Section renders for the Sales Representative:
  - Full name
  - Title ("Sales Representative" or role label)
  - Direct phone number (formatted)
  - Email address
- TempleHE company information in the footer of every page:
  - Company name, address, phone, website
  - Logo (stored in GCS, configurable via `AppConfig('company_logo_url')`)
- Both personnel fields pulled from the `User` records linked to `EquipmentRecord.assigned_appraiser_id` and `.assigned_sales_rep_id`
- If either is unassigned, the section shows "Contact TempleHE for information" with the main company phone/email

---

### Feature 7.1.6 — Report Header & Branding

**User Story:**
As TempleHE, I want the PDF to carry professional branding on every page so that it can be presented to customers and lenders with confidence.

**Acceptance Criteria:**
- Page 1 header: TempleHE logo (left), "Heavy Equipment Appraisal Report" title (center), report generation date (right)
- Every page has a footer: TempleHE company name + "Confidential — Generated [date]" + page number (e.g., "Page 2 of 5")
- Color scheme and fonts configurable via `AppConfig('pdf_brand_primary_color')`, `AppConfig('pdf_font_family')` — defaults to TempleHE blue + Inter font
- Report title page: Record ID, Equipment Summary (make/model/year), Customer Name (business), Appraisal Date
- Table of contents on Page 1 if report exceeds 4 pages
- Report is A4 or US Letter format (configurable via `AppConfig('pdf_page_size')`)

---

## Epic 7.2 — Generation Trigger & Storage

### Feature 7.2.1 — PDF Generation Trigger

**User Story:**
As a Sales Rep, I want the system to automatically generate the appraisal PDF when an appraisal is approved so that the report is ready to share with the customer without me having to manually trigger it.

**Acceptance Criteria:**
- When `EquipmentRecord.status` transitions to `approved_pending_esign`, a Pub/Sub message is published to the `pdf-generation` topic (alongside the eSign dispatch — both fire in parallel)
- The `PDFGenerationWorker` Cloud Run Job consumes the message:
  1. Calls `ReportDataService.build_report_data(appraisal_submission_id)`
  2. Renders the Jinja2 HTML template with the report data
  3. Runs WeasyPrint to generate the PDF
  4. Uploads the PDF to GCS: `reports/{record_id}/{appraisal_id}.pdf`
  5. Creates/updates the `AppraisalReport` DB record with `gcs_path`, `generated_at`
  6. Publishes a `pdf-ready` Pub/Sub message
- If `ReportDataIncompleteError` is raised, the job writes the error to `audit_logs` and retries after 30 minutes (max 3 retries)
- `PDFGenerationWorker` unit-tested with a mock `ReportDataService` and a headless WeasyPrint call

---

### Feature 7.2.2 — PDF Access & Download

**User Story:**
As a customer, I want to download my appraisal report as a PDF from my portal so that I have a copy for my records.

**Acceptance Criteria:**
- `GET /api/v1/equipment-records/:id/report/pdf`:
  - Requires auth; ownership check (customer can only fetch their own record's report)
  - If `AppraisalReport.gcs_path` exists: generates a signed GCS URL with 15-minute expiry and returns `{ "download_url": "<signed_url>", "expires_at": "<ISO>" }`
  - If no report yet: returns `202 { "status": "generating", "message": "Your report is being prepared. Please check back in a few minutes." }`
  - Sales, Manager, Admin roles can access any record's report
- Customer portal "Download Report" button (Phase 2.5.1) calls this endpoint; uses the returned URL for a direct `<a href>` download — no proxy through the API
- Internal team can also download from the Equipment Record detail view in the Sales dashboard
- PDF filename formatted as: `TempleHE_Appraisal_THE-XXXXXXXX.pdf`

---

## Phase 7 Completion Checklist

- [ ] `ReportDataService` returns complete `ReportData` for a test submission; raises `ReportDataIncompleteError` when photos or approval data are missing
- [ ] Generated PDF includes all 5 sections: Equipment Details, Valuation & Pricing, Photo Gallery, Personnel Info, Branded Header/Footer
- [ ] Photo gallery in PDF includes EXIF timestamp and GPS coordinates under each image
- [ ] `gps_missing` and `gps_out_of_range` warning icons render correctly
- [ ] Score breakdown table shows all components with correct weights from `AppConfig`
- [ ] PDF generated within 60 seconds of `approved_pending_esign` status transition
- [ ] Generated PDF accessible via signed GCS URL from customer portal; link expires after 15 minutes
- [ ] Re-requesting the download URL generates a new signed URL pointing to the same stored file (no regeneration)
- [ ] `pdf_page_size`, `pdf_brand_primary_color`, `company_logo_url` AppConfig changes are reflected in the next generated PDF
