# Phase 5 — iOS Appraiser App

> **Prerequisite reading:** `00_overview.md`, `01_phase1_infrastructure_auth.md`, `04_phase4_admin_panel.md`, `project_notes/decisions.md` (ADR-012), `dev_plan/11_security_baseline.md §14`
> **Reference data:** `01_checklists/` (all category checklists), `02_schema_and_dictionary/01_normalized_app_field_schema_v1.md`, `03_implementation_package/06_scoring_and_rules_logic.csv`
> **Platform:** SwiftUI, iOS 16+, iPad and iPhone
> **Distribution:** TestFlight (immediate) + App Store (post-launch review)
> **Estimated scope:** 6–8 weeks
> **Deliverable:** Fully functional iOS appraiser app with offline sync, dynamic checklists, photo capture, GPS/EXIF enforcement, and valuation lookup

---

## Sprint 0 — Pre-flight from Phase 1 Hardening

Before any iOS-surface work begins:

- **TOTP `MultiFernet` rotation must ship first.** Phase 1 Hardening intentionally deferred this (`project_notes/code_review_phase1.md §5 Medium`) because no iOS volume existed yet. Before the iOS app starts writing TOTP-protected sessions at scale, `api/config.py` needs a `totp_encryption_keys: list[str]` (primary + rotating keys) and `api/services/auth_service.py` needs to wrap `Fernet` in `MultiFernet` for decrypt + encrypt-to-primary semantics. One migration to re-encrypt existing `totp_secret_enc` rows with the new primary if the key was ever rotated. Tracked in `dev_plan/11_security_baseline.md §14`. **Note:** Phase 4 Sprint 7 already ships MultiFernet decode in `credentials_vault.py` for the integration credentials path; the same shape lifts cleanly into `auth_service`.

## Phase 4 Carry-Ins (Live + Ready for Phase 5)

Phase 4 closed 2026-04-27 (ADR-020); Phase 5 inherits these surfaces:

- **iOS config endpoint** — `GET /api/v1/ios/config` returns `{config_version, categories, inspection_prompts, red_flag_rules, app_config}`. `config_version` is a deterministic SHA-256 hash over the sorted JSON body; iOS app caches the response and only re-fetches when the hash changes. Auth-gated to `appraiser/admin/sales/sales_manager`.
- **Dynamic equipment categories** — admin can add/rename/deactivate categories from `/admin/categories`; changes flow through to the iOS config endpoint immediately (hash bumps). Component weights, inspection prompts, photo slots, attachment options, red-flag rules all CRUD'able.
- **Versioned inspection prompts + red flag rules + categories** — `current_*()` selectors filter on `replaced_at IS NULL`; historical appraisals stay anchored to the version they were submitted against. Phase 5 reads only the current-version slice, but appraisal submissions should store the version at submit time so retro-reporting in Phase 8 stays correct.
- **Notification template registry + Slack dispatch** — every admin notification (lock break, status change, health alert) renders through `notification_templates.py`; iOS push notifications can land as a new channel by registering APNs templates with the same shape.
- **Health dashboard + poller** — `service_health_state` is observable from `/admin/health`; iOS-specific probes (APNs / FCM) plug in by registering an integration tester + service name in `health_check_service`.
- **Multi-attendee calendar + watchers** — `calendar_event_attendees` + `equipment_record_watchers` tables are live; iOS scheduling UX can surface "who's attending" without further backend work.

---

## Architecture Notes (iOS)

- **API communication:** URLSession with async/await; auth token stored in iOS Keychain (never UserDefaults)
- **Offline storage:** Core Data for appraisal records, photos (as file references), and config cache
- **Background sync:** `URLSessionConfiguration.background` for photo uploads; `BGTaskScheduler` for submission sync
- **Push notifications:** APNs via Firebase Cloud Messaging (FCM) — FCM token registered with the API on login
- **Configuration:** Remote config fetched from `GET /api/v1/config/ios` on each app launch; cached in Core Data; config hash compared to detect changes

---

## Epic 5.1 — App Foundation & Authentication

### Feature 5.1.1 — App Scaffolding & Navigation

**User Story:**
As an Appraiser, I want a fast, native app on my iPad or iPhone that feels purpose-built for field appraisals so that I can work efficiently on-site.

**Acceptance Criteria:**
- SwiftUI app with a tab bar: Dashboard | New Appraisal | Calendar | Profile
- Supports iPhone and iPad; optimized for iPad landscape (primary use case — larger form areas)
- All touchable elements have `accessibilityLabel`, `accessibilityRole`, and `accessibilityHint` (VoiceOver compliance)
- App launches in under 2 seconds on an iPhone 12 or newer (cold start)
- Dark mode supported
- App bundle ID: `com.templehe.appraiser`
- Minimum deployment target: iOS 16.0

---

### Feature 5.1.2 — Authentication (iOS)

**User Story:**
As an Appraiser, I want to log in with my TempleHE credentials once and stay logged in so that I don't have to re-authenticate every time I open the app in the field.

**Acceptance Criteria:**
- Login screen accepts email + password; "Sign in with Google" button uses ASWebAuthenticationSession
- Auth tokens stored in iOS Keychain (`kSecAttrAccessibleWhenUnlockedThisDeviceOnly`)
- Access token auto-refreshed before expiry using the refresh token (silent refresh in background)
- If both tokens expire, user is redirected to login screen; any in-progress draft appraisal is preserved in Core Data
- 2FA flow: if account has 2FA enabled, a TOTP entry screen is shown after password login
- Biometric login (Face ID / Touch ID) supported after initial credential login — tokens protected by `LocalAuthentication` framework
- Logout clears Keychain tokens but preserves offline drafts in Core Data (with a warning: *"You have unsync'd appraisals. They will remain on this device and sync when you log in again."*)

---

### Feature 5.1.3 — Push Notification Registration

**User Story:**
As an Appraiser, I want to receive push alerts on my phone for new appraisal assignments so that I don't miss jobs when I'm not actively using the app.

**Acceptance Criteria:**
- On first login, the app requests APNs permission via `UNUserNotificationCenter.requestAuthorization`
- FCM token registered with the API at `POST /api/v1/appraisers/me/device-token` on each login (token can change on reinstall)
- Notification types:
  - **New Assignment:** *"New appraisal scheduled — [Make Model] for [Customer Name] on [Date]"*; tapping opens the Calendar detail for that event
  - **Appointment Reminder:** sent 24 hours before a scheduled appraisal
  - **Sync Confirmation:** *"Your appraisal for THE-XXXXXXXX has been uploaded and received."* — silent notification when background sync completes
- Notification routing: when the Sales team schedules an appraisal (Phase 3, Feature 3.4.2), the backend sends the push via FCM
- Notification content encrypted in transit; no PII in the notification payload beyond what is needed for display
- Notification handling: deep-links into the correct app screen when tapped

---

## Epic 5.2 — Appraiser Dashboard & Assignment Management

### Feature 5.2.1 — Assigned Appraisal Dashboard

**User Story:**
As an Appraiser, I want to see all my upcoming and recent appraisal assignments on the app dashboard so that I always know my schedule.

**Acceptance Criteria:**
- Dashboard tab shows:
  - **Today** section: appointments scheduled for today, sorted by time
  - **Upcoming** section: next 7 days
  - **Drafts** section: appraisals in progress (saved locally, not yet submitted)
  - **Recent** section: last 10 submitted appraisals with sync status badge
- Each card shows: customer name, machine make/model, scheduled time, site address, status badge (Upcoming | In Progress | Draft | Pending Sync | Uploaded)
- Tapping a card opens the appraisal detail or continues a draft
- "New Appraisal" button in the tab bar creates a new unscheduled appraisal (for ad hoc situations where a rep asks an appraiser to evaluate outside the calendar)
- Status badges:
  - **Draft** — started but not submitted; stored locally only
  - **Pending Sync / Offline** — submitted but not yet uploaded due to no connectivity
  - **Uploaded** — received by the API

---

### Feature 5.2.2 — Click-to-Call

**User Story:**
As an Appraiser, I want to call the Sales Rep or customer directly from the app so that I can confirm appointments or get missing information without leaving the app or hunting for a phone number.

**Acceptance Criteria:**
- Each assignment card and appraisal detail view displays:
  - **Sales Rep:** name + phone rendered as a `tel:` link with a phone icon button labeled "Call Rep"
  - **Customer:** name + cell phone rendered as a `tel:` link with label "Call Customer"
- Tapping initiates a native phone call via `UIApplication.shared.open(telURL)`
- Both numbers pulled from the API — never hardcoded
- Phone numbers shown with formatted display (e.g., `(404) 555-0100 ext. 203`)

---

## Epic 5.3 — Google Maps Integration & Site Navigation

### Feature 5.3.1 — Turn-by-Turn Navigation to Site

**User Story:**
As an Appraiser, I want to launch turn-by-turn navigation to the appraisal site directly from the app so that I don't have to copy the address into a separate maps app.

**Acceptance Criteria:**
- "Navigate" button on each assignment card and appraisal detail view
- Tapping opens Apple Maps (default) with the site address pre-filled as the destination; if Apple Maps is unavailable, falls back to Google Maps universal URL
- Address displayed on the card in human-readable format
- "Copy Address" action available (long-press or secondary button) for manual copy

---

## Epic 5.4 — Baseline Valuation Lookup

### Feature 5.4.1 — Equipment Comparable Sales Search

**User Story:**
As an Appraiser, I want to look up recent sale prices for similar equipment from within the app so that I have market data to support my valuation without carrying printed spreadsheets.

**Acceptance Criteria:**
- Valuation lookup accessible within the active appraisal form (dedicated "Market Data" section)
- Lookup form accepts: Make, Model, Year (range ±3 years), Hours (range ±500 hours), Equipment Category
- On search, `POST /api/v1/valuation/search` is called; the API queries:
  1. Internal `ComparableSale` database (seeded from historical appraisals and manually imported auction results)
  2. If internal results < 3, optionally triggers a `ValuationService` call to the stubbed external provider (returns empty results until a real API is integrated)
  3. If `enable_playwright_valuation_scraper` AppConfig flag is true, the API enqueues a background Pub/Sub job that runs a Playwright scraper for recent public auction listings; results are returned asynchronously via a webhook/polling pattern
- Results displayed as a scrollable list: sale price, sale date, make/model/year, hours, source (internal | external | scraped)
- Results can be "pinned" to the appraisal — up to 5 comps can be saved to `AppraisalSubmission.comparable_sales JSONB`
- If no results are found: *"No comparable sales found in the database. Adjust your search criteria or proceed with your professional assessment."*
- Valuation search results are not blocking — Appraiser can continue the form while results load

---

## Epic 5.5 — Dynamic Equipment Appraisal Form

### Feature 5.5.1 — Core Intake Section

**User Story:**
As an Appraiser, I want the app to guide me through a structured intake form so that I capture all required information consistently regardless of how busy or rushed the site visit is.

**Acceptance Criteria:**
- Form sections match the normalized schema in `02_schema_and_dictionary/01_normalized_app_field_schema_v1.md`
- Section 1 — Site & Asset Identity (always shown):
  - Appraisal Date (auto-populated with today, editable)
  - Customer Name (pre-populated from assignment, editable)
  - Site Address (pre-populated from assignment, editable — triggers GPS confirmation)
  - Asset Category (required dropdown — selecting this unlocks all category-specific sections)
  - Make, Model, Serial Number, Year, Hours Meter
  - Hours Verified (yes/no toggle)
  - Ownership Type, Lien Status, Acquisition Path
  - Running Status, Can Cold Start (yes/no)
  - Emissions Tier, Cab Type, ROPS Present
  - Service Records Available
  - Major Rebuild History (text area)
- All required fields validated before the form allows progression to the next section
- Form auto-saves to Core Data every 10 seconds (no manual "Save Draft" tap needed)
- Progress indicator shows: Section X of Y, % complete

---

### Feature 5.5.2 — Dynamic Category-Specific Section

**User Story:**
As an Appraiser, I want the form to show only the inspection prompts, components, and attachment options relevant to the equipment I am evaluating so that I am not scrolling through irrelevant fields.

**Acceptance Criteria:**
- After selecting Asset Category, the category-specific section is rendered dynamically from the iOS configuration fetched from `GET /api/v1/config/ios`
- Category sections include (per category, sourced from `01_checklists/`):
  - **Major Components list** — each component rendered as a scored row: component name + 0–5 score picker (segmented control) + condition notes text field (optional)
  - **Inspection Prompts** — checklist of yes/no/N/A toggles; each prompt labeled per the checklist for that category
  - **Attachments/Options** — multi-select checkboxes for all possible attachments for that category (e.g., for Excavators: General purpose bucket, Thumb, Coupler, Hammer, etc.)
- Component scores drive the weighted overall score (calculated in real-time as scores are entered):
  - Component weights loaded from `AppConfig` (synced from `06_scoring_and_rules_logic.csv`)
  - Live score display: *"Current Overall Score: 3.87 — Strong Resale Candidate"*
- Red flag fields: if a red-flag condition is set (e.g., `structural_damage = true`), a visible red banner appears: *"Red Flag: Management review will be required for this submission."*
- Section rendered from config: Admin can add/remove inspection prompts or attachment options via `AppConfig` without an app update

---

### Feature 5.5.3 — Summary & Marketability

**User Story:**
As an Appraiser, I want to record my professional assessment and final notes before submitting so that the platform has a complete picture of my evaluation.

**Acceptance Criteria:**
- Final form section (always shown, after category-specific section):
  - Overall Cosmetic Condition (dropdown: Excellent / Good / Fair / Poor / Inoperable / Not Verified)
  - Marketability Rating (dropdown: Fast Sell / Average / Slow Sell / Salvage Risk)
  - Transport Notes (text area, optional)
  - Red Flags Summary (text area, shown and required if any red flag condition is true)
  - Listing Notes (text area — market-facing description for the listing page)
- Final calculated overall score displayed with score band label
- "Preview Submission" screen shows a read-only summary of all entered data before submission tap
- "Submit Appraisal" button disabled until all required fields (from AppConfig `ios_required_checklist_fields_<category>`) are complete and all required photos (Feature 5.6) are captured

---

## Epic 5.6 — Photo Capture System

### Feature 5.6.1 — Live Camera Enforcement

**User Story:**
As an Admin, I want the app to only accept photos taken live on the device camera so that appraisers cannot submit stock photos or old images that do not represent the machine's current condition.

**Acceptance Criteria:**
- Photo capture uses `UIImagePickerController` or `PHPickerViewController` configured with `sourceType = .camera` exclusively
- Camera roll / photo library access is explicitly denied for appraisal photos — `sourceType = .photoLibrary` is never presented
- If a device has no camera (simulator), the app shows: *"Photo capture is not available on this device."* and disables submission
- Attempting to use any image source other than live camera is blocked at the UI layer — no workaround through share sheets

---

### Feature 5.6.2 — EXIF Metadata Validation & Capture

**User Story:**
As an Admin, I want every photo submitted with an appraisal to carry GPS coordinates and a timestamp so that I can verify the appraiser was at the correct location and photos were taken on the day of the visit.

**Acceptance Criteria:**
- On each photo capture, the app reads EXIF metadata using `CGImageSource` + `kCGImagePropertyExifDictionary` and `kCGImagePropertyGPSDictionary`
- Required EXIF fields extracted and stored alongside the photo:
  - `gps_latitude` + `gps_longitude` (decimal degrees)
  - `gps_timestamp` (UTC)
  - `capture_timestamp` (device local time)
- If GPS location is unavailable at capture time (location services denied or signal lost), the app shows a warning: *"GPS data is not available for this photo. Please ensure location services are enabled."* — photo is still accepted but flagged as `gps_missing = true` on the `AppraisalPhoto` record
- GPS coordinates are validated against the entered site address using a configurable radius tolerance (AppConfig key `photo_gps_radius_tolerance_meters`, default: 5000m / ~3 miles) — if the photo location falls outside this radius, the appraiser sees a warning: *"This photo appears to have been taken far from the appraisal site. Continue?"* — they can still proceed (logged as a flag, not a hard block)
- Device location permission is requested at app first launch with `NSLocationWhenInUseUsageDescription`

---

### Feature 5.6.3 — Image Compression

**User Story:**
As an Admin, I want photos automatically compressed before upload so that large image files do not consume excessive Cloud Storage or slow down sync on cell data.

**Acceptance Criteria:**
- Every captured image compressed to JPEG at 80% quality using `UIImage.jpegData(compressionQuality: 0.8)`
- Maximum output dimensions: 2048 × 2048 pixels (longer edge); aspect ratio preserved; images larger than this are downscaled using `UIGraphicsImageRenderer` before compression
- Target file size goal: < 1 MB per photo (not a hard block — compression is best-effort)
- Original uncompressed photo is discarded after compression; only compressed version stored in Core Data and uploaded
- Compression happens on a background thread (not main thread) to keep UI responsive

---

### Feature 5.6.4 — Dynamic Photo Checklist Enforcement

**User Story:**
As an Admin, I want the specific set of required photos to vary by equipment category and be remotely configurable so that I can add a new required photo type to the checklist without waiting for an app update.

**Acceptance Criteria:**
- Required photo list per category loaded from `AppConfig` key `ios_required_photos_<category_slug>` (e.g., `ios_required_photos_excavators`)
- Default required photo lists sourced from `02_schema_and_dictionary/01_normalized_app_field_schema_v1.md` "Required photos" section per category
- Photo checklist UI renders each required photo as a labeled capture slot:
  - Uncaptured: camera icon + label (e.g., "Engine Compartment") + "Take Photo" button
  - Captured: thumbnail preview + label + check mark + "Retake" button
- A progress bar shows: X of Y required photos captured
- "Submit Appraisal" is disabled until all required photo slots are filled (`photo_set_complete = true`)
- Optional photos: after all required slots are filled, an "Add Additional Photos" section allows any number of additional free-form photos with a custom label
- Each photo linked to its checklist slot label (stored as `AppraisalPhoto.slot_label`)

---

## Epic 5.7 — Offline Sync System

### Feature 5.7.1 — Local Data Caching

**User Story:**
As an Appraiser, I want the app to work fully offline so that I can conduct an appraisal at a remote site with no cell service and have confidence my data is safe.

**Acceptance Criteria:**
- Core Data schema mirrors the key API entities: `CDAppraisalRecord`, `CDAppraisalPhoto`, `CDComponentScore`, `CDComparableSale`, `CDConfig`
- On app launch (with connectivity), the API is called for: assigned appraisals for the next 30 days, current iOS config (if hash changed), cached comparable sales for recently used categories
- All fetched data written to Core Data immediately
- The appraisal form reads/writes exclusively from Core Data — the API is never called in real-time during form entry
- Photos stored as compressed JPEG files in the app's sandboxed `Documents/Photos/` directory; Core Data stores the file path
- `CDAppraisalRecord.sync_status` enum: `draft | pending_sync | uploading | uploaded | sync_failed`

---

### Feature 5.7.2 — Queued Submission & Background Sync

**User Story:**
As an Appraiser, I want my completed appraisal to upload automatically when connectivity returns so that I never have to manually retry a submission.

**Acceptance Criteria:**
- When the appraiser taps "Submit Appraisal":
  - If online: submission begins immediately; status transitions `draft → uploading`
  - If offline: status transitions `draft → pending_sync`; a banner shows: *"You are offline. Your appraisal has been saved and will upload automatically when connectivity is restored."*
- Background sync implemented with `BGTaskScheduler` and `URLSessionConfiguration.background`:
  - Registered task ID: `com.templehe.appraiser.sync`
  - Task fires when connectivity is restored and the app is backgrounded
  - Uploads `CDAppraisalRecord` rows with `sync_status = pending_sync` in order of `submitted_at` (oldest first)
  - Photos uploaded to Cloud Storage via signed upload URL from `POST /api/v1/appraisal-photos/upload-url` before the record JSON is submitted
- Submission payload: `POST /api/v1/appraisal-submissions` with full `AppraisalSubmission` JSON + array of `AppraisalPhoto` metadata (Cloud Storage paths already uploaded)
- On 2xx response: `sync_status = uploaded`; push notification sent to appraiser (silent)
- On 4xx response (validation error): `sync_status = sync_failed`; appraiser receives a push: *"Submission failed for THE-XXXXXXXX — please review and resubmit."*; error details accessible in the Draft view
- On 5xx / network timeout: retry with exponential backoff (max 5 attempts over 2 hours); after all retries exhausted, `sync_status = sync_failed`

---

### Feature 5.7.3 — UI Status Indicators

**User Story:**
As an Appraiser, I want clear visual indicators on every appraisal card showing whether my data is safely uploaded or still waiting so that I know what I can safely close out.

**Acceptance Criteria:**
- Status badge on each appraisal card (Dashboard + Drafts section):
  - **Draft** — gray badge; *"Not yet submitted"*
  - **Pending Sync / Offline** — yellow badge with wifi-slash icon; *"Waiting for connection"*
  - **Uploading** — blue badge with activity spinner; *"Uploading..."*
  - **Uploaded** — green badge with checkmark; *"Received by TempleHE"*
  - **Sync Failed** — red badge with exclamation; *"Upload failed — tap to retry"*
- Tapping a "Sync Failed" card opens a detail view with the error message and a manual "Retry Upload" button
- A banner at the top of the Dashboard shows "X appraisals pending upload" when `pending_sync` records exist and connectivity is available (indicating sync is in progress)
- No network status banners shown when all records are `uploaded`

---

## Phase 5 Completion Checklist

- [ ] App launches and authenticates with email/password and Google SSO; tokens stored in Keychain
- [ ] Push notification received when a new appraisal is scheduled via the Sales dashboard (Phase 3)
- [ ] Full appraisal form completed for an Excavator — all category-specific fields, scores, and photo slots render from `AppConfig`
- [ ] Admin changes `ios_required_photos_excavators` AppConfig — app reflects new list on next launch without an app update
- [ ] Photo capture blocks camera roll; only live camera accepted
- [ ] Captured photo EXIF includes GPS coordinates and timestamp; `gps_missing = true` flag set when GPS unavailable
- [ ] Photo compressed to < 1 MB before storage
- [ ] "Submit Appraisal" button blocked until all required photo slots are filled and all required fields are complete
- [ ] Completed appraisal submitted offline — `status = pending_sync`; background sync uploads when connectivity returns
- [ ] After sync, appraiser receives silent push notification; card shows "Uploaded" badge
- [ ] Comparable sale search returns internal DB results and handles empty state gracefully
- [ ] Click-to-call dials correctly on iPhone; navigation launches Apple Maps with correct address
