# Phase 7 Status Report — PDF Reports

## Sprint 1: Data Assembly + Schemas — COMPLETE 2026-05-03

### What was built
- `api/schemas/report.py` — Full Pydantic schema hierarchy for `ReportData` and all sub-sections (equipment, valuation, gallery, personnel, branding), plus `ReportDownloadResponse` / `ReportGeneratingResponse` for the download endpoint
- `api/services/report_data_service.py` — `build_report_data()` async DB loader + `_assemble()` pure function; raises `ReportDataIncompleteError` when both pricing fields are null (enforces approval-before-PDF invariant)
- `api/services/app_config_registry.py` — 4 new AppConfig keys: `pdf_page_size`, `pdf_brand_primary_color`, `pdf_font_family`, `company_logo_url`
- `api/pyproject.toml` — added `weasyprint==68.1` and `Pillow` dependencies

### Test results
- Unit: 25 tests, all passing
- Integration: 5 tests, all passing

### Key decisions
- `_assemble()` is a pure function (no DB calls) so unit tests stay fast with `MagicMock` fixtures
- `ReportDataIncompleteError` fires only when *both* pricing fields are null; partial data (e.g., no photos) renders with placeholder
- `CategoryComponent` ORM kwargs validated: `weight_pct`, `display_order`, `active` (not `version`/`is_active`)

### Bugs found and fixed
- `_seed_component` test helper passed invalid `version=1` and `is_active=True` kwargs to `CategoryComponent`; fixed to use correct field names

---

## Sprint 2: PDF Rendering + Generation + Download Endpoint — COMPLETE 2026-05-03

### What was built
- `api/templates/pdf/styles.css` — Full WeasyPrint CSS; `@page` with footer counter; photo grid (3-col A4, 2-col Letter); management review alert box
- `api/templates/pdf/appraisal_report.html.j2` — Jinja2 template with 5 sections: report header/title, equipment details, valuation & pricing, photo gallery (base64 inline), personnel info
- `api/services/pdf_render_service.py` — `render_pdf()`: photo fetch from R2 + Pillow re-compress (800×800, 60% JPEG) + Jinja2 render + WeasyPrint HTML→PDF
- `api/services/pdf_generation_worker.py` — `generate_and_store()` (full pipeline), `generate_and_store_best_effort()` (swallows + audits errors), `generate_download_url()` (R2 presigned 15-min GET)
- `api/routers/reports.py` — `GET /api/v1/equipment-records/{id}/report/pdf`; 202/200/503 states; customer ownership enforced via explicit Customer SELECT
- `api/routers/manager_approvals.py` — PDF trigger via FastAPI `BackgroundTasks` with dedicated `AsyncSessionLocal` session
- `api/main.py` — registered reports router

### Test results
- Unit: 205/205 passing
- Integration: 544/544 passing

### Key decisions
- `AsyncSessionLocal` per background task (not shared request session) — avoids `InterfaceError` during session teardown when the background task outlives the request
- `appraisal_reports` has no unique constraint on `appraisal_submission_id` → Python-level select+conditional upsert instead of `ON CONFLICT DO UPDATE`
- Customer ownership check uses explicit `select(Customer).where(Customer.user_id == ...)` — lazy loading `current_user.customer_profile` raises `MissingGreenlet` in async context

### Bugs found and fixed
- `asyncio.create_task` sharing the request DB session caused 8 test teardown `InterfaceError`s; fixed by moving PDF trigger to FastAPI `BackgroundTasks` with its own session
- `ON CONFLICT DO UPDATE` on nullable non-unique column rejected by PostgreSQL; fixed with explicit Python upsert
- `Customer.user_id` lazy-load in async context raised `MissingGreenlet`; fixed with explicit query
- Test for download endpoint: `settings.r2_access_key_id` is empty in test env → 503; fixed by patching `settings` in the affected test

---

## Sprint 3: Frontend + E2E Gate — COMPLETE 2026-05-03

### What was built
- `web/src/api/reports.ts` — API client with `getReportDownload()` and `isReportReady()` type guard
- `web/src/pages/EquipmentDetail.tsx` — `ReportCard` component gated on `REPORT_ELIGIBLE_STATUSES` (`approved_pending_esign`, `esigned_pending_publish`, `active`)
- `web/src/pages/SalesEquipmentDetail.tsx` — `SalesReportCard` component with same gate + expiry timestamp display
- `web/src/test/handlers.ts` — MSW default handler returning 202 generating response
- `web/src/pages/ReportDownload.test.tsx` — 3 Vitest tests: hidden for new_request, generating message, download link
- `scripts/seed_e2e_phase7.py` — approved + new_request modes
- `web/e2e/helpers/api.ts` — `seedPhase7()` helper
- `web/e2e/phase7_pdf.spec.ts` — 5 E2E gate scenarios

### Test results
- Frontend unit (Vitest): 131/131 passing

### Key decisions
- `isReportReady()` type guard discriminates on `download_url` presence (not HTTP status code, which isn't visible through the `request<T>()` wrapper)
- Report card hidden entirely for non-eligible statuses (no empty card) — cleaner UX than showing a disabled/empty state
- E2E tests cover the 202 "generating" path since R2 is not configured in E2E env; the 200 "ready" path is tested in integration tests

### Open issues / follow-ups
- None — all Phase 7 features complete
