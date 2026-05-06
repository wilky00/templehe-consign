# Phase 8 Status Report — Analytics & Public Listing Page

Branch: `phase8-analytics-listing`
Started: 2026-05-04

---

## Sprint 1 — Public Listing + Analytics Backend

**Completed:** 2026-05-04

### What was built

| File | Type | Summary |
|---|---|---|
| `api/schemas/public_listing.py` | NEW | ListingCard, ListingDetail, InquiryCreate/Response, ListingPatch |
| `api/schemas/analytics.py` | NEW | AnalyticsEventCreate/Response with PII validator |
| `api/services/listing_service.py` | NEW | Filter/paginate/sort listings; joins AppraisalSubmission for verified fields |
| `api/services/inquiry_service.py` | NEW | Create Inquiry row + send buyer confirmation + rep alert |
| `api/services/email_service.py` | MODIFY | Added `send_inquiry_confirmation_email`, `send_inquiry_alert_email` |
| `api/routers/public.py` | NEW | `GET /public/listings`, `GET /public/listings/:id`, `POST .../inquiries` |
| `api/routers/analytics.py` | NEW | `POST /analytics/event`; drops staff role events |
| `api/routers/sales.py` | MODIFY | `PATCH /sales/equipment/{id}/listing` |
| `api/schemas/sales.py` | MODIFY | `ListingPatchOut` |
| `api/main.py` | MODIFY | Registered public + analytics routers |
| `api/tests/integration/test_public_listings.py` | NEW | 10 tests |
| `api/tests/integration/test_inquiries.py` | NEW | 10 tests |
| `api/tests/integration/test_analytics_events.py` | NEW | 6 tests |

### Test results

- Unit: 205/205 ✓
- Integration: 570/570 ✓ (26 new tests, 0 regressions)

### Key decisions

- **Listing data source:** `AppraisalSubmission` (appraiser-verified `make`, `model`, `year`, `hours_condition`, `marketability_rating`, etc.) with fallback to `customer_*` fields on `EquipmentRecord` when no approved submission exists.
- **Condition filter** only matches listings with an approved `AppraisalSubmission`. Listings without one are excluded — correct behavior for a filtered catalog.
- **Bot prevention:** honeypot field `web_address`. Bots get 201 with a fake ID; no `Inquiry` row is written.
- **Analytics drop:** events from staff roles return `recorded: false` and are not written to `analytics_events`.
- **Rate limits:** 60/min/IP for listing browse; 5/hr/IP for inquiry submit.

### Bugs found and fixed during sprint

1. `Category` → `EquipmentCategory` model name (wasn't matching)
2. `inquiry_service` rep query missing `select_from(PublicListing)` — caused `UndefinedTableError`
3. `customer_make`/`customer_model`/`customer_year` used in tests instead of `make`/`model`/`year` (which are on `AppraisalSubmission`)
4. Customer seed needed `invite_email` to satisfy `ck_customers_user_or_invite` constraint
5. `intake_pending` is not a valid `EquipmentRecord.status` — changed to `new_request`
6. Honeypot test captured `listing.id` before rollback to avoid lazy-load `MissingGreenlet` error

### Open issues / follow-ups

None — Sprint 1 is clean.

---

---

## Sprint 2 — Public Listing Frontend

**Completed:** 2026-05-04

### What was built

| File | Type | Summary |
|---|---|---|
| `web/src/api/listings.ts` | NEW | Typed client for all public listing + inquiry + listing PATCH endpoints |
| `web/src/services/analytics.ts` | NEW | `trackEvent()` + `usePageView()` route-change hook; fire-and-forget |
| `web/src/pages/PublicListings.tsx` | NEW | `/listings` — filter sidebar (price/condition), sort, pagination, URL-encoded state |
| `web/src/pages/PublicListingDetail.tsx` | NEW | `/listings/:id` — specs, notes, price, inquiry form, SEO meta via react-helmet-async |
| `web/src/App.tsx` | MODIFY | Added public `/listings` + `/listings/:id` routes (no ProtectedRoute) |
| `web/src/pages/SalesEquipmentDetail.tsx` | MODIFY | `ListingManagementCard` — price update + mark-sold + withdraw |
| `web/src/pages/PublicListings.test.tsx` | NEW | 17 Vitest tests (list, detail, inquiry form, validation, empty/error states) |
| `web/e2e/phase8_listing.spec.ts` | NEW | 5 Playwright E2E scenarios |
| `scripts/seed_e2e_phase8.py` | NEW | Phase 8 E2E fixture seeder |
| `web/e2e/helpers/api.ts` | MODIFY | Added `seedPhase8()` |
| `web/src/test/render.tsx` | MODIFY | Added `HelmetProvider` wrapper for tests |
| `web/src/test/handlers.ts` | MODIFY | Added `POST /analytics/event` MSW no-op handler |
| `web/src/main.tsx` | MODIFY | Added `HelmetProvider` to app bootstrap |

### Test results

- Frontend unit: 148/148 ✓ (17 new, 0 regressions)
- Backend unit: 205/205 ✓ (unchanged)
- Backend integration: 570/570 ✓ (unchanged)

### Key decisions

- **No ProtectedRoute** on `/listings` + `/listings/:id` — public catalog is unauthenticated. Token sent if present (analytics benefit) but never required.
- **SEO:** SPA + `react-helmet-async` (not Next.js). Sufficient for Google crawl; avoids framework change.
- **Filter state in URL:** `useSearchParams` — makes filters bookmarkable and shareable.
- **Analytics service dir:** `web/src/services/` (new directory) for non-API concerns. Keeps analytics out of the API client layer.
- **Inquiry honeypot:** hidden `web_address` field in the form (via `sr-only` + `aria-hidden`). Backend silently drops it.

### Bugs found and fixed during sprint

1. `HelmetProvider` not in `renderWithProviders` — `<Helmet>` threw in every test; fixed by adding to `render.tsx`
2. `POST /analytics/event` not mocked in MSW handlers — MSW warned on every test; fixed by adding no-op handler to `handlers.ts`
3. Two tests used `getByText("2019 Caterpillar 336")` — matched both the card title AND subtitle (year + make + model), causing "found multiple elements" error; fixed by using `getAllByText(...).length > 0`

### Open issues / follow-ups

None — Sprint 2 is clean.

---

---

## Sprint 3 — Admin Reporting Backend

**Completed:** 2026-05-05

### What was built

| File | Type | Summary |
|---|---|---|
| `api/schemas/reporting.py` | NEW | SalesByPeriodRow/Response, SalesByTypeRow/Response, SalesByStateRow/Response, PortalTrafficResponse, PageViewMetric |
| `api/services/reporting_service.py` | NEW | sales_by_period, sales_by_type, sales_by_state, portal_traffic, export_csv |
| `api/routers/admin_reports.py` | NEW | GET /admin/reports/sales-by-period, sales-by-type, sales-by-state, portal-traffic; GET /admin/reports/export |
| `api/main.py` | MODIFY | Registered admin_reports_router |
| `api/tests/integration/test_admin_reports.py` | NEW | 18 tests |

### Test results

- Unit: 205/205 ✓ (unchanged)
- Integration: 588/588 ✓ (18 new tests, 0 regressions)

### Key decisions

- **CSV export is synchronous:** Returns a `StreamingResponse` (text/csv) directly rather than the async job + signed URL pattern described in the dev plan. Row counts in this POC are small; async jobs are a carry-forward for when production data grows past 5 000 rows.
- **Sales by Period buckets approved submissions:** The `approved_at` timestamp on `AppraisalSubmission` (status=`approved`) is the authoritative "closed deal" date, not `PublicListing.published_at`.
- **Sales by Type requires category_id:** Records without a category are excluded from the by-type report — correct behavior since uncategorized records haven't gone through appraisal.
- **Portal traffic excludes no user segment filtering yet:** The `user_segment` query param is wired to the endpoint but the service reads all events regardless of segment. Full new/returning segmentation requires session-level first-seen tracking; flagged as a carry-forward.
- **RBAC:** All 5 endpoints gate on `require_roles("admin", "reporting")`. The `reporting` role slug was confirmed seeded in the test conftest and migrations.

### Bugs found and fixed during sprint

1. Test seeded "Excavator" category — not in the 3-category bundle (Dozers, Backhoe Loaders, Articulated Dump Trucks). Changed seed helper default to "Dozers".

### Open issues / follow-ups

- CSV export async job pattern for > 5 000 rows (dev plan Feature 8.1.4 Export Center)
- `user_segment` new/returning filter in `portal_traffic` (requires session first-seen tracking)

---

---

---

## Sprint 4 — Admin Reporting Frontend

**Completed:** 2026-05-05

### What was built

| File | Type | Summary |
|---|---|---|
| `web/package.json` | MODIFY | Added `recharts@3.8.1` |
| `web/src/api/reports.ts` | MODIFY | Appended Phase 8 admin types + getSalesByPeriod/Type/State, getPortalTraffic, downloadReportCsv |
| `web/src/pages/AdminReports.tsx` | MODIFY | Replaced placeholder — 4 real tab components with charts, tables, filters, CSV export |
| `web/src/services/analytics.ts` | MODIFY | Added `useFormAnalytics(formName)` hook |
| `web/src/App.tsx` | MODIFY | Wired `usePageView()` for auto page_view tracking on all route changes |
| `web/src/pages/IntakeForm.tsx` | MODIFY | Wired `useFormAnalytics("equipment_intake")` into form mount + mutation success |
| `web/src/pages/AdminReports.test.tsx` | NEW | 12 Vitest tests |
| `web/src/test/handlers.ts` | MODIFY | Added MSW handlers for 5 new report endpoints |
| `scripts/seed_e2e_phase8_reporting.py` | NEW | E2E seeder (admin user + approved records + analytics events) |
| `web/e2e/helpers/api.ts` | MODIFY | Added `seedPhase8Reporting()` helper |
| `web/e2e/phase8_analytics_reporting.spec.ts` | NEW | 5 E2E acceptance scenarios |

### Test results

- Frontend unit: 160/160 ✓ (12 new, 0 regressions)
- Backend unit: 205/205 ✓ (unchanged)
- Backend integration: 588/588 ✓ (unchanged)

### Key decisions

- **Choropleth map deferred** — The dev plan specified a D3/GeoJSON state map for By Location. A sortable state table delivers the same data. Carry-forward to a later sprint when/if visual mapping is prioritized.
- **PDF export from reports deferred** — Would require a distinct WeasyPrint template from the appraisal PDF. Carry-forward.
- **`useFormAnalytics` is single-step aware** — Fires `form_step_start` on mount (not first keystroke) since the IntakeForm is a single-card form, not a multi-step wizard.
- **Sub-view switcher in Type/Location tab** — Uses a pill-style `role="tablist"` (not the outer page tabs) to switch between By Type and By State views within the same tab panel.
- **`downloadReportCsv` bypasses `request()`** — Uses raw `fetch` + `URL.createObjectURL` so the browser triggers the native save dialog. The auth token is still included from Zustand `getState()`.

### Bugs found and fixed during sprint

None — Sprint 4 was clean on first run (12/12 tests passed without changes).

### Open issues / follow-ups

- Choropleth state map visualization (D3/react-simple-maps)
- PDF export from admin reports (distinct WeasyPrint template)
- CSV async job for Export Center (> 5,000 rows; flagged in Sprint 3)
- `user_segment` new/returning filter in portal traffic (requires session first-seen tracking)
