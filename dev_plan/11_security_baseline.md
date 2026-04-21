# Security Baseline — Auth Hardening, Compliance & Data Protection

> **Audience:** Jim, as the sole developer and operator.
> **Scope:** Every item in this file is a required acceptance criterion before production launch. Right-sized for SMB; no enterprise gold-plating.
> **Phase mapping:** Most items are absorbed into Phase 1 (auth hardening, sanitization, headers); some into Phase 2 (ToS/privacy, email compliance); a few are one-time setup steps called out explicitly.
>
> **Stack mapping (POC → GCP target):** The platform runs on Fly.io + Neon Postgres + Cloudflare R2 + Cloudflare WAF/CDN today (per `ADR-001` in `project_notes/decisions.md`). Every security control below is implemented on that stack first and remains valid after migration. When a control mentions a GCP service (Secret Manager, Cloud Storage, Pub/Sub, Cloud Run Jobs, Cloud Logging) that means the **target state**; the **POC equivalent** is called out next to it (`fly secrets`, R2, scheduled Fly Machine, BetterStack). The `RecordLockService`, `BlobStorageService`, `JobQueueService`, and `SecretsService` interfaces are written so the implementation swaps at migration time without API changes.

---

## 1. Password Reset & Account Recovery

Phase 1 only covered registration + email verification. Password reset is a launch-blocker.

### Feature 1.3.5 — Password Reset Flow

**User Story:**
As a user who forgot my password, I want to request a reset link so I can regain access without contacting support.

**Acceptance Criteria:**
- `POST /api/v1/auth/password-reset-request` accepts `{ "email": "..." }`; always returns 200 regardless of whether the email exists (prevents user enumeration)
- If email matches an active user, a signed JWT reset token (30-minute expiry) is sent via SendGrid with a link to `/auth/reset-password?token=<jwt>`
- `POST /api/v1/auth/password-reset-confirm` accepts `{ "token": "...", "new_password": "..." }`; validates token signature and expiry, applies password complexity rules (same as registration), bcrypt-hashes, updates the user record
- On successful reset: all existing refresh tokens for the user are invalidated (forces re-login on all devices), and an email is sent: "Your password was just changed. If this wasn't you, contact support immediately."
- Rate limited: max 3 reset requests per email per hour, max 10 per IP per hour
- All reset events written to `audit_logs`

### Feature 1.3.6 — Email Change Flow

**Acceptance Criteria:**
- `POST /api/v1/auth/change-email` (requires current session) accepts `{ "new_email": "...", "current_password": "..." }`
- Current password must be re-verified (step-up auth)
- Verification email sent to the **new** address with a confirmation link; email is not changed until the link is clicked
- Notification email sent to the **old** address: "Your email is being changed to ***@***. If this wasn't you, click here to cancel."
- Old email receives a second notice once the change is confirmed

### Feature 1.3.7 — 2FA Recovery

**Acceptance Criteria:**
- The 10 recovery codes from Feature 1.3.4 can be redeemed at `POST /api/v1/auth/2fa/recover` in place of a TOTP code
- Each code is single-use; used codes marked consumed in the database
- When a user has consumed 7+ codes (3 or fewer remaining), a warning email prompts them to generate new codes
- If all 10 codes are consumed and TOTP is lost: user must contact Jim, who can verify identity out-of-band and manually disable 2FA via admin action (logged to audit_logs with explicit "manual 2FA reset" event type)

---

## 2. Brute-Force & Abuse Protection

### Feature 1.3.8 — Rate Limiting on Auth Endpoints

**Acceptance Criteria:**
- Rate limiting implemented via `slowapi` (FastAPI middleware). POC uses an in-process `slowapi` backend per Fly Machine combined with Cloudflare edge rate limiting on `/api/*` (see `10_operations_runbook.md` §2.6); at GCP migration the backend swaps to Memorystore Redis for shared counters across instances. Cloudflare rate limiting always applies as an outer ring regardless of stack.
- Per-endpoint limits:

| Endpoint | Per IP | Per Email/Account |
|---|---|---|
| `POST /auth/login` | 10 / minute | 5 / 15 minutes |
| `POST /auth/register` | 5 / hour | n/a |
| `POST /auth/password-reset-request` | 10 / hour | 3 / hour |
| `POST /auth/2fa/verify` | 10 / minute | 5 / 15 minutes |
| `POST /auth/refresh` | 60 / minute | 60 / minute |
| Any `/public/*` endpoint | 60 / minute | n/a |

- Exceeding a limit returns 429 with `Retry-After` header
- Rate limit events logged at INFO; sustained limit-hitting (> 20 429s from same IP in 5 min) logged at WARNING and surfaced as a Sentry event

### Feature 1.3.9 — Account Lockout

**Acceptance Criteria:**
- After 5 failed login attempts on the same account within 15 minutes, account status is set to `locked`; login returns 423 with message "This account has been temporarily locked due to repeated failed logins. Try again in 30 minutes or reset your password."
- Lockout auto-releases after 30 minutes
- Successful password reset (Feature 1.3.5) also releases lockout
- Admin can manually release lockout from the admin panel
- Lockout and release events written to `audit_logs`

### Feature 1.3.10 — Login Notifications for New Devices

**Acceptance Criteria:**
- On successful login, compare user agent + IP against past `audit_logs` login events for that user
- If this is a new device/location (no prior login from this UA family + IP ASN combination), send an email: "New sign-in to your TempleHE account from [City, State] on [Device]. If this wasn't you, reset your password immediately."
- Not sent for SSO logins that come through Google (Google sends their own)

---

## 3. Input Sanitization & XSS Prevention

### Feature 1.x.1 — Sanitization Middleware (new epic in Phase 1)

**User Story:**
As the site operator, I want all user-submitted text rendered safely so that a malicious customer cannot inject scripts into another user's session.

**Acceptance Criteria:**
- All free-text fields on `AppraisalSubmission`, `ChangeRequest`, `Customer`, `PublicListing`, `Inquiry`, `AppraisalPhoto.notes` etc. are sanitized on both write (backend, via `bleach` library) and render (frontend, via React's default text node escaping)
- Sanitization policy: strip all HTML tags; preserve plain text and newlines; emails and URLs are NOT auto-linked server-side (frontend can linkify safely via a library like `linkify-react`)
- Markdown support is explicitly OFF in user-submitted fields (we don't want to parse untrusted markdown)
- PDF generation (Phase 7, WeasyPrint) also escapes text fields — never renders raw HTML from user input
- Email templates use Jinja's `|e` auto-escaping by default; explicit `|safe` is only allowed on system-generated content (links, localized phrases)
- Integration test: submit text containing `<script>`, `<img onerror>`, `javascript:` URLs in every user-editable field → render back via API and inspect; confirm sanitized

### Feature 1.x.2 — Security Response Headers

**Acceptance Criteria:**
- FastAPI middleware sets the following headers on every response:

```
Strict-Transport-Security: max-age=31536000; includeSubDomains; preload
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: geolocation=(), microphone=(), camera=()
Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https://*.r2.cloudflarestorage.com https://images.templehe.com; connect-src 'self' https://sentry.io; frame-ancestors 'none'
```

- CSP is strict but allows Sentry and the photo-hosting origin (Cloudflare R2 behind `images.templehe.com` during POC; swap `img-src` to `https://storage.googleapis.com` after GCP migration). Adjust per page if a specific integration requires it (e.g., eSign iframe)
- CORS middleware: allowlist only the known frontend origins (configured per env in `AppConfig`: `cors_allowed_origins`). No wildcard.
- Report CSP violations to Sentry: add `report-uri` to the CSP header pointing at Sentry's CSP reporting endpoint

### Feature 1.x.3 — CSRF Protection

**Acceptance Criteria:**
- The API uses `Authorization: Bearer <jwt>` rather than cookies for auth → CSRF is naturally not applicable to the primary API
- Admin panel frontend: same model (bearer tokens in memory, not cookies) — protects against CSRF by construction
- Public-facing forms (inquiry, consignment eSign embedded page): if any of these use cookies (e.g., the eSign provider's embedded signer), enable SameSite=Lax on any cookies we set and validate Origin header on POSTs

---

## 4. Secrets Management & Rotation

### Feature 1.4.3 — Secrets Rotation Policy

**Acceptance Criteria:**
- Every application secret stored in `fly secrets` per app (POC) — moves to Secret Manager labeled `rotation_due` after GCP migration. The inventory and per-secret rotation procedure live in `project_notes/secrets-rotation.md`.
- Rotation schedule:

| Secret | Frequency | Manual/Auto | POC home | Target home |
|---|---|---|---|---|
| Neon database connection string (per branch) | Annual or on incident | Manual (rotate in Neon dashboard, update via `flyctl secrets set DATABASE_URL=...`) | `fly secrets` | Secret Manager |
| JWT signing key | Annual or on incident | Manual (`openssl rand -base64 64`, then `flyctl secrets set JWT_SIGNING_KEY=...`) | `fly secrets` | Secret Manager |
| Twilio auth token | Annual | Manual (Twilio dashboard → `flyctl secrets set`) | `fly secrets` | Secret Manager |
| SendGrid API key | Annual | Manual | `fly secrets` | Secret Manager |
| Google Maps API key | Annual, or sooner if abuse suspected | Manual | `fly secrets` | Secret Manager |
| eSign webhook secret | Annual | Manual | `fly secrets` | Secret Manager |
| Cloudflare R2 access keys | Annual | Manual (Cloudflare dashboard → `flyctl secrets set`) | `fly secrets` | n/a (R2 retired post-migration; replaced by Cloud Storage IAM) |
| Fly deploy tokens (per app) | Quarterly (90 days) | Manual (`flyctl tokens create deploy --app ...`, update GitHub secret, `flyctl tokens revoke <old>`) | GitHub Actions secret | n/a (replaced by Workload Identity Federation) |
| GCP service account keys | Not used — Workload Identity Federation only | n/a | n/a | n/a |

- Scheduled task (§8 of `10_operations_runbook.md`) runs monthly and emails Jim a list of secrets within 60 days of their rotation date
- Rotation procedure documented for each secret in `project_notes/secrets-rotation.md`; each includes: where to generate the new value, the `flyctl secrets set` command (Cloud Run + `gcloud secrets versions add` after migration), and how to force the running app to pick it up (Fly auto-restarts the Machine when secrets change; on Cloud Run, deploy a new revision)
- **Never** check a secret into git. Pre-commit hook (gitleaks) and GitHub secret scanning both block this.

### Feature 1.4.4 — Admin "Reveal Credential" Step-Up Auth

Reference: Phase 4 Feature 4.3.1 allows admin to reveal stored integration credentials. This is a concentrated risk vector.

**Acceptance Criteria:**
- Clicking "Reveal" requires re-authentication: admin must enter their password (and TOTP if 2FA enabled) in a modal before the value is fetched
- Revealed value is shown for 30 seconds then auto-masked again
- Every reveal logged to `audit_logs` with `event_type = "integration_credential_revealed"`, target credential name, and actor info
- Rate limit: max 10 reveals per hour per admin

---

## 5. Email & SMS Compliance

### 5.1 Email deliverability + compliance (CAN-SPAM)

One-time DNS setup that must be done before launching:

**Acceptance Criteria:**
- SendGrid domain authentication configured: SPF, DKIM, DMARC records added to the TempleHE DNS
- DMARC policy starts at `p=none` (monitor mode) for 2 weeks, then `p=quarantine`, then `p=reject` once baseline is clean
- All outbound email templates include:
  - TempleHE physical mailing address in the footer (CAN-SPAM requirement)
  - A clear unsubscribe link for any non-transactional email (status updates, marketing — nothing for now, but the mechanism must exist)
  - Sender name clearly identifying TempleHE; no misleading "From" names
- Transactional emails (verification, password reset, status updates) are exempt from unsubscribe but still include the physical address
- Email preference management endpoint `PATCH /api/v1/users/me/email-preferences` lets users opt out of non-critical email categories
- Bounces and spam complaints logged from SendGrid webhook; users with hard bounces flagged in the admin panel

**DNS records to create (template):**

```
# SPF
@  TXT  "v=spf1 include:sendgrid.net ~all"

# DKIM — two records from SendGrid's dashboard
s1._domainkey   CNAME  s1.domainkey.u12345.wl.sendgrid.net.
s2._domainkey   CNAME  s2.domainkey.u12345.wl.sendgrid.net.

# DMARC
_dmarc  TXT  "v=DMARC1; p=none; rua=mailto:dmarc@templehe.com; pct=100"
```

### 5.2 SMS compliance (A2P 10DLC + STOP opt-out)

**This is required by US law. Twilio cannot send reliable US SMS without it.** Start the registration process on Day 1 of Phase 1 because it takes 2–4 weeks.

**Acceptance Criteria:**
- Twilio account has a registered **A2P 10DLC Campaign** linked to TempleHE's EIN/business registration
- Campaign type: "Low Volume Mixed" is appropriate for an SMB (~500 SMS/day). Upgrade later if volume grows.
- Every initial SMS to a new number includes the opt-out language: "Reply STOP to opt out, HELP for help. Msg & data rates may apply."
- Twilio's automatic STOP/HELP handling is enabled (default); when a user sends STOP, they are automatically opted out at Twilio's level
- When Twilio signals a user has opted out via webhook, their `notification_preferences.channel` is changed to `email` and a one-time email is sent: "We've opted you out of SMS notifications. You'll continue to receive updates by email."
- Users can't opt back in to SMS except by editing their profile in the portal

**Registration steps (do once):**
1. Twilio Console → Messaging → Regulatory Compliance → Register A2P 10DLC
2. Submit Brand (TempleHE business info, EIN)
3. Submit Campaign (use case, sample messages, opt-in flow screenshots)
4. Wait 1–4 weeks for carrier approval
5. Associate phone numbers with the approved Campaign

### 5.3 Notification preferences — granular opt-outs

**Acceptance Criteria:**
- Extend `notification_preferences` table: per-category toggles for each event type (new_request_confirmation, status_change, change_request_resolved, inquiry_received, etc.)
- Customer-facing preferences page at `/portal/preferences` lets users enable/disable categories per channel
- System-critical emails (password reset, security alerts, account lockouts) are always sent and cannot be disabled

---

## 6. Legal — Terms of Service & Privacy Policy

### Feature 2.1.3 — ToS & Privacy Acceptance

**User Story:**
As TempleHE, I need every user to affirmatively accept our ToS and privacy policy so we have a defensible record.

**Acceptance Criteria:**
- Registration form (Feature 2.1.1 and Admin invites) includes a required checkbox: "I agree to the Terms of Service and Privacy Policy" with those phrases as links
- On submit, server records: `user.tos_accepted_at`, `user.tos_version`, `user.privacy_accepted_at`, `user.privacy_version`
- Version strings live in `AppConfig` (`tos_current_version`, `privacy_current_version`) and match the versioned ToS/Privacy docs hosted at `/legal/terms-v1.md` and `/legal/privacy-v1.md`
- When a new major version is published, users are prompted to re-accept on next login (interstitial screen); cannot use the portal until accepted
- Raw text of each accepted version archived immutably in object storage with versioning enabled (POC: Cloudflare R2 bucket `temple-he-legal/`; target: GCS bucket `temple-prod-legal/`) so we have historical proof of what the user agreed to
- An initial ToS and Privacy Policy must be drafted by a lawyer or obtained from a template service (Termly, iubenda, or similar) before launch — Claude cannot and should not draft the actual legal text

**Templates you can reasonably start from (then have reviewed):**
- Termly (free tier + upgrade for more complex) — generates CCPA/GDPR-aware text
- iubenda — more polished output, paid
- Adapting a similar-scale SMB's published privacy policy (with a lawyer's review)

---

## 7. Data Retention, Export & Deletion (GDPR-lite for SMB)

Even if you're not serving EU customers, California (CCPA) and a growing number of US states require customer data rights. Implementing this properly is not expensive and saves enormous pain later.

### Feature 2.6.1 — Customer Data Export

**Acceptance Criteria:**
- Customer can request a data export at `/portal/privacy/export`
- `POST /api/v1/customers/me/data-export` enqueues a job (POC: row in `jobs` Postgres table, drained by a scheduled Fly Machine; target: Pub/Sub topic + Cloud Run Job consumer) to assemble the customer's data
- The export package includes (JSON + attached files):
  - Customer profile record
  - All equipment records owned by them
  - All appraisal submissions, photos (URLs + downloadable ZIP), PDF reports
  - All change requests
  - Communication log (emails/SMS sent to them, excerpts only — no system internal data)
- Rate-limited to 1 export request per customer per 30 days
- Delivered as a presigned object-storage URL (7-day expiry) via email — POC: R2 presigned URL; target: signed GCS URL
- Export generation logged to `audit_logs`

### Feature 2.6.2 — Customer Account Deletion

**Acceptance Criteria:**
- Customer can request deletion at `/portal/privacy/delete-account`
- Confirmation requires: password re-entry + explicit text confirmation ("DELETE")
- On submit:
  - `customer.deletion_requested_at` set
  - 30-day grace period during which the customer can cancel by logging in
  - Email: "Your account will be permanently deleted on [date]. Cancel anytime by logging in."
  - After 30 days: hard-delete PII (name, email, phone, address) from the `customers` and `users` tables; retain `equipment_records` and `appraisal_submissions` with PII redacted (customer_id set to NULL, notes field scrubbed)
  - Audit log entries retained (anonymized — we keep "a user with id X did Y" but not their identity)
  - Photos and PDFs deleted from object storage (R2 in POC, GCS after migration); R2 object versioning means the deletion is recoverable for the version-retention window — adjust the lifecycle rule if a customer requests immediate hard-delete
- Admin receives an email notice when a deletion request is made (in case of suspicious activity)
- Deletion event logged to `audit_logs`

### Feature 2.6.3 — Retention Schedule

| Data type | Retention | Action after |
|---|---|---|
| Active customer data | Indefinite (while active) | n/a |
| Closed account PII | 30 days after deletion request | Hard delete |
| `audit_logs` | 2 years | Archive to cold storage (POC: dedicated R2 bucket `temple-he-audit-archive/` with lifecycle → Infrequent Access tier; target: separate GCS bucket with 5-year retention), then delete |
| Appraisal photos | 5 years after listing sold/withdrawn | Delete (cost) |
| Appraisal PDFs | 7 years | Retain for tax/legal |
| Inquiries from public listings (no conversion) | 1 year | Delete |
| Analytics events | 1 year | Delete (aggregated stats retained separately) |
| Sentry error data | 90 days (Sentry default on free tier) | n/a |

- Retention enforced by a monthly scheduled job (`retention-enforcer`) that queries and deletes/archives per the table above — POC: a dedicated Fly Machine with `[deploy.schedule]` set to monthly cron in `fly.toml`; target: Cloud Run Job triggered by Cloud Scheduler
- Job writes a summary to `audit_logs` each run (counts of items archived/deleted)

---

## 8. Webhook Security

### Feature 6.3.4 — Webhook Signature + Replay Protection

Phase 6 covers HMAC verification for the eSign webhook. Replay protection was missing.

**Acceptance Criteria:**
- Every incoming webhook (eSign, Twilio, SendGrid, FCM) is verified:
  - HMAC-SHA256 signature matches the shared secret
  - Timestamp in the payload is within 5 minutes of server time (prevents replay of captured payloads)
  - Payload `event_id` (or Twilio `SmsSid`, SendGrid `sg_event_id`) recorded for de-duplication; duplicate event IDs are ignored with a 200 response (idempotent). POC implementation uses a `webhook_events_seen (event_id PK, received_at, expires_at)` Postgres table with a daily cleanup of rows older than 24h; target swaps to a Redis SET with 24h TTL after GCP migration
- Webhook endpoints log every received payload (minus secrets) for forensic review (POC: structured log shipped to BetterStack; target: Cloud Logging)
- A failed signature verification emits a WARN log and a Sentry event — repeated failures should be investigated

---

## 9. iOS App — Additional Security

### Feature 5.1.4 — Minimum Supported Version + Force Update

**Acceptance Criteria:**
- Backend returns `min_supported_ios_version` in the `/api/v1/config/ios` response (AppConfig value)
- On launch, the iOS app compares its own version against this value; if older, shows a blocking screen: "A required update is available. Please update TempleHE Appraiser from the App Store to continue."
- Blocking screen has a single button linking to the App Store listing
- This is the kill switch for shipping a critical fix — bump the minimum version in AppConfig and old clients are forced to update

### Feature 5.1.5 — Crash Reporting

**Acceptance Criteria:**
- Firebase Crashlytics integrated in the iOS app (free)
- Crash reports include device model, iOS version, app version, stack trace, breadcrumbs (last 20 user actions)
- NO PII in crash reports — field values and user identifiers scrubbed before upload
- Crashlytics alerts Jim via email when a new crash type appears in production

### Feature 5.1.6 — Offline Token Handling

**Acceptance Criteria:**
- If the access token expires while the app is offline, the user is NOT forced to log out
- Draft appraisals continue to save to Core Data
- On reconnect, the app attempts a silent refresh using the refresh token; if that fails (refresh token expired), the user is prompted to re-log in once — drafts are preserved
- This scenario is tested in Phase 5 E2E: disconnect for > 7 days, reconnect, verify drafts are not lost

---

## 10. Sales-Initiated Price Changes

Gap identified in review: Phase 6 only re-approves price changes initiated by customers.

### Feature 6.2.3 — Sales Rep Price Change Guard

**Acceptance Criteria:**
- When a sales rep edits `PublicListing.asking_price` or the approved pricing on an `EquipmentRecord`, the same `consignment_price_change_threshold_pct` check runs
- If the change exceeds threshold, the save requires Sales Manager approval before taking effect (UI shows: "This change requires manager approval before going live.")
- `ChangeRequest` row created with `request_type = sales_price_change`, routed to the manager queue
- Until approved, the listing continues to show the previous price

---

## 11. Assignment Handoff When Staff Departs

### Feature 4.2.2 — User Deactivation Workflow

**Acceptance Criteria:**
- When admin deactivates a user with role `sales` or `appraiser`:
  - Admin is presented with a modal: "This user has N open equipment records assigned. Reassign to whom?"
  - Admin selects a replacement user from the dropdown
  - All `EquipmentRecord` rows where `assigned_sales_rep_id = <leaving_user>` OR `assigned_appraiser_id = <leaving_user>` AND status is not terminal are bulk-updated
  - Each reassigned record emits an audit log entry + notification to the new assignee
  - Calendar events for future appraisals are reassigned to the new appraiser with a note: "Reassigned from [old name] to [new name]"
- Without this flow the deactivation is blocked with a helpful error

---

## 12. Pre-Launch Security Checklist

Before first production deploy, every box here must be checked. This is the go/no-go list.

- [ ] Password reset flow implemented and tested end-to-end
- [ ] Account lockout tested (5 failed logins → locked → auto-released after 30 min)
- [ ] Rate limiting verified on all auth endpoints
- [ ] All security headers present on API responses (check with `curl -I`)
- [ ] CSP tested — no violations in browser console on all pages
- [ ] Sanitization tested — submitted `<script>` renders as text, not executes
- [ ] Secrets rotation schedule documented in `project_notes/secrets-rotation.md`
- [ ] Admin "Reveal" step-up auth working
- [ ] SendGrid SPF + DKIM + DMARC configured; test email passes all three at mail-tester.com
- [ ] Twilio A2P 10DLC registration approved
- [ ] SMS STOP opt-out tested end-to-end
- [ ] ToS v1 and Privacy Policy v1 legally reviewed and published
- [ ] ToS/Privacy acceptance required at registration; versions stored per user
- [ ] Data export endpoint returns a complete package
- [ ] Data deletion flow tested on a staging customer (full 30-day cycle simulated via timestamp override)
- [ ] Retention enforcer scheduled job deployed and tested in staging (POC: `temple-retention-enforcer` Fly Machine on monthly cron; target: Cloud Run Job)
- [ ] Webhook signature verification + replay protection unit-tested
- [ ] iOS min-version kill switch tested by setting min-version higher than bundle version
- [ ] Crashlytics receiving reports from staging iOS builds
- [ ] Sales-initiated price change guard tested
- [ ] User deactivation with active records blocked until reassignment completed
- [ ] All items in `10_operations_runbook.md` §12 (Day-1 checklist) complete
- [ ] `/security-review` skill run on the full codebase once; critical findings addressed
- [ ] Initial OWASP ZAP baseline scan run against staging; no HIGH findings
- [ ] Dependabot + push protection + gitleaks + Trivy all green on `main`

---

## 13. Integration with existing phases

The items above integrate into the existing phase files as follows:

| Section | Phase | Added to |
|---|---|---|
| §1 Password reset / account recovery | 1 | New Epic 1.3 features (§4 of this doc details the acceptance criteria) |
| §2 Rate limiting + lockout | 1 | New Epic 1.3 features |
| §3 Sanitization + security headers | 1 | New Epic 1.6 |
| §4 Secrets rotation | 1 + Ops | Phase 1 sets the baseline; ops runbook §7 handles operational rotation |
| §5 Email + SMS compliance | 1 (integrations) + pre-launch checklist | Twilio/SendGrid setup in Phase 1; A2P 10DLC registration on Day 1 |
| §6 ToS & Privacy | 2 | Feature 2.1.3 added to Phase 2 |
| §7 Data retention + export/delete | 2 + Ops | New epic in Phase 2; monthly retention job in Ops |
| §8 Webhook replay protection | 6 | Added to Feature 6.3.3 acceptance criteria |
| §9 iOS additions | 5 | Features added to Phase 5 |
| §10 Sales price change guard | 6 | Added to Phase 6 |
| §11 Staff departure handoff | 4 | Feature 4.2.2 added to Phase 4 |

Phase 1 will be updated in a separate edit pass to include the new auth hardening features listed above.

---

## 14. Deferred Items — Phase 1 Hardening (2026-04-21)

The post-Sprint-5 code review (`project_notes/code_review_phase1.md`, Outline: https://kb.saltrun.net/doc/baXdhfglbk) triaged 35 findings. Most were remediated on branch `phase1-hardening` (see ADR-012). The following were intentionally deferred; this section is their canonical home so a future session knows the deferral is deliberate.

### 14.1 TOTP `MultiFernet` rotation (→ Phase 5 Sprint 0)

**Why deferred:** Phase 1 has a single `totp_encryption_key` Fernet key. Key leakage decrypts all stored TOTP secrets. Rotation path requires `MultiFernet`: a primary key for encryption + a list of legacy keys for decrypt-only. Phase 1's 2FA volume doesn't justify the complexity — no real users have enabled TOTP yet.

**Action in Phase 5:** Before iOS 2FA opens up at volume:
- `api/config.py` — replace `totp_encryption_key: str` with `totp_encryption_keys: str` (comma-separated; first is primary).
- `api/services/auth_service.py` — wrap `Fernet` in `MultiFernet(fernets)` for decrypt; always encrypt with primary.
- Rotation runbook: set new primary, leave old as secondary, redeploy. Re-encrypt legacy `totp_secret_enc` rows over a weekend window via an ad-hoc script, then drop the old key.

### 14.2 Application-level `/metrics` endpoint

**Why deferred:** Fly metrics cover host-level (CPU, RAM, network). Application counters (auth failures, rate-limit hits, 2FA attempts) are visible via audit log today — acceptable for Phase 1. An in-process Prometheus exposition would require a scraper (Fly doesn't run one by default) or an export to BetterStack metrics.

**Reconsider when:** a security or reliability question can't be answered by audit log + BetterStack logs, or when the GCP migration lands Cloud Monitoring as the default surface.

### 14.3 `boto3` → `aioboto3` evaluation

**Why deferred:** `boto3` is sync-only (wrapped with `asyncio.to_thread` today). Not hot in Phase 1. For R2 photo uploads in Phase 2+ that could matter, but `aioboto3` has its own maintenance story and the R2 S3-compatible API works identically.

**Reconsider when:** R2 calls appear in latency-sensitive request paths (Phase 2 photo presign flow). Measure first; don't churn preemptively.

### 14.4 `trust_proxy` CIDR allowlist (optional hardening)

**Why deferred:** `middleware.rate_limit.get_client_ip` prefers `CF-Connecting-IP` → `X-Forwarded-For` → socket peer. A request that bypasses both Cloudflare and Fly's proxy could forge these headers. At POC scale, the bypass only affects the forger's own rate-limit bucket.

**Reconsider when:** the API is exposed on a direct endpoint (post-GCP migration with Cloud Load Balancer, or if Cloudflare is bypassed for some internal integration). At that point, verify the peer IP is in Cloudflare's published CIDR list before trusting the `CF-Connecting-IP` header.

### 14.5 PII retention (row-level)

**Why split:** §7 of this document already specifies the retention schedule (login logs 30 days, audit logs 18 months, customer PII per request). Phase 1 ships partitioning + the sweeper scaffold; row-level retention on `audit_logs` / `user_sessions` / `known_devices` lands with the Phase 2 data export & deletion epic so it's decided before real customer data arrives on prod.
