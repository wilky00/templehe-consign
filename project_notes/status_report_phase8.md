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

*Sprint 3 next: Admin Reporting Backend (funnel metrics, category breakdown, geographic heatmap, CSV export)*
