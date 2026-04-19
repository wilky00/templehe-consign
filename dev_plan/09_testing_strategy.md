# Testing Strategy — End-to-End, Integration & Phase Gates

> **Prerequisite reading:** `00_overview.md`
> **Scope:** Applies to every phase. Read this file before starting any phase's implementation.
> **Philosophy:** Tests are part of the feature, not an afterthought. A phase is not complete until its E2E gate passes in CI.

---

## 1. Testing Pyramid

```
        [E2E Tests]          — Playwright (web), XCUITest (iOS)
       /            \          Per-phase gate; runs in CI on merge to main
      /              \
   [Integration Tests]       — FastAPI TestClient + real DB (test schema)
  /                  \         Per-feature; runs in CI on every PR
 /                    \
[Unit Tests]                  — pytest (API), Vitest (web), XCTest (iOS)
                                Per-function; runs on every commit
```

All three layers run in CI. A PR cannot merge if any layer fails. A phase gate (E2E) blocks promotion to `staging` if it fails.

---

## 2. Unit Testing Standards

### API (Python/pytest)
- All service classes (`ScoringService`, `RedFlagService`, `LeadRoutingService`, `ReportDataService`, `NotificationService`, etc.) must have 100% unit test coverage of their business logic
- Use `pytest-asyncio` for async functions
- Database calls mocked with `unittest.mock` or `pytest-mock` — unit tests never touch a real DB
- Run with: `make test-unit-api`
- Coverage enforced: `--cov=api --cov-fail-under=85`

### Web Frontend (TypeScript/Vitest)
- All utility functions, hooks (`useFormAnalytics`, `useRecordLock`, etc.), and non-trivial components tested
- React components tested with `@testing-library/react`
- API calls mocked with `msw` (Mock Service Worker)
- Run with: `make test-unit-web`

### iOS (Swift/XCTest)
- All service classes (`ScoringService`, `SyncManager`, `ConfigManager`, `EXIFValidator`, `ImageCompressor`) unit tested
- Core Data operations tested with an in-memory store (`NSInMemoryStoreType`)
- Network calls mocked with a `URLProtocol` stub
- Run with: `make test-unit-ios`

---

## 3. Integration Testing Standards

### API Integration Tests
- Use FastAPI `TestClient` against a real PostgreSQL test database (separate schema: `templeHE_test`)
- Test database seeded fresh before each test module run; torn down after
- Redis uses a separate test database index (index 15)
- Every API endpoint has at minimum:
  - Happy path: correct input → correct response + correct DB state
  - Auth failure: missing or invalid token → 401
  - RBAC failure: wrong role → 403
  - Validation failure: missing required field → 400 with human-readable message
- Run with: `make test-integration-api`

### Key integration test suites by phase:
- Phase 1: `test_auth.py`, `test_rbac.py`, `test_audit_log.py`
- Phase 2: `test_customer_registration.py`, `test_equipment_intake.py`, `test_change_requests.py`, `test_notifications.py`
- Phase 3: `test_lead_routing.py`, `test_calendar_scheduling.py`, `test_record_locking.py`
- Phase 4: `test_app_config.py`, `test_ios_config.py`, `test_routing_rules.py`
- Phase 5: `test_appraisal_submission.py`, `test_photo_upload.py`, `test_valuation_search.py`
- Phase 6: `test_scoring_engine.py`, `test_red_flags.py`, `test_approval_workflow.py`, `test_esign_webhook.py`
- Phase 7: `test_pdf_generation.py`, `test_report_data_service.py`
- Phase 8: `test_reporting_queries.py`, `test_public_listings.py`, `test_inquiry_flow.py`

---

## 4. E2E Testing — Web (Playwright)

### Setup
- Framework: **Playwright** (TypeScript)
- Tests live in `/web/e2e/`
- Target: staging environment (deployed after each phase merge)
- Test user accounts seeded in staging DB before E2E run (via `scripts/seed_e2e_users.py`)
- Run with: `make test-e2e-web`

### Phase-Specific E2E Gates

Each gate must pass before a phase is marked complete in CI.

---

#### Phase 1 Gate — Auth & RBAC
File: `e2e/phase1_auth.spec.ts`

- [ ] New user registers with email/password → verification email received (stub email service in staging) → clicks link → logs in successfully
- [ ] Registered user cannot log in before email verification (403 returned, friendly message shown)
- [ ] Google SSO login flow completes and redirects to dashboard
- [ ] 2FA setup: TOTP QR code shown → code entered → 2FA enabled → subsequent login requires TOTP code
- [ ] Admin invites a new Sales Rep → Sales Rep receives invite email → completes registration → logs in with `sales` role
- [ ] Sales Rep attempts to access `/admin/dashboard` → 403 page rendered (not a blank screen or raw error)
- [ ] Customer attempts to access `/sales/dashboard` → 403 page rendered

---

#### Phase 2 Gate — Customer Portal
File: `e2e/phase2_customer_portal.spec.ts`

- [ ] Customer registers business profile → dashboard loads with empty state and CTA
- [ ] Customer submits equipment intake form (all 3 steps) → confirmation email delivered with `THE-XXXXXXXX` Record ID → record appears on dashboard with status "New Request"
- [ ] Customer selects SMS communication preference → warning text visible before saving
- [ ] Customer opens Equipment Detail view → status timeline renders with current step highlighted
- [ ] Customer submits a Change Request (Update Description type) → assigned Sales Rep receives notification on their configured channel within 60 seconds
- [ ] Customer cannot submit a second change request while one is pending (button disabled, banner shown)
- [ ] Customer attempts to access another customer's record ID → 403

---

#### Phase 3 Gate — Sales CRM & Scheduling
File: `e2e/phase3_sales_crm.spec.ts`

- [ ] Two equipment records submitted by the same customer → Sales dashboard groups them under one customer row
- [ ] Cascade assignment applied to customer group → both child records update to the same Sales Rep and Appraiser
- [ ] New customer submission triggers lead routing → Ad Hoc rule fires (if matching email domain) → correct Sales Rep assigned; audit log entry present
- [ ] New customer in a state with a geographic rule → geographic rule fires; round-robin skipped
- [ ] New customer with no matching rule → round-robin fires; round-robin index increments on second submission
- [ ] Appraiser scheduled for a time slot → second scheduling attempt for same appraiser same time → 409 returned, conflict message shown with suggested next available slot
- [ ] Scheduling with Google Maps drive time: appraiser has a prior appointment 2 hours away; scheduling a new appointment immediately after is blocked; appointment with 3-hour gap succeeds
- [ ] Record lock acquired on edit → second user opens same record → "Currently being edited by [Name]" shown → heartbeat times out → lock auto-releases → second user can now edit
- [ ] Manager breaks lock → first user sees lock-expired banner

---

#### Phase 4 Gate — Admin Panel
File: `e2e/phase4_admin.spec.ts`

- [ ] Admin changes `intake_fields_visible` AppConfig to hide the "Lien Status" field → customer intake form reloads and no longer shows Lien Status (no code deploy)
- [ ] Admin saves Twilio credentials → "Test" button sends SMS to test number and shows success confirmation
- [ ] Admin creates a new geographic routing rule for state "TX" → submitting a Texas customer triggers that rule → audit log shows rule_id
- [ ] Admin drag-reorders routing rules → new priority order persisted → rule evaluation follows new order
- [ ] Admin adds a new equipment category via Category Manager (Epic 4.8) → category appears in customer intake dropdown and in iOS config endpoint
- [ ] Reporting user accesses `/admin/reports` → can view reports tab → cannot access `/admin/config` (403)
- [ ] Health dashboard shows all services green (staging environment); simulating a bad Twilio key shows red status for Twilio panel

---

#### Phase 5 Gate — iOS App (XCUITest)
File: `ios/TempleHEAppraiserTests/E2E/` — runs on iOS Simulator (iPhone 15 Pro, iOS 17)

- [ ] Login with email/password → Dashboard loads showing assigned appraisals
- [ ] Tap a scheduled appraisal → full form loads with correct category-specific fields (Excavator checklist for an Excavator record)
- [ ] Change asset category in form → category-specific section re-renders with the new category's components and inspection prompts
- [ ] Attempt to attach a photo from camera roll → action is blocked; only camera option presented
- [ ] Capture a photo via live camera (simulator camera input) → thumbnail appears in the required slot; EXIF metadata shown
- [ ] Submit appraisal with all required fields and photos completed → submission succeeds in online mode → "Uploaded" badge shown on Dashboard
- [ ] Submit appraisal in offline mode (network disabled in simulator) → status shows "Pending Sync" → re-enable network → background sync triggers → status updates to "Uploaded"
- [ ] Admin changes `ios_required_photos_excavators` AppConfig → app launched fresh → new photo requirement reflected in checklist (no app update)
- [ ] Admin adds a new custom category via Admin Panel → category appears in asset category picker in iOS app

---

#### Phase 6 Gate — Approval & eSign
File: `e2e/phase6_approval_esign.spec.ts`

- [ ] Appraiser submits a complete appraisal → Manager approval queue shows the record → Manager enters purchase offer and approves → Sales Rep receives approval email
- [ ] Appraisal with `structural_damage = true` → red flag badge shown in approval queue → marketability downgraded one band → "Management Review Required" shown on record
- [ ] `missing_serial_plate = true` → "Hold for Title Review" blocks approval until Manager checks the confirmation checkbox
- [ ] Manager approves → eSign stub email sent to customer → customer clicks stub signing link → webhook fires → `ConsignmentContract.signed_at` populated → Sales Rep receives "signed" notification
- [ ] Sales Rep clicks "Publish" after eSign → status = `published` → record no longer in `esigned_pending_publish` queue
- [ ] Customer submits price change > threshold % → Manager re-approval queue entry created → Manager re-approves → workflow continues

---

#### Phase 7 Gate — PDF Reports
File: `e2e/phase7_pdf.spec.ts`

- [ ] Full workflow from intake → approval → eSign → publish triggers PDF generation → `AppraisalReport.generated_at` is populated within 60 seconds of approval
- [ ] Customer opens Equipment Detail view for a published record → "Download Report" button present → clicking returns a signed URL → file downloads and opens as a valid PDF
- [ ] Generated PDF contains all 5 sections: Equipment Details, Valuation & Pricing, Photo Gallery, Personnel Information, branded header/footer
- [ ] At least 3 required photos from the appraisal appear in the gallery with EXIF timestamp and GPS coordinates
- [ ] Requesting the download URL a second time returns a new signed URL pointing to the same file (PDF not regenerated)

---

#### Phase 8 Gate — Analytics & Public Listing
File: `e2e/phase8_listing_analytics.spec.ts`

- [ ] Published listing appears on `/listings` page within 5 seconds of Sales Rep publishing
- [ ] Filter by equipment category → listing count updates correctly → URL reflects filter state → reloading the URL preserves filters
- [ ] Inquiry form submitted on a listing detail page → Sales Rep receives notification → buyer receives confirmation email
- [ ] Inquiry form rate-limited: submitting 6 times in 1 minute returns an error on the 6th attempt
- [ ] Admin reporting: Sales by Period report generates correct count for a known test dataset
- [ ] Reporting user can view `/admin/reports` but GET `/admin/config` returns 403
- [ ] Analytics event captured: customer visits `/portal/submit` → `page_view` event recorded in `analytics_events` table → event NOT recorded for a sales rep visiting the same page

---

## 5. E2E Test Infrastructure

### Staging Seed Data
- `scripts/seed_e2e_users.py` creates deterministic test accounts for each role with known credentials stored in Secret Manager under key `e2e/test-credentials`
- Seed script is idempotent; run before every E2E suite
- E2E tests must clean up their own created records (e.g., delete test customers after the test) OR use isolated test-specific record ID prefixes (`THE-TEST-XXXXXXXX`) that can be bulk-purged

### Email Testing (Staging)
- Staging environment routes all outbound email to **Mailpit** (self-hosted, runs in staging as a Docker sidecar) instead of SendGrid
- Playwright tests query the Mailpit API (`GET http://mailpit:8025/api/v1/messages`) to verify email content and extract links
- SMS and Slack notifications in staging route to a stub service that logs to a testable HTTP endpoint

### CI Integration
- E2E tests run in GitHub Actions after the staging deploy step
- Playwright runs in headed mode with video recording on failure (`--reporter=html`)
- XCUITest runs in GitHub Actions via `xcodebuild test` on a macOS runner
- Failed E2E tests block the phase from being marked complete; a Slack notification is sent to the dev channel

---

## 6. Performance Baselines (Non-functional)

These are not blocking CI gates but are tracked and alerted if exceeded:

| Operation | Target | Alert Threshold |
|---|---|---|
| API response (P95, all endpoints) | < 300ms | > 500ms |
| Customer intake form submission | < 1s | > 2s |
| PDF generation time | < 60s | > 120s |
| iOS app cold start | < 2s | > 3s |
| Background sync after reconnect | < 30s | > 60s |
| Public listing page load (uncached) | < 1.5s | > 3s |

Performance measured with k6 (API load test) run monthly in staging; iOS cold start measured via Instruments in CI.

---

## 7. Accessibility Testing Gates

Applies to all web phases (2, 3, 4, 8):
- Playwright E2E suite includes an axe-core accessibility scan on each key page using `@axe-core/playwright`
- Zero critical or serious violations allowed for a phase to pass
- Lighthouse accessibility score ≥ 90 on: `/portal/dashboard`, `/portal/submit`, `/sales/dashboard`, `/admin/dashboard`, `/listings`, `/listings/:id`
- Lighthouse runs automated via `playwright-lighthouse` in CI

---

## 8. Security Testing

Applies to Phase 1 (foundational) and re-run on any phase that touches auth or permissions:
- OWASP Top 10 check via `ZAP` (DAST scan against staging after Phase 1 deploy)
- Dependency vulnerability scan: `pip-audit` (Python), `npm audit` (frontend), `swift package audit` (iOS) — run on every PR; high/critical CVEs block merge
- Secret scanning: `truffleHog` or `gitleaks` runs on every PR; any detected secret blocks merge immediately
- See `.claude/docs/security.md` for the full security checklist
