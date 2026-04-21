# Phase 1 Code Review — Triaged Findings & Phase 2 Fragility

**Review date:** 2026-04-21
**Reviewer:** Claude (Opus 4.7)
**Scope:** all files created or materially modified in Phase 1 of the TempleHE consignment platform. Excluded: `.venv/`, `__pycache__`, tests (reviewed for shape only, not quality).
**Also published to Outline:** https://kb.saltrun.net/doc/baXdhfglbk

**Triage buckets:** Critical (ship-stopper or exploitable) · High (will break or bite in production) · Medium (wrong but bounded) · Low (minor) · Noise (cosmetic).

---

## Remediation status (2026-04-21, branch `phase1-hardening`)

All Critical, High, and Medium findings are either **resolved** in a named commit or **deferred** to a named later-phase document. Lows that were "documented only" carry a `no-change` marker with rationale.

| Workstream | Commit | Covers |
|---|---|---|
| WS1 Dockerfile runtime | on `main` via PR #21 / commit d6fb656 | §5 High Dockerfile, Phase-2-fragility #11 |
| WS2 python-jose → PyJWT | 44b5b45 | §7 High python-jose, §7 High bleach, §7 Medium passlib, Phase-2-fragility #4 |
| WS3 refresh-token cookie | eaf82d4 | §1 Critical refresh token dropped, §4 High orphan sessions, §8 Medium dead schemas, Phase-2-fragility #1 |
| WS4 rate-limit IP + 2FA recovery | e84ee9f | §1 Critical /2fa/recovery no limiter, §1 High rate limiter IP, §1 Medium 2fa/verify IP-only, §2 Low _ip XFF, Phase-2-fragility #2 |
| WS5 2FA re-auth | 1819784 | §1 Critical 2FA enable/disable no re-auth, Phase-2-fragility #8 |
| WS6 observability | 151a474 | §1 High JWT verify per request, §6 Medium redundant verify, §6 Low exception context, §6 Low Sentry request_id |
| WS7 email dispatch | e3384b4 | §2 Medium HTML interpolation, §3 High email in request path, §3 High asyncio.create_task, Phase-2-fragility #6 |
| WS8 logout auth + session revoke | 9c1aedc | §1 High logout unauth, §1 Medium email change no revoke |
| WS9 CORS, body, race, pending+locked | 2de0533 | §2 Medium CORS, §2 Medium body size, §1 Low device race, §1 Medium pending+locked |
| WS10 dead code + CI | 90e13c2 | §5 Medium CI ephemeral secrets, §5 Low seed.py DATABASE_URL, §7 High Trivy ignore-unfixed, §8 Medium jwt_refresh_secret, §4 Medium get_db (documented) |
| WS11 /auth/me | c304983 | §8 Medium CurrentUser orphan, Phase-2-fragility #3 |
| WS12 health-check hardening | fb39636 | §3 Medium health swallows exceptions, §3 Medium R2 unconfigured in prod, §6 Medium health masks drift |
| WS13 retention + partitioning | d380153 | §4 Medium rate_limit_counters / webhook_events_seen no retention, §4 Medium audit_logs unpartitioned, Phase-2-fragility #9 |
| WS14 documentation | — | ADR-012, phase docs, known-issues, Outline |

**Deferred to later phases** (documented, not implemented):
- TOTP MultiFernet rotation → Phase 5 (see `dev_plan/11_security_baseline.md §14` and `dev_plan/05_phase5_ios_app.md`)
- Prometheus /metrics → later phase (`dev_plan/11_security_baseline.md §14`)
- boto3 → aioboto3 → not planned (`dev_plan/11_security_baseline.md §14`)
- PII retention policy → Phase 2 data export/deletion work (`dev_plan/11_security_baseline.md §7` already specifies the schedule)
- Equipment categories seed data → Phase 4 Admin Panel (already tracked in `project_notes/known-issues.md`)
- Fly secrets verified on staging → ops concern at deploy time, not code fix

---

## Up-front note on branch state (historical, as of original review)

The review branch at review time was `fix-venv-runtime`. That branch's Dockerfile + fly-toml fixes landed on `main` via PR #21 before Phase 1 hardening started. The hardening branch was cut off the post-PR-21 main, so all subsequent commits build on the corrected runtime.

---

## 1) Authentication & authorization boundaries

### Critical
- **Refresh token is generated, stored, and then thrown away.** `api/routers/auth.py:126` returns `TokenResponse(access_token=result["access_token"])` and ignores `result["refresh_token"]`. `_complete_2fa_login` in `api/services/auth_service.py:646-650` has the same shape. `schemas/auth.py:81` has a comment that says "refresh_token is set as an HttpOnly cookie" — that cookie is never set. — **Resolved 2026-04-21 (eaf82d4):** login, /2fa/verify, /2fa/recovery now set the refresh token as an HttpOnly + SameSite=Strict cookie scoped to /api/v1/auth. Dead LogoutRequest / RefreshRequest schemas removed.
- **`confirm_2fa` does not require a password re-prompt.** `services/auth_service.py:552-571`. Anyone holding a valid access token (stolen via XSS, session hijack, etc.) can enable 2FA on the victim's account. Same shape for `disable_2fa` at `auth_service.py:653-673`. — **Resolved 2026-04-21 (1819784):** both endpoints now require the current password in addition to TOTP. Wrong password emits `user.2fa_reauth_failed` audit.
- **`/2fa/recovery` has no rate limiter.** `routers/auth.py:253-259`. — **Resolved 2026-04-21 (e84ee9f):** attached a stricter IP limiter (5/hour) + per-partial-token limiter (3 per 5-min lifetime) so the recovery path is no longer the asymmetric bypass.

### High
- **Rate limiter keys by `request.client.host`, not the real client IP.** `middleware/rate_limit.py:72`. — **Resolved 2026-04-21 (e84ee9f):** new `get_client_ip()` helper prefers `CF-Connecting-IP`, falls back to first `X-Forwarded-For`, then socket peer. Documented Cloudflare → Fly proxy chain assumption.
- **`middleware/structured_logging.py:22-25` decodes and verifies the JWT on every request.** — **Resolved 2026-04-21 (151a474):** auth middleware now stashes user_id on `request.state.user_id`; logging middleware reads it from the ASGI scope, no second decode.
- **`logout` is unauthenticated.** `routers/auth.py:150-156`. — **Resolved 2026-04-21 (9c1aedc):** /logout now requires Bearer auth via CurrentUserDep; still reads the cookie for revocation.

### Medium
- **Email change doesn't revoke sessions.** `services/auth_service.py:497-525`. — **Resolved 2026-04-21 (9c1aedc):** `confirm_email_change` now calls `session_service.revoke_all_for_user` after the email column flips.
- **`pending_verification` user can accumulate failed logins and get locked.** `services/auth_service.py:316-324`. — **Resolved 2026-04-21 (2de0533):** login reordered to check status before touching the failed-login counter. `confirm_password_reset` now also allows `pending_verification → active` so a user who lost their verify email can recover via reset.
- **`2FA verify` rate limiter is IP-only.** `middleware/rate_limit.py:110`. — **Resolved 2026-04-21 (e84ee9f):** added a per-partial-token limiter (5 per 5-min lifetime) in addition to the IP limiter.

### Low
- **Device fingerprint SELECT-then-INSERT race.** `services/auth_service.py:157-168`. — **Resolved 2026-04-21 (2de0533):** `_check_new_device` now uses `INSERT ... ON CONFLICT DO NOTHING RETURNING id`.

---

## 2) Input validation & injection surfaces

### Medium
- **Email template string interpolation without escaping.** `services/email_service.py:117-132`. — **Resolved 2026-04-21 (e3384b4):** `send_new_device_email` and `send_email_change_notification` now pass user-controlled fields through `html.escape()`.
- **No request body size limit.** — **Resolved 2026-04-21 (2de0533):** new `MaxBodySizeMiddleware` (1 MB default) rejects oversized bodies with 413 before FastAPI validation and bcrypt run.
- **CORS `allow_methods=["*"], allow_headers=["*"]` with `allow_credentials=True`.** `main.py:42-45`. — **Resolved 2026-04-21 (2de0533):** locked methods to `GET/POST/PUT/PATCH/DELETE/OPTIONS` and headers to `Authorization/Content-Type/X-Request-ID`.

### Low
- **`_ip()` trusts the first entry of `X-Forwarded-For` unconditionally.** `routers/auth.py:49-54`. — **Resolved 2026-04-21 (e84ee9f):** router-local helper removed; centralized `get_client_ip` prefers Cloudflare's `CF-Connecting-IP` (which Cloudflare rewrites authoritatively) before trusting XFF.
- **Rate limiter parses body JSON out-of-band.** `middleware/rate_limit.py:81-86`. — **No change:** Starlette caches `_body` after first read, current FastAPI versions are stable. Accepted risk; revisit on next FastAPI major.

### Noise
- All SQL parameterized via SQLAlchemy. No SQL injection surface.

---

## 3) Error handling & failure modes

### High
- **Email send is in the request path, raises on failure.** `services/email_service.py:34-36, :51-54` and `services/auth_service.py:214, :411`. — **Resolved 2026-04-21 (e3384b4):** all email helpers wrapped with `_safe_send` decorator (log + swallow). Auth service routes email dispatch through `_send_or_await` which uses FastAPI `BackgroundTasks` when a request is in flight. Register, password reset, 2FA recovery, etc. no longer 500 on SendGrid outages.
- **`asyncio.create_task(...)` for fire-and-forget emails.** `services/auth_service.py:336, :447, :630`. — **Resolved 2026-04-21 (e3384b4):** all three sites removed; emails go through `BackgroundTasks`.

### Medium
- **`health.py` returns 200 when R2 is `unconfigured`.** `routers/health.py:75-83`. — **Resolved 2026-04-21 (fb39636):** R2 is informational in dev/test/staging but required in production — `unconfigured` in prod returns 503 so config drift triggers the probe.
- **`health.py` swallows all exceptions.** `:22-27, :30-36, :55-59`. — **Resolved 2026-04-21 (fb39636):** each branch now calls `logger.exception` so Sentry + structured logs see the failure. Migration drift also emits expected-vs-found.

### Low
- **`_audit` writes are rolled back if the outer transaction fails.** `services/auth_service.py:123-136`. — **No change:** intentional; audit tied to persisted outcome. Documented in ADR-012.
- **Seed script commits at the end.** `scripts/seed.py:152`. — **No change:** acceptable; re-runs are idempotent via ON CONFLICT DO NOTHING.

---

## 4) State consistency & race conditions

### High
- **`_check_new_device` is a classic SELECT-then-INSERT race.** — **Resolved 2026-04-21 (2de0533):** see §1 Low.
- **Orphan sessions forever.** — **Resolved 2026-04-21 (eaf82d4):** refresh token is now returned via cookie, so login never creates unreachable `user_sessions` rows. WS13 (d380153) adds hourly cleanup for expired/long-revoked sessions as defense in depth.

### Medium
- **`rate_limit_counters` has no retention.** `webhook_events_seen` same. — **Resolved 2026-04-21 (d380153):** new `fn_sweep_retention()` invoked hourly by `temple-sweeper` Fly Machine deletes counters > 2h old and webhook rows past `expires_at`.
- **`audit_logs` is unpartitioned and unbounded.** — **Resolved 2026-04-21 (d380153):** migration 003 rewrites `audit_logs` as a monthly range-partitioned table on `created_at`; the hourly sweeper ensures the current + next 2 months of partitions exist.
- **`get_db` auto-commits on success.** `database/base.py:42-50`. — **No change, documented (90e13c2):** ADR-012 codifies the "one tx per request" contract; services needing multi-step work instantiate `AsyncSessionLocal()` directly.

### Low
- **`confirm_email_change` re-checks `email` uniqueness.** — **No change:** very narrow race; accepted.
- **TOTP orphan secret.** — **No change:** next `setup_2fa` overwrites it, which is the intended behavior. Worth a comment.

---

## 5) Secret & credential handling

### High
- **`scripts/seed.py:13` imports `from passlib.context import CryptContext`.** — **Resolved 2026-04-21 (90e13c2):** passlib removed from seed; switched to direct `bcrypt` matching `services/auth_service.py`. The stale passlib in `.venv` was also cleaned up by `uv sync` after WS2 (44b5b45) removed the dependency.
- **Dockerfile runtime still uses `uv run` and the `/app` tree is owned by root** (`api/Dockerfile:24-33`). — **Resolved before phase1-hardening branched:** landed on `main` via PR #21 / commit d6fb656 (adds `chown -R app:app /app`, sets `PATH=/app/.venv/bin:$PATH`, switches CMD to direct `uvicorn`). All three `infra/fly/temple-api-*.toml` now call `/app/.venv/bin/alembic upgrade head`.

### Medium
- **`TOTP_ENCRYPTION_KEY` is a single Fernet key with no rotation path.** — **Deferred to Phase 5 sprint-0** (`dev_plan/05_phase5_ios_app.md` and `dev_plan/11_security_baseline.md §14`). iOS adds the volume that makes rotation load-bearing.
- **CI's `deploy-prod` job generates ephemeral `JWT_SECRET_KEY`, `JWT_REFRESH_SECRET`, `TOTP_ENCRYPTION_KEY` at `.github/workflows/ci.yml:161-165` and never uses them.** — **Resolved 2026-04-21 (90e13c2):** entire block deleted; flyctl deploy reads app secrets server-side, so the generation was dead.

### Low
- **`seed.py` hardcodes the dev DATABASE_URL as its default fallback** (`scripts/seed.py:18`). — **Resolved 2026-04-21 (90e13c2):** `DATABASE_URL` is now required; seed exits cleanly if missing.

---

## 6) Logging & observability gaps

### Medium
- **Every request that carries a Bearer token decodes and fully verifies the JWT in `structured_logging.py`.** — **Resolved 2026-04-21 (151a474):** see §1 High.
- **PII in logs and long-term DB state.** — **Deferred to Phase 2 data-export/retention work** per `dev_plan/11_security_baseline.md §7` (already specifies the retention schedule). WS13's sweeper takes a first bite (sessions expire, counters prune) but doesn't yet apply row-level retention to `audit_logs`.
- **Health check masks configuration drift.** — **Resolved 2026-04-21 (fb39636):** see §3 Medium.

### Low
- **Structured log emits only `info` level and never includes exception context.** — **Resolved 2026-04-21 (151a474):** 5xx now logs at `error` level; uncaught exceptions that propagate past the app layer get a `logger.exception` line with exception class + traceback.
- **No `X-Request-ID` ↔ Sentry correlation.** — **Resolved 2026-04-21 (151a474):** `request_id.py` now calls `sentry_sdk.set_tag("request_id", rid)`.
- **No metrics endpoint / no Prometheus surface.** — **Deferred** (`dev_plan/11_security_baseline.md §14`).

### Noise
- BetterStack / UptimeRobot: manual checklist items. No change.

---

## 7) Dependency vulnerabilities

### High
- **`python-jose[cryptography]>=3.3`.** — **Resolved 2026-04-21 (44b5b45):** migrated to PyJWT 2.12. New unit test asserts `alg=none` tokens are rejected.
- **`bleach>=6.1` declared but not imported anywhere in Phase 1.** — **Resolved 2026-04-21 (44b5b45):** dependency removed. Phase 2 intake sanitization (per `dev_plan/11_security_baseline.md §3`) will re-add it when an actual consumer lands.
- **Trivy runs with `ignore-unfixed: true`.** — **Resolved 2026-04-21 (90e13c2):** flipped to `false`. Per-CVE suppressions must be documented in `.trivyignore` with justification.

### Medium
- **`passlib` removal incomplete.** — **Resolved 2026-04-21 (90e13c2 + 44b5b45):** `uv sync` cleaned the stale venv entry; seed.py was the only Phase-1 consumer and now uses direct `bcrypt`.
- **`python-jose[cryptography]` pulls both `cryptography` and jose's own primitives.** — **Resolved 2026-04-21 (44b5b45):** PyJWT uses `cryptography` only.

### Low
- **`boto3>=1.35`.** — **Deferred, not planned.** Flagged in `dev_plan/11_security_baseline.md §14` so an async S3 client becomes a considered option if the R2 code path becomes hot.

### Noise
- Dependabot volume: expected.

---

## 8) Dead / unreachable code

### Medium
- **`TokenResponse.refresh_token` comment (`schemas/auth.py:81`).** — **Resolved 2026-04-21 (eaf82d4):** comment removed.
- **`LogoutRequest` and `RefreshRequest` (`schemas/auth.py:94-99`).** — **Resolved 2026-04-21 (eaf82d4):** schemas deleted; router reads cookie.
- **`config.jwt_refresh_secret` (`config.py:30`).** — **Resolved 2026-04-21 (90e13c2):** field removed. `.env.example`, README, fly-provisioning docs, conftest defaults, and CI `$GITHUB_ENV` lines all cleaned up.
- **`CurrentUser` schema (`schemas/auth.py:170-178`).** — **Resolved 2026-04-21 (c304983):** wired to `GET /api/v1/auth/me`.

### Low
- **`database/__init__.py` re-exports `Base`.** — **No change:** harmless.
- **`routers/__init__.py`, `middleware/__init__.py`, `services/__init__.py`** empty. — **No change:** fine.
- **CI `deploy-prod` generates unused secrets.** — **Resolved 2026-04-21 (90e13c2)** (duplicate of §5 Medium).

---

# Phase 2 Fragility — What's Already Wrong Underneath

All 11 items either resolved or explicitly carry-forward as of 2026-04-21.

1. **Sessions don't work.** — **Resolved (eaf82d4).**
2. **Rate limiter is broken behind the Fly/Cloudflare proxy.** — **Resolved (e84ee9f).**
3. **No `GET /api/v1/auth/me` endpoint exists.** — **Resolved (c304983).**
4. **`python-jose` signs every token.** — **Resolved (44b5b45).**
5. **`get_db` auto-commits per request.** — **No change, documented (90e13c2 + ADR-012):** services that need multi-step transactions instantiate `AsyncSessionLocal()` directly.
6. **Email lives in the request path.** — **Resolved (e3384b4):** `BackgroundTasks` is the Phase-1 stopgap; Phase 2's intake email uses the `NotificationService` + `notification_jobs` queue per ADR-001 — noted in ADR-012.
7. **Equipment categories have no data.** — **Still open, tracked in `project_notes/known-issues.md`:** Phase 4 Admin Panel populates `category_components`, `category_inspection_prompts`, `category_photo_slots`, `category_red_flag_rules`.
8. **2FA enable/disable on access-token-only re-auth.** — **Resolved (1819784).**
9. **Rate-limit and webhook-dedup tables grow forever.** — **Resolved (d380153).**
10. **Fly secrets staged but not activated.** — **Deploy-time ops concern.** The first staging deploy off `phase1-hardening` exercises the full secret matrix; verify before Phase 2 touches R2.
11. **Dockerfile `USER app` + root-owned `/app`.** — **Resolved on `main` (PR #21 / d6fb656)** before hardening branch was cut.

## Shortlist to fix before Phase 2 lands

All five originally-flagged load-bearing items are resolved:

1. Refresh tokens (#1) — **eaf82d4**
2. Rate limiter IP (#2) — **e84ee9f**
3. `python-jose` → `PyJWT` (#4) — **44b5b45**
4. 2FA re-auth (#8) — **1819784**
5. Dockerfile runtime (#11) — **d6fb656 (on main before this branch)**
