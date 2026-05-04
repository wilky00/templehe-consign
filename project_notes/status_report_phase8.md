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

*Sprint 2 next: Public Listing Frontend (React pages, filters, inquiry form, analytics page_view stub)*
