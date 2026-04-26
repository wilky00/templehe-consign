# Deep Review Prompt Library

Structured prompts and static analysis commands for phase-boundary code reviews and ongoing quality audits. Run one focused pass at a time. LLM passes produce a triaged findings list — never diffs. Fix only after you've manually confirmed each finding is real.

---

## How to Run a Review

1. **Run static analysis first** (zero hallucination rate, fast). Commands in the next section.
2. **Run one LLM pass per category** — paste the prompt into a fresh Opus session with the relevant files or directory as context.
3. **Triage the output yourself** — mark each finding `real / noise / deferred` before touching any code.
4. **Create scoped fix tasks** — hand only real findings back to Claude with explicit acceptance criteria, one category at a time.

Do not ask Opus to "find all bugs" in one pass. That produces a mix of real findings, style opinions, confident hallucinations, and invented bugs.

---

## Static Analysis Commands

Your stack already runs Gitleaks, Trivy, pip-audit, and npm-audit in `.github/workflows/security.yml`. Run those in CI as-is. The two gaps to fill: **Bandit** (Python security linting) and **Semgrep** (cross-language SAST patterns). Add both locally and optionally to CI.

### Bandit — Python security linting

```bash
# Install (one-time)
cd api && uv add --dev bandit[toml]

# Run — medium+ severity, medium+ confidence
uv run bandit -r app/ -ll -ii

# Machine-readable output for diffing across sessions
uv run bandit -r app/ -f json -o bandit-report.json --severity-level medium --confidence-level medium
```

Add to `api/pyproject.toml` to suppress known false positives with context:

```toml
[tool.bandit]
exclude_dirs = ["tests"]
skips = []  # Add "B104" etc. here only with a comment explaining why
```

### Semgrep — cross-language SAST

```bash
# Install (one-time, requires Python)
pip install semgrep --break-system-packages

# Python/FastAPI backend
semgrep --config=p/python \
        --config=p/fastapi \
        --config=p/jwt \
        --config=p/sql-injection \
        --config=p/secrets \
        api/app/ \
        --json > semgrep-api.json

# TypeScript/React frontend
semgrep --config=p/typescript \
        --config=p/react \
        --config=p/xss \
        --config=p/javascript \
        web/src/ \
        --json > semgrep-web.json

# Human-readable (drop --json for terminal review)
semgrep --config=p/fastapi api/app/
```

### Already-configured tools (run locally to match CI)

```bash
# Secrets — scan full repo history
gitleaks detect --source . --report-path gitleaks-report.json

# Container CVEs — build image first, then scan
docker build -t templeapi:review api/
trivy image templeapi:review --severity HIGH,CRITICAL

docker build -t templeweb:review web/
trivy image templeweb:review --severity HIGH,CRITICAL

# Python dependency audit
cd api && pip-audit

# Node dependency audit
cd web && npm audit --audit-level=high
```

---

## LLM Review Prompts

Each prompt below is a complete, paste-ready instruction for an Opus session. Customize the bracketed `[PROJECT CONTEXT]` block for future projects. Everything else is reusable as-is.

---

### Pass 1 — Authentication & Authorization Boundaries

```
[PROJECT CONTEXT]
Stack: Python 3.12, FastAPI, PostgreSQL 16, SQLAlchemy async, PyJWT, bcrypt, pyotp.
Auth model: JWT bearer tokens. Role slugs: customer, sales, sales_manager, appraiser, admin, reporting.
The API lives in api/app/. Routes are in api/app/routers/. Auth utilities in api/app/core/security.py (or similar).

[TASK]
You are a security-focused senior engineer performing a targeted authentication and authorization review.
Do NOT review code style, performance, or anything outside auth/authz.

Specifically look for:
- Routes that are missing auth dependencies entirely (no Depends(get_current_user) or equivalent)
- Routes that check authentication but not authorization (authenticated != authorized)
- Role checks that are too broad (e.g., any authenticated user can reach a sales_manager endpoint)
- Role checks that use string comparison instead of an enum or constant (typo risk)
- JWT validation gaps: missing expiry check, missing signature verification, algorithm confusion (accepting "none" alg)
- Token refresh logic that doesn't invalidate the old token
- Password reset or OTP flows where the token can be reused after success
- Any endpoint that accepts a user_id from the request body and acts on it without verifying it matches the authenticated user
- Admin-only config or user-management routes that are reachable from non-admin roles
- CORS configuration that is too permissive for the environment

Output format: a triage table with columns: Severity (Critical/High/Medium/Low/Noise) | File | Line | Finding | Reasoning.
No diffs. No fix suggestions. Reasoning must explain why it is or isn't exploitable, not just what the code does.
If you are uncertain whether something is a real issue, say so and explain what you'd need to confirm it.
```

---

### Pass 2 — Input Validation & Injection Surfaces

```
[PROJECT CONTEXT]
Stack: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy async ORM, bleach for HTML sanitization,
boto3 for Cloudflare R2 object storage, Twilio for SMS, SendGrid for email.
Frontend: React 18, TypeScript strict, react-router-dom v6.

[TASK]
You are a security-focused senior engineer performing a targeted input validation and injection review.
Do NOT review auth, style, performance, or anything outside validation and injection.

Specifically look for:
- Any SQLAlchemy query that uses string interpolation or .text() with unsanitized input instead of bound parameters
- File upload handlers that don't validate MIME type, extension, or file size before writing to storage
- Object storage key construction that uses user-supplied input without sanitization (path traversal)
- SMS or email content that includes unsanitized user input (template injection, content spoofing)
- Pydantic models that use arbitrary_types_allowed or model_config without validation
- Fields that accept a string but should be constrained (e.g., phone number, email, status enum) with no pattern/enum constraint
- Any place bleach.clean() is called but the allowed_tags or allowed_attributes are too permissive
- React components that use dangerouslySetInnerHTML with any user-derived content
- URL parameters in the frontend router that are used in API calls or displayed without sanitization
- Integer overflow or type coercion bugs in numeric fields (e.g., price, quantity, year)
- Batch endpoints that accept arrays with no max-length constraint

Output format: a triage table with columns: Severity (Critical/High/Medium/Low/Noise) | File | Line | Finding | Reasoning.
No diffs. No fix suggestions. Reasoning must explain the injection vector and what an attacker could achieve.
```

---

### Pass 3 — Error Handling & Failure Modes

```
[PROJECT CONTEXT]
Stack: Python 3.12, FastAPI, asyncpg, SQLAlchemy async, Twilio, SendGrid, boto3/R2, structlog, Sentry.
FastAPI uses HTTPException for error responses. Background tasks may be handled via Postgres jobs table
and scheduled Fly machines.

[TASK]
You are a reliability-focused senior engineer performing a targeted error handling review.
Do NOT review auth, validation, style, or anything outside error handling and failure modes.

Specifically look for:
- Bare `except:` or `except Exception:` blocks that swallow errors silently (no log, no re-raise)
- External service calls (Twilio, SendGrid, boto3) that have no error handling at all
- External service calls that raise on failure but callers don't handle the exception
- Database operations inside a request handler that are not wrapped in a try/except or transaction rollback
- Background jobs that silently fail with no status update to the jobs table
- Any place where a 500 response leaks internal error details (stack traces, SQL, file paths) to the client
- Functions that return None on failure instead of raising, where callers don't check for None
- Async functions that create tasks with asyncio.create_task() without storing the reference (task GC drops exceptions)
- File or network operations that don't clean up resources on failure (missing finally or context manager)
- Retry logic that retries non-idempotent operations (e.g., retrying an SMS send that already fired)
- Places where an error in one item of a batch silently skips the rest with no reporting

Output format: a triage table with columns: Severity (Critical/High/Medium/Low/Noise) | File | Line | Finding | Reasoning.
No diffs. No fix suggestions. Explain what the user or operator would observe when the failure mode triggers.
```

---

### Pass 4 — State Consistency & Race Conditions

```
[PROJECT CONTEXT]
Stack: Python 3.12, FastAPI (async), SQLAlchemy async, PostgreSQL 16 (asyncpg driver).
Concurrency: multiple Fly machines running simultaneously. No Redis — distributed locking uses a
Postgres `record_locks` table and advisory locks (RecordLockService). Jobs tracked in a `jobs` table.
Status fields are common (equipment status, lead status, job status).

[TASK]
You are a reliability-focused senior engineer performing a targeted state consistency and race condition review.
Do NOT review auth, validation, error handling, or anything outside state and concurrency.

Specifically look for:
- Any place where code reads a record's status, makes a decision, then updates it without a transaction or lock
  (classic read-modify-write race)
- Status transitions that are not validated against an allowed transition graph (e.g., jumping from draft to approved)
- Any operation that should be atomic but spans multiple separate database statements without a transaction
- RecordLockService usage: locks that are not released on exception (no try/finally or context manager pattern)
- Advisory locks: any lock acquired but not released in all code paths
- Background jobs that are triggered twice concurrently with no idempotency guard
- Pagination or list queries that don't use a stable sort key (results shift under concurrent inserts)
- Counter or aggregate fields updated with Python arithmetic instead of a SQL UPDATE ... SET count = count + 1
  (lost update under concurrency)
- Soft-delete patterns where deleted records are still returned by queries that don't filter on deleted_at IS NULL
- Any place where SQLAlchemy's session.refresh() is absent after a concurrent update elsewhere

Output format: a triage table with columns: Severity (Critical/High/Medium/Low/Noise) | File | Line | Finding | Reasoning.
No diffs. No fix suggestions. Describe the specific sequence of concurrent events that triggers the bug.
```

---

### Pass 5 — Secret & Credential Handling

```
[PROJECT CONTEXT]
Stack: Python 3.12, FastAPI, pydantic-settings for config, structlog for logging, Sentry for error tracking.
Secrets in production via Fly secrets / environment variables. .env files for local dev (gitignored).
External services: Twilio (account SID + auth token + messaging service SID), SendGrid (API key),
Cloudflare R2 (access key + secret key + bucket name), JWT secret, PostgreSQL DSN, Sentry DSN.

[TASK]
You are a security-focused senior engineer performing a targeted secrets and credential handling review.
Do NOT review auth logic, validation, or anything outside secret storage, transmission, and logging.

Specifically look for:
- Any hardcoded secret, API key, password, or token in source code (not just .env — check config defaults too)
- pydantic-settings fields that have a non-empty default for a secret (e.g., jwt_secret: str = "changeme")
- structlog or standard logging statements that include request bodies, headers, or response payloads
  where a secret could appear (Authorization header, API key in query param, etc.)
- Sentry breadcrumbs or extra context that logs full request data including sensitive fields
- Database DSN logged at startup (common pattern that leaks credentials)
- boto3 or Twilio client initialization that logs credentials in debug mode
- Any place a secret is passed as a URL parameter (GET request with api_key=...) rather than a header
- Error messages or exception details that include credential values
- JWT payload that includes fields it shouldn't (e.g., storing the raw password hash, internal IDs that shouldn't be client-visible)
- .env.example that contains real values instead of placeholder strings

Output format: a triage table with columns: Severity (Critical/High/Medium/Low/Noise) | File | Line | Finding | Reasoning.
No diffs. No fix suggestions. Flag any finding where a secret could end up in logs, Sentry, or a response body.
```

---

### Pass 6 — Logging & Observability Gaps

```
[PROJECT CONTEXT]
Stack: Python 3.12, FastAPI, structlog, Sentry (sentry-sdk[fastapi]). Background jobs via Postgres jobs table
and scheduled Fly machines. External integrations: Twilio, SendGrid, boto3/R2.

[TASK]
You are a reliability-focused senior engineer performing a targeted logging and observability review.
Do NOT review auth, validation, error handling mechanics, or anything outside logging and observability.

Specifically look for:
- Significant operations that produce no log output at all (e.g., status changes, external service calls, job completions)
- Log statements that don't include enough context to reconstruct what happened
  (missing: user_id, entity_id, action, outcome — at minimum two of these)
- External service calls (Twilio, SendGrid, R2) where neither success nor failure is logged
- Background job start and completion that isn't logged with the job_id and result
- Sentry not capturing exception context (calling capture_exception inside a bare except without re-raising means
  you lose the original traceback in some SDK versions)
- Authentication failures that aren't logged (attacker enumeration attempts become invisible)
- Places where log level is wrong: debug-level logging for security events, or info-level for errors
- Any place where structured fields are inconsistent with adjacent log calls (e.g., same concept logged as
  "user_id", "userId", and "uid" in different files — breaks log aggregation queries)
- Request/response logging middleware that logs 4xx responses but not 5xx (or vice versa)
- Missing health check or startup log that confirms which environment and config is loaded

Output format: a triage table with columns: Severity (Critical/High/Medium/Low/Noise) | File | Line | Finding | Reasoning.
No diffs. No fix suggestions. For each gap, explain what an operator would be unable to diagnose in production.
```

---

### Pass 7 — Dependency Vulnerabilities & Supply Chain

```
[PROJECT CONTEXT]
Stack: Python 3.12 (uv, pyproject.toml), Node 22 / npm (package.json + package-lock.json).
Container base images: python:3.12.7-slim (API), nginx:1.27.2-alpine (web frontend).
Security CI already runs pip-audit, npm-audit, Trivy, and Gitleaks.

[TASK]
You are a security-focused senior engineer performing a dependency and supply chain review.
This pass is a complement to automated tools — focus on things scanners miss.

Specifically look for:
- Dependencies that are pinned to a range (>=x.y) where a known-bad version within that range exists
- Dependencies with no updates in 2+ years that handle security-sensitive operations (auth, crypto, parsing)
- Any dependency that is a thin wrapper around a native binary (C extension) with poor maintenance signals
- Direct use of deprecated or insecure stdlib modules (e.g., pickle, xml.etree without defusedxml,
  hashlib.md5 for security purposes, random instead of secrets)
- PyJWT usage: confirm algorithms are explicitly allowlisted, not auto-detected from token header
- cryptography library: confirm no use of deprecated primitives (MD5, SHA1, DES, ECB mode)
- bcrypt: confirm rounds are not below 12
- boto3: confirm no use of path-style S3 URLs (deprecated, SSRF risk in some configs)
- Frontend: any npm package installed from a GitHub URL or non-registry source
- Any package that was recently transferred to a new maintainer (typosquatting / account takeover risk —
  check if names look like common packages with subtle misspellings)

Output format: a triage table with columns: Severity (Critical/High/Medium/Low/Noise) | Package | Finding | Reasoning.
No diffs. No fix suggestions. Note the file and line if a specific usage pattern is the issue, not the dep itself.
```

---

### Pass 8 — Dead Code & Unreachable Paths

```
[PROJECT CONTEXT]
Stack: Python 3.12, FastAPI, React 18, TypeScript strict. The project has been built in phases —
earlier phases may have left scaffolding, stub endpoints, or feature flags that are now unreachable.

[TASK]
You are a senior engineer performing a targeted dead code and unreachable path review.
Do NOT review auth, validation, error handling, or anything outside dead/unreachable code.

Specifically look for:
- FastAPI routes that are defined but never called from any frontend code or test
- Functions defined but never imported or called in the Python codebase
- Pydantic models defined but not used in any route, service, or test
- Database models or columns that have no corresponding route, service method, or migration query
- TypeScript types or interfaces defined but never imported
- React components that are defined but never rendered
- Feature flag or environment checks that always evaluate to the same branch given the actual config values
- Commented-out code blocks longer than 5 lines (not inline explanations — actual commented-out logic)
- TODO or FIXME comments that reference functionality that was since implemented or abandoned
- Any import that is unused (ruff will catch some of these, but look for cross-module cases ruff misses)
- Database migration files that add columns or tables that were subsequently dropped in a later migration
  (the net result is a migration that does nothing useful)

Output format: a triage table with columns: Severity (Critical/High/Medium/Low/Noise) | File | Line | Finding | Reasoning.
No diffs. No fix suggestions. Distinguish between "dead but harmless" and "dead and misleading/risky."
```

---

### Pass 9 — Architectural Debt (Phase Boundary Prompt)

Run this at the end of each phase, before starting the next. The goal is to catch design decisions that are wrong or fragile before the next phase doubles down on them. This is the most valuable and most commonly skipped pass.

```
[PROJECT CONTEXT]
Stack: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy async, PostgreSQL 16, React 18, TypeScript strict.
The project is built in phases. A phase plan lives in dev_plan/. Project notes in project_notes/.

[CURRENT PHASE COMPLETED]: [e.g., Phase 2 — Customer Portal]
[NEXT PHASE STARTING]: [e.g., Phase 3 — Sales CRM]
[NEXT PHASE PLAN SUMMARY]: [paste the key deliverables from the phase plan file, ~10-20 lines]

[TASK]
You are a senior architect performing a phase-boundary architectural debt review. This is not a bug hunt.
Do NOT report individual bugs, style issues, or missing error handling.

The specific question is: what in [CURRENT PHASE] will [NEXT PHASE] be built on top of, where the design
is already wrong or fragile such that it will be significantly cheaper to fix now than after [NEXT PHASE]
builds on it?

Specifically look for:
- Data model decisions that will require breaking migrations once [NEXT PHASE] features are added
  (missing foreign keys, wrong cardinality, fields that need to become relations, etc.)
- API contracts — request/response shapes or URL patterns — that [NEXT PHASE] will need to extend in ways
  that break current clients
- Service interfaces (RecordLockService, NotificationService, SigningService, ValuationService) that have
  the wrong abstraction boundary for what [NEXT PHASE] will ask of them
- Auth/role model decisions that don't accommodate the new personas or permissions in [NEXT PHASE]
- State machine designs (status fields, transition rules) that don't have room for the new states [NEXT PHASE] requires
- Assumptions baked into existing code that [NEXT PHASE]'s features would violate
  (e.g., "one equipment item per submission" if Phase N adds multi-item submissions)
- Anything that is implemented as a stub or hardcoded value that [NEXT PHASE] will need to make dynamic

Output format:
For each issue: a short title, the files/lines involved, what specifically breaks when [NEXT PHASE] is built on top of it,
and a rough estimate of fix cost now vs. fix cost after [NEXT PHASE] (small/medium/large).
Severity: Critical (blocks the phase or requires a data migration) / High (significant rework) / Medium (annoying but manageable) / Low.
No diffs. No fix suggestions beyond what's needed to describe the problem clearly.
```

---

## Triage Workflow (After Each Pass)

Once Opus returns findings, do this before touching any code:

1. Open the findings list and go row by row.
2. For each finding, mark it one of:
   - **Real** — confirmed by reading the code yourself. Assign a severity.
   - **Noise** — false positive, misunderstood context, or style opinion. Document why so you don't re-investigate it.
   - **Deferred** — real but out of scope for this phase. Log it in `project_notes/known-issues.md`.
3. Create one fix task per **Real / Critical or High** finding. Include: file, line, what's wrong, acceptance criteria for the fix.
4. Fix and verify before moving to Medium/Low items.

Do not hand a batch of findings back to Claude as "fix all of these." That is the single biggest source of regressions in agentic cleanup passes.
