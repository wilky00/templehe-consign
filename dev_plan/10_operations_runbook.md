# Operations Runbook — Fly.io POC / MVP Platform

> **Audience:** Jim, supporting this platform remotely on an 8–24 hour SLA as a solo maintainer.
> **Philosophy:** Every operation is scripted or has a copy-paste command. If it isn't in this file, it isn't supported.
> **Read this file before running any `flyctl`, `neonctl`, or `git tag` command against a cloud environment.**
>
> **Hosting status:** The platform runs on Fly.io for POC and the initial production launch. GCP is the documented production target, not the current runtime. See `project_notes/decisions.md` ADR-001 for the decision context, `12_gcp_production_target.md` for the target architecture, and `13_hosting_migration_plan.md` for the cutover playbook.

---

## 1. Environment Architecture (POC on Fly.io)

### 1.1 Three Fly apps + managed Neon Postgres + local Docker

| Environment | Purpose | Where it runs | Who can deploy |
|---|---|---|---|
| **Local** | Day-to-day coding | Docker Compose on your laptop | You |
| **`temple-api-dev`** | Integration testing against cloud Postgres | Fly app, scale-to-zero, Neon `dev` branch | Auto-deploy on push to `develop` branch |
| **`temple-api-staging`** | Pre-prod mirror; E2E tests run here; release candidate validation | Fly app, scale-to-zero, Neon `staging` branch | Auto-deploy on merge to `main` |
| **`temple-api-prod`** | Customer-facing production | Fly app, `min-machines=1`, Neon `prod` primary (PITR enabled) | Tag `v*` + manual GitHub Actions approval |

Parallel Fly apps for the frontend: `temple-web-dev`, `temple-web-staging`, `temple-web-prod`.

**Why three Fly apps (not three Fly orgs):** blast-radius isolation at the app level is sufficient at this scale. Deploy tokens are app-scoped — a compromised dev deploy token can't reach prod. At GCP migration time, three apps become three GCP projects (`temple-dev`, `temple-staging`, `temple-prod`).

**Why Neon branches instead of three Postgres instances:** each Neon branch is isolated at the storage layer but shares compute, cutting cost. Every PR can also optionally spin up an ephemeral branch for integration tests — a meaningful AI-DLC win when Claude-driven PRs run in parallel.

**Why also local Docker:** most development never needs the cloud. Compose runs Postgres locally at no cost and ~10x faster to iterate against.

### 1.2 Realistic monthly cost (USD)

| Line item | Cost | Notes |
|---|---|---|
| Fly Machines (dev 256 MB scale-to-zero; staging 512 MB scale-to-zero; prod 512 MB `min-machines=1`). Sizing per `01_phase1_infrastructure_auth.md` Feature 1.1.2. | $3–8 | Dev + staging pay only while a Machine is up; prod runs continuously. API + web apps per env = 6 apps total; non-prod cost dominated by brief wake-ups. |
| Neon Pro (10 projects, autoscaling, PITR) | $19 | Free tier works for initial POC; upgrade when PITR is needed (before real customer data). |
| Cloudflare R2 (photos + PDFs, ≤ 10 GB) | $0 | Free tier 10 GB/month included |
| Cloudflare CDN + WAF (DNS proxy on prod) | $0 | Free plan includes managed WAF ruleset and DDoS protection |
| Sentry free | $0 | 5K errors/mo, 1 user; upgrade to Team ($26/mo) once team grows |
| UptimeRobot free | $0 | 50 monitors, 5-minute checks |
| BetterStack Logs free | $0 | 1 GB log retention/month — enough for POC |
| SendGrid free | $0 | 100 emails/day |
| Twilio (pay-as-you-go, low volume) | $2–10 | A2P 10DLC setup fees ~$4 one-time; per-SMS ~$0.008 |
| **Total** | **$24–37/mo** | Fits the $30 budget when Twilio volume is modest. |

Set Fly and Neon billing alerts at 50%, 80%, 100% of $40/mo. See §8.

### 1.3 Regions

Pick a primary region close to TempleHE customers. For most US heavy-equipment markets, **`iad`** (Ashburn, VA) or **`dfw`** (Dallas, TX) give good latency nationwide. Neon's corresponding regions are `aws-us-east-1` and `aws-us-east-2`. Keep the Fly region and Neon region in the same AWS region to minimize egress latency.

```bash
export FLY_REGION=iad
export NEON_REGION=aws-us-east-1
```

---

## 2. Initial One-Time Setup

Run these once, in order. Replace `YOUR_GITHUB_USER`, `YOUR_EMAIL`, and placeholders as noted.

### 2.1 Install prerequisites on your laptop

```bash
# macOS (per your CLAUDE.md macos.md standards)
brew install flyctl gh git pre-commit docker
brew install --cask orbstack    # lighter Docker alternative for macOS; or use Docker Desktop
npm install -g neonctl          # Neon CLI

# Verify
flyctl version
neonctl --version
gh --version
docker --version
```

### 2.2 Authenticate

```bash
flyctl auth login      # opens browser, creates Fly org "temple-he"
neonctl auth           # opens browser, creates Neon org
gh auth login          # GitHub CLI
```

**Enable 2FA on Fly, Neon, GitHub, Cloudflare, Sentry, SendGrid, Twilio accounts.** The platform's security posture depends on these accounts being hard to compromise.

### 2.3 Create the Fly apps

```bash
# Create an org-scoped Fly organization for TempleHE
# (done once during auth if you chose "Create new org"; verify in dashboard)
flyctl orgs list
export FLY_ORG=temple-he

# Create the six Fly apps — API + web, one per environment
for env in dev staging prod; do
  flyctl apps create "temple-api-${env}" --org $FLY_ORG
  flyctl apps create "temple-web-${env}" --org $FLY_ORG
done
```

Each app gets a public hostname at `https://temple-api-prod.fly.dev` etc. until you add custom domains (§2.7).

### 2.4 Create the Neon Postgres project

```bash
neonctl projects create --name temple-he --region-id $NEON_REGION

# Get the project id
export NEON_PROJECT_ID=$(neonctl projects list --output json | jq -r '.[] | select(.name=="temple-he") | .id')

# Create three branches rooted off the same primary
# Neon auto-creates a primary branch named "main" when the project is created.
# Rename it to "prod" so the three branch names match our environment naming,
# then create child branches for dev and staging rooted off prod.

# Find the primary branch id
PRIMARY_BRANCH_ID=$(neonctl branches list --project-id $NEON_PROJECT_ID --output json \
  | jq -r '.[] | select(.primary == true) | .id')

# Rename primary to "prod"
neonctl branches rename --project-id $NEON_PROJECT_ID --id $PRIMARY_BRANCH_ID --name prod

# Create dev and staging as branches off prod
neonctl branches create --project-id $NEON_PROJECT_ID --name dev --parent prod
neonctl branches create --project-id $NEON_PROJECT_ID --name staging --parent prod

# Connection strings per branch
neonctl connection-string --project-id $NEON_PROJECT_ID --branch dev --pooled
neonctl connection-string --project-id $NEON_PROJECT_ID --branch staging --pooled
neonctl connection-string --project-id $NEON_PROJECT_ID --branch prod --pooled
```

Always use the **pooled** connection string in Fly apps — Neon's PgBouncer-compatible pooler is what keeps the Fly Machines from exhausting Postgres connections on cold start.

### 2.5 Create the Cloudflare R2 bucket

```bash
# Sign up at dash.cloudflare.com (free), then:
# Dashboard → R2 → Create bucket: temple-he-photos
# Dashboard → R2 → Create bucket: temple-he-reports
# Dashboard → R2 → Create bucket: temple-he-backups   (used in §6)
# Dashboard → R2 → Manage R2 API Tokens → Create API token
#   - Permissions: Object Read & Write
#   - Specify buckets: the three above
#   - Save the Access Key ID + Secret Access Key — these go into fly secrets
```

Object versioning in R2 is opt-in per bucket. Enable it on all three:

```
Dashboard → R2 → temple-he-photos → Settings → Object Versioning → Enable
(repeat for temple-he-reports and temple-he-backups)
```

### 2.6 Put Cloudflare in front of prod for WAF + DDoS

```
Dashboard → Add Site → enter templehe.com (or your app domain)
Follow the nameserver swap instructions at your domain registrar
Once the site is active:
  - DNS → add CNAME api → temple-api-prod.fly.dev (Proxied: ON)
  - DNS → add CNAME app → temple-web-prod.fly.dev (Proxied: ON)
  - Security → WAF → Managed Rules → Cloudflare Managed Ruleset → Enable
  - Security → WAF → Rate Limiting → add rule: 100 requests/minute per IP on /api/*
  - SSL/TLS → Overview → Full (Strict)
  - SSL/TLS → Edge Certificates → Always Use HTTPS: ON
  - SSL/TLS → Edge Certificates → Minimum TLS Version: 1.2
  - SSL/TLS → Edge Certificates → HSTS: Enable (max-age 6 months, includeSubdomains, preload)
```

Dev and staging don't need the Cloudflare proxy — they use the default `*.fly.dev` hostnames. Only prod sits behind Cloudflare to get free WAF + DDoS + edge rate limiting.

Then tell Fly the custom hostnames so it provisions Let's Encrypt certs end-to-end (Cloudflare terminates one TLS hop, Fly the other — Full Strict requires both sides to have valid certs):

```bash
flyctl certs add api.templehe.com --app temple-api-prod
flyctl certs add app.templehe.com --app temple-web-prod
```

### 2.7 Create the GitHub repo

```bash
gh repo create temple-he-platform --private --source=. --remote=origin
git branch -M main
git push -u origin main
git checkout -b develop
git push -u origin develop
```

Branch strategy:
- `develop` = auto-deploys to dev apps (Neon `dev` branch)
- `main` = auto-deploys to staging apps (Neon `staging` branch)
- Git tags matching `v*` (e.g., `v0.1.0`) = deploy to prod apps (Neon `prod` branch) with manual approval

Branch protection rules (Settings → Branches):
- `main`: require PR, require status checks (CI green), require 1 review (your own counts via self-approval rule)
- `develop`: require PR, require CI green
- Restrict force pushes to `main` and `develop`

### 2.8 GitHub Actions deploy tokens (scoped per app)

Do **not** use your personal Fly token for CI. Create a deploy token scoped to each app:

```bash
for app in temple-api-dev temple-api-staging temple-api-prod temple-web-dev temple-web-staging temple-web-prod; do
  flyctl tokens create deploy \
    --app "$app" \
    --expiry 2160h \
    --name "github-actions-${app}" > ".fly-token-${app}"
  echo "Token for ${app} saved to .fly-token-${app}"
done
```

Add these as GitHub repo secrets, one per app (e.g., `FLY_TOKEN_TEMPLE_API_PROD`), then **delete the local files**. Rotate tokens every 90 days (§9 rotation schedule).

```bash
# After adding to GitHub secrets:
shred -u .fly-token-*
```

### 2.9 Configure GitHub environments with approval gates

In the GitHub repo, **Settings → Environments** and create three environments: `dev`, `staging`, `prod`.

- `dev`: no protection rules; secret `FLY_API_TOKEN` = `FLY_TOKEN_TEMPLE_API_DEV`
- `staging`: no protection rules; secret `FLY_API_TOKEN` = `FLY_TOKEN_TEMPLE_API_STAGING`
- `prod`: **Required reviewers: Jim**. Optional 5-minute wait timer. Secret `FLY_API_TOKEN` = `FLY_TOKEN_TEMPLE_API_PROD`

This is what gives you the one-click approval step before a prod deploy runs.

### 2.10 Populate `fly secrets` per environment

Every secret lives in `fly secrets`, encrypted at rest and mounted as env vars in the running Machine. Nothing about secret values ever lands in git.

```bash
# Run once per app, once per environment. Example for prod:
flyctl secrets set --app temple-api-prod \
  DATABASE_URL="$(neonctl connection-string --project-id $NEON_PROJECT_ID --branch prod --pooled)" \
  JWT_SIGNING_KEY="$(openssl rand -base64 64)" \
  JWT_REFRESH_KEY="$(openssl rand -base64 64)" \
  SENDGRID_API_KEY="SG.xxxx" \
  TWILIO_ACCOUNT_SID="ACxxxx" \
  TWILIO_AUTH_TOKEN="xxxx" \
  R2_ACCESS_KEY_ID="xxxx" \
  R2_SECRET_ACCESS_KEY="xxxx" \
  R2_ACCOUNT_ID="xxxx" \
  R2_BUCKET_PHOTOS="temple-he-photos" \
  R2_BUCKET_REPORTS="temple-he-reports" \
  SENTRY_DSN="https://xxx@sentry.io/xxx" \
  SENTRY_ENVIRONMENT="prod" \
  GOOGLE_MAPS_API_KEY="xxxx" \
  SLACK_WEBHOOK_URL="https://hooks.slack.com/xxx" \
  ADMIN_BOOTSTRAP_EMAIL="jim@templehe.com"
```

Setting a secret triggers a re-deploy. After every rotation, verify `/api/v1/health` is green.

---

## 3. Local Development Loop (the daily flow)

### 3.1 Spin up local stack

```bash
cd api
docker compose up -d    # starts Postgres + Mailpit (email trap)
make migrate            # runs alembic upgrade head
make seed               # loads seed data including 15 categories
make dev                # starts FastAPI with --reload on :8000
```

In another terminal:

```bash
cd web
npm install
npm run dev             # Vite dev server on :5173
```

Your frontend proxies `/api/*` to `http://localhost:8000`. Changes to code reload automatically.

**Note:** Local dev runs without Redis. Record locking uses Postgres advisory locks (same as Fly POC); this matches dev to staging/prod behavior. Redis comes back at GCP migration time.

### 3.2 Run tests before every commit

```bash
make test               # runs unit + integration tests for everything
make lint               # ruff + eslint + swiftlint
```

Pre-commit hooks enforce this on commit — CLAUDE.md says no `--no-verify`, so if something is failing, fix it.

### 3.3 Branch, commit, open PR

```bash
git checkout develop && git pull
git checkout -b feature/password-reset
# ... make changes with Claude Code ...
git add -p
git commit -m "Add password reset flow per phase 1 §1.3.5"
git push -u origin feature/password-reset
gh pr create --base develop --fill
```

GitHub Actions runs: lint → unit tests → integration tests → security scans. Claude Code `/review` and `/security-review` run locally before push. Squash-merge to `develop` triggers auto-deploy to `temple-api-dev`.

### 3.4 Ephemeral Neon branches per PR (AI-DLC accelerator)

Optional but powerful: every PR spins up its own Neon branch so the integration tests run against isolated data. The workflow step:

```yaml
- name: Create ephemeral Neon branch
  run: |
    BRANCH="pr-${{ github.event.pull_request.number }}"
    neonctl branches create --project-id ${{ secrets.NEON_PROJECT_ID }} --name "$BRANCH" --parent prod
    echo "DATABASE_URL=$(neonctl connection-string --project-id ${{ secrets.NEON_PROJECT_ID }} --branch $BRANCH --pooled)" >> $GITHUB_ENV

- name: Teardown Neon branch on PR close
  if: github.event.action == 'closed'
  run: neonctl branches delete --project-id ${{ secrets.NEON_PROJECT_ID }} --id "pr-${{ github.event.pull_request.number }}"
```

Free up to the first 10 branches on Neon Pro; perfect for a team of one to three.

---

## 4. Deployment Flow

### 4.1 The pipeline at a glance

```
feature-branch ──PR──▶ develop ──▶ [CI] ──▶ flyctl deploy --app temple-api-dev
                                                    │
                                                    ▼
                                          E2E tests against dev
                                                    │
develop ──PR──▶ main ──▶ [CI] ──▶ flyctl deploy --app temple-api-staging
                                                    │
                                                    ▼
                                    E2E + accessibility tests on staging
                                                    │
main ──git tag v*──▶ [CI + manual approval] ──▶ flyctl deploy --app temple-api-prod --strategy bluegreen
                                                    │
                                                    ▼
                                          Smoke tests + /health check
                                                    │
                                      ┌─ pass ──▶ blue/green swap
                                      └─ fail ──▶ flyctl releases rollback (§5)
```

### 4.2 The deploy workflow (GitHub Actions)

`.github/workflows/deploy.yml` (abbreviated):

```yaml
name: Deploy
on:
  push:
    branches: [develop, main]
    tags: ['v*']

jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: ${{ startsWith(github.ref, 'refs/tags/v') && 'prod' || (github.ref == 'refs/heads/main' && 'staging' || 'dev') }}
    steps:
      - uses: actions/checkout@v4
      - uses: superfly/flyctl-actions/setup-flyctl@master

      - name: Run DB migrations
        env:
          FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}
        run: |
          APP="temple-api-${{ env.ENV_SLUG }}"
          flyctl ssh console --app "$APP" --command "alembic upgrade head"

      - name: Deploy API
        env:
          FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}
        run: |
          APP="temple-api-${{ env.ENV_SLUG }}"
          flyctl deploy --app "$APP" \
            --image-label "git-${{ github.sha }}" \
            --strategy bluegreen \
            --wait-timeout 300

      - name: Smoke test
        run: |
          for i in 1 2 3; do
            curl -fsSL "https://${{ env.APP_HOSTNAME }}/api/v1/health" && break
            sleep 10
          done

      - name: Rollback on failure
        if: failure()
        env:
          FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}
        run: flyctl releases rollback --app "temple-api-${{ env.ENV_SLUG }}" --yes

      - name: Notify Sentry of release
        env:
          SENTRY_AUTH_TOKEN: ${{ secrets.SENTRY_AUTH_TOKEN }}
        run: |
          npx @sentry/cli releases new "git-${{ github.sha }}"
          npx @sentry/cli releases set-commits "git-${{ github.sha }}" --auto
          npx @sentry/cli releases finalize "git-${{ github.sha }}"
          npx @sentry/cli releases deploys "git-${{ github.sha }}" new -e "${{ env.ENV_SLUG }}"
```

### 4.3 Cutting a production release

```bash
# Make sure staging is green
gh run list --branch main --limit 1
gh run view <run-id>    # confirm all green

# Tag a version (semantic versioning)
git checkout main && git pull
git tag v0.3.0 -m "Release 0.3.0 — adds password reset + rate limiting"
git push origin v0.3.0
```

The tag push triggers the prod workflow. Go to **GitHub → Actions → Deploy** and click **Review deployments → prod → Approve**. The workflow:

1. Runs `alembic upgrade head` against the prod Neon branch
2. `flyctl deploy --strategy bluegreen` — new Machine starts, old Machine keeps serving
3. Smoke test hits `/api/v1/health` on the new revision
4. If green: Fly swaps traffic atomically to the new Machine, old one drains
5. If red: `flyctl releases rollback --yes` brings the old Machine back immediately

### 4.4 Database migrations

**Always forward-only. Always reversible.** Every Alembic migration has a working `downgrade()` — tested locally before commit.

Migrations run *before* the Fly deploy, so a broken migration blocks the deploy. If a migration fails mid-run:

```bash
# Check what happened — migrations are logged to Fly and to Sentry
flyctl logs --app temple-api-prod --no-tail | grep -i alembic | tail -50

# Roll the migration back manually
flyctl ssh console --app temple-api-prod --command "alembic downgrade -1"
```

Destructive migrations (DROP COLUMN, TYPE changes) are split into two releases:

1. Release N: deploy code that reads + writes both old and new columns
2. Release N+1: drop the old column after verifying no traffic references it

Never ship a destructive migration and the code that depends on it in the same release.

---

## 5. Rollback Procedures

### 5.1 Fast rollback (code only) — 30 seconds

Fly keeps every release image tagged and addressable. Roll back the running Machines to the prior release:

```bash
# List recent releases
flyctl releases --app temple-api-prod --limit 5

# Roll back one release (the default)
flyctl releases rollback --app temple-api-prod --yes

# Or roll back to a specific version
flyctl releases rollback --app temple-api-prod --version 42 --yes
```

Frontend follows the same pattern on its own Fly app:

```bash
flyctl releases rollback --app temple-web-prod --yes
```

### 5.2 Rollback including a DB migration — 5–15 minutes

If the bad release shipped a migration:

1. Roll code traffic back first (§5.1)
2. Run the downgrade:
   ```bash
   flyctl ssh console --app temple-api-prod --command "alembic downgrade -1"
   ```
3. Confirm schema matches the code now serving:
   ```bash
   flyctl ssh console --app temple-api-prod --command "alembic current"
   ```
4. If the downgrade itself fails and data was corrupted, use Neon PITR (§6.3) to restore to a pre-migration timestamp.

### 5.3 "Prod is completely broken" — the panic path

If the API is returning 5xx for all requests and rollback doesn't help:

```bash
# Put the API into maintenance mode
flyctl secrets set MAINTENANCE_MODE=true --app temple-api-prod

# (This triggers a redeploy; Fly picks up the new secret and the middleware returns 503
# + a friendly HTML page to all requests except /api/v1/health.)
```

Once fixed:

```bash
flyctl secrets unset MAINTENANCE_MODE --app temple-api-prod
```

### 5.4 Cloudflare "Under Attack" mode

If prod is under active DDoS beyond what the free WAF handles:

```
Cloudflare Dashboard → templehe.com → Security → Settings → Security Level: Under Attack
```

All visitors get a JS challenge before reaching Fly. Keep "Under Attack" on for the duration of the event, then drop back to Medium.

---

## 6. Backup & Disaster Recovery

### 6.1 Recovery targets (committed)

| Metric | Target | Notes |
|---|---|---|
| **RTO** (time to restore service) | 4 hours | Realistic for solo support. |
| **RPO** (max acceptable data loss) | 1 hour | Neon PITR retains WAL for 7 days on Pro. |
| **Backup retention** | 7 days PITR + 30 days daily `pg_dump` to R2 + 1 year of monthly archives | |
| **Restore drill frequency** | Every quarter | On calendar, not optional. |

### 6.2 What's backed up and how

**Neon Postgres (primary backup):**
- Neon Pro: automatic continuous backup via WAL; PITR to any second within the last **7 days**.
- Neon branches double as instant snapshots — create a branch named `snapshot-YYYYMMDD` before any risky operation, delete once verified safe.

**Off-site daily `pg_dump` to Cloudflare R2 (defense in depth):**

A Fly Machine runs daily at 03:00 UTC and dumps each branch to R2. If Neon itself fails, these dumps are restorable into any Postgres.

`infra/fly-backup/fly.toml`:

```toml
app = "temple-he-backup"
primary_region = "iad"

[processes]
app = "/usr/local/bin/backup.sh"

[deploy]
strategy = "immediate"

[[machine_config.schedule]]
# Every day at 03:00 UTC
schedule = "0 3 * * *"
```

`infra/fly-backup/backup.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
DATE=$(date -u +%Y%m%d)

for branch in prod staging; do
  DUMP_FILE="temple-${branch}-${DATE}.sql.gz"
  pg_dump "$DATABASE_URL_${branch^^}" --no-owner --no-privileges \
    | gzip -9 > "/tmp/${DUMP_FILE}"

  # Upload to R2 via aws-cli (R2 is S3-compatible)
  aws s3 cp "/tmp/${DUMP_FILE}" "s3://temple-he-backups/pg/${branch}/${DUMP_FILE}" \
    --endpoint-url "https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com" \
    --only-show-errors

  rm "/tmp/${DUMP_FILE}"
done

# Retention: R2 lifecycle rule deletes objects older than 30 days from pg/
# (configured in Cloudflare dashboard or via wrangler)

# Monthly archive: on the 1st of each month, also copy to pg-archive/ which has
# no lifecycle rule (kept 1 year)
if [[ $(date -u +%d) == "01" ]]; then
  for branch in prod staging; do
    DUMP_FILE="temple-${branch}-${DATE}.sql.gz"
    aws s3 cp "s3://temple-he-backups/pg/${branch}/${DUMP_FILE}" \
              "s3://temple-he-backups/pg-archive/${branch}/${DUMP_FILE}" \
      --endpoint-url "https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
  done
fi
```

**Cloudflare R2 (photos + PDFs):**
- **Object versioning enabled** on all three buckets — deletes and overwrites are recoverable
- R2 lifecycle rule: photo versions older than 90 days are deleted (keeps costs down)
- Prod bucket access restricted to the prod Fly app's R2 API token (rotated quarterly)

**Secrets:** `fly secrets list` exports the names but not values. Export values quarterly to an encrypted offline archive (§6.5).

### 6.3 Restoring from backup — step by step

**Scenario A: PITR restore to a timestamp within the last 7 days (e.g., bad DELETE swept through customers table).**

```bash
# 1. Confirm the timestamp you want to restore to (UTC)
export RESTORE_TIME="2026-04-18T14:00:00Z"

# 2. Create a branch from the prod branch at that timestamp
neonctl branches create --project-id $NEON_PROJECT_ID \
  --name "restore-$(date +%s)" \
  --parent prod \
  --parent-timestamp "$RESTORE_TIME"

# 3. Get its connection string
neonctl connection-string --project-id $NEON_PROJECT_ID \
  --branch "restore-..." --pooled

# 4. Inspect the restored data
psql "$RESTORED_URL" -c "SELECT count(*) FROM customers"

# 5. Extract the tables you need and reimport to the live prod branch
pg_dump "$RESTORED_URL" -t customers -t equipment_records \
        --data-only --on-conflict=do-nothing \
        > /tmp/recovered.sql
psql "$PROD_URL" < /tmp/recovered.sql

# 6. Delete the restore branch
neonctl branches delete --project-id $NEON_PROJECT_ID --id <branch-id>
```

**Scenario B: restore from the R2 daily dump (Neon itself unavailable, or data loss > 7 days old).**

```bash
# 1. Download the dump
aws s3 cp s3://temple-he-backups/pg/prod/temple-prod-20260415.sql.gz /tmp/ \
  --endpoint-url "https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com"

gunzip /tmp/temple-prod-20260415.sql.gz

# 2a. If Neon is available, restore into a new branch
neonctl branches create --project-id $NEON_PROJECT_ID --name "restore-from-dump"
psql "$NEW_BRANCH_URL" < /tmp/temple-prod-20260415.sql

# 2b. If Neon is down, spin up a Fly Postgres app as a temporary home
flyctl postgres create --name temple-pg-emergency --region iad \
  --initial-cluster-size 1 --vm-size shared-cpu-1x
flyctl postgres attach temple-pg-emergency --app temple-api-prod
psql "$FLY_PG_URL" < /tmp/temple-prod-20260415.sql
# Update DATABASE_URL via fly secrets set, redeploy
```

### 6.4 Quarterly restore drill (mandatory)

Set a recurring calendar event: **first Monday of each quarter, 2 hours blocked.**

```bash
# 1. Pick a random timestamp from last week
# 2. Run the PITR procedure above against the staging branch (never prod)
# 3. Spot-check: row counts, a known equipment record, a known customer
# 4. Write a 3-sentence summary in project_notes/drills.md with date + result
# 5. Delete the cloned branch
# 6. Also verify the R2 dump workflow: download yesterday's dump, load into a throwaway
#    Neon branch, confirm table counts match expectations
```

If the drill ever fails, the issue is logged as a P1 and fixed before the next deploy.

### 6.5 Offline encrypted backup of secrets

Quarterly, export `fly secrets` + Neon + Cloudflare API tokens to an encrypted archive you keep somewhere not on Fly (external drive, 1Password vault, whatever):

```bash
mkdir -p /tmp/secrets-backup
cd /tmp/secrets-backup

# Fly secret names (values can't be read back from Fly — they're write-only)
# Keep your source-of-truth values in 1Password, this script verifies the names are current
for app in temple-api-dev temple-api-staging temple-api-prod; do
  flyctl secrets list --app "$app" --json > "${app}.json"
done

# Neon + Cloudflare + SendGrid + Twilio API keys are in 1Password; export the Secret IDs
# for reference.

# Encrypt
tar czf - . | gpg -c --output "/tmp/temple-secrets-$(date +%Y%m%d).tar.gz.gpg"
rm -rf /tmp/secrets-backup
```

Store the encrypted archive outside Fly. The passphrase lives in your password manager.

---

## 7. Monitoring & Alerts

### 7.1 The monitoring stack (all free or cheap)

| Tool | What it does | Cost |
|---|---|---|
| **Fly built-in metrics** | CPU, memory, request rate, response status per Machine | Free |
| **BetterStack Logs** | Long-retention log storage (Fly only retains logs briefly); searchable UI | Free: 1 GB/mo |
| **Sentry** (free tier) | Application errors with stack traces, deploy tracking, release correlation | Free: 5K errors/mo |
| **UptimeRobot** | External HTTP checks from multiple regions, Slack/email/SMS alerts | Free: 50 monitors, 5-min interval |
| **Cloudflare Analytics** | Edge traffic, WAF hits, rate limit blocks | Free |
| **Slack** (your existing) | Where all alerts land | Free |

No DataDog, no PagerDuty, no New Relic. You don't need them at this scale.

### 7.2 What to instrument (Phase 1 acceptance criteria additions)

All FastAPI routes emit structured JSON logs with these fields:

```json
{
  "timestamp": "2026-04-18T14:32:11Z",
  "severity": "INFO",
  "request_id": "uuid",
  "user_id": "uuid or null",
  "route": "POST /api/v1/equipment-records",
  "status_code": 201,
  "latency_ms": 142,
  "error": null
}
```

Fly pipes container stdout/stderr to its log stream. The Fly `log_shipper` feature (free) forwards to BetterStack:

```bash
# One-time setup per app
flyctl logs-shipper create --app temple-api-prod \
  --type betterstack \
  --token $BETTERSTACK_SOURCE_TOKEN
```

All `ERROR`-severity logs are forwarded to Sentry automatically via the Sentry Python SDK.

### 7.3 Alert policies

| Alert | Where defined | Condition | Channel | Priority |
|---|---|---|---|---|
| Uptime check (`/api/v1/health`) on prod | UptimeRobot | 2 consecutive failures (10 min) | Slack #alerts + email + SMS | P0 |
| Fly Machine OOM | Fly metrics → Slack | Memory > 90% for 5 min | Slack #alerts | P1 |
| API 5xx rate | BetterStack alert | > 1% of requests over 5 min | Slack #alerts + email | P1 |
| API latency | BetterStack alert | P95 > 2s for 10 min | Slack #alerts | P2 |
| Neon connection failures | BetterStack alert | any occurrence in 5 min | Slack #alerts + email | P1 |
| Neon storage | Neon dashboard + manual check | > 80% of plan quota | Slack #alerts | P2 |
| Sentry new issue | Sentry → Slack integration | severity=error in prod | Slack #alerts | P2 |
| Cloudflare WAF spike | Cloudflare Notifications | > 1000 blocks/hour | email | P2 |
| Daily backup job | BetterStack alert | backup Fly Machine did not log success by 04:00 UTC | Slack #alerts + email | P1 |
| Fly + Neon + Cloudflare billing | vendor dashboards | > 80% of budget | email | P2 |

P0 alerts go to SMS via UptimeRobot (free plan includes 3 SMS channels) so a 2am outage actually wakes you up.

### 7.4 Uptime checks (UptimeRobot)

```
Create monitors:
  1. https://api.templehe.com/api/v1/health      — HTTP(s), 5-min, alert on 2 failures
  2. https://app.templehe.com                    — HTTP(s), 5-min, alert on 2 failures
Alert contacts: Slack #alerts, your email, your cell SMS
```

### 7.5 Sentry setup

```bash
# Sign up at sentry.io, create org "temple-he"
# Create 3 projects: temple-api-dev, temple-api-staging, temple-api-prod
# Plus 1 for the iOS app: temple-ios

# In the API: pip install sentry-sdk[fastapi]
# In fly secrets:
#   SENTRY_DSN=<per-environment>
#   SENTRY_ENVIRONMENT=dev|staging|prod
#   SENTRY_RELEASE=git-<sha>   (set by GitHub Actions at deploy time)
```

Every deploy posts a `sentry-cli releases new` so Sentry can show you "this error started in release v0.3.2."

### 7.6 Daily triage ritual (5–10 minutes)

Every morning (or every other day):

1. Open Sentry — any new issues in prod? Resolve or create a GitHub issue.
2. Open BetterStack — scan the last 24 hours of ERROR-severity logs.
3. Open UptimeRobot dashboard — confirm 100% uptime overnight.
4. Open the `#alerts` Slack channel — scroll back, confirm anything active is acknowledged.
5. Open Fly dashboard → Billing and Neon dashboard → Billing — glance at cost trend.

That's it. The alerts are the system of record.

---

## 8. Cost Management

### 8.1 Set budget alerts

- **Fly:** Dashboard → Billing → Spend Alerts → set $40/mo threshold (covers 3 apps + backup Machine)
- **Neon:** Dashboard → Billing → Usage Alerts → set $25/mo threshold
- **Cloudflare:** mostly free; monitor R2 egress
- **Twilio:** Dashboard → Usage Triggers → alert at $20/mo
- **SendGrid:** Dashboard → Stats — manual weekly check

### 8.2 Cost drivers to watch

1. **Neon storage growth** — `audit_logs` grow forever. Phase 4 §4.4 should include an archival job (move rows > 2 years old into R2 cold storage).
2. **Google Maps Distance Matrix calls** — Phase 3 caches these in the API for 6 hours. Monitor via Google Cloud Console; cap quota if it spikes.
3. **R2 egress** — R2 class B operations (reads) cost $0.36 per million. At SMB scale, negligible. Monitor Cloudflare → R2 → Metrics.
4. **Fly Machine hours** — prod API runs 24/7. If cold starts are acceptable for dev/staging, ensure `min-machines-running=0` on those apps.
5. **Twilio SMS volume** — watch A2P 10DLC campaign throughput and error rate.

### 8.3 Scale-to-zero audit

Run monthly to catch drift:

```bash
for app in temple-api-dev temple-api-staging temple-web-dev temple-web-staging; do
  echo "== $app =="
  flyctl status --app "$app" | grep -E "(Name|State|Min machines)"
done
```

Dev and staging should all show `min machines running: 0`. Prod should show `min machines running: 1`.

---

## 9. GitHub Security Scanning (all free)

### 9.1 What runs and when

| Scanner | Scope | Trigger | Blocks merge? |
|---|---|---|---|
| **Dependabot** | Python, npm, Swift, Docker base images, GitHub Actions | Daily, auto-PR on vuln | No (Jim reviews, merges) |
| **Secret scanning + push protection** | Known credential patterns (API keys, tokens) | On every push | **Yes** — blocks the push |
| **gitleaks** (action) | Broader secret patterns, historical commits | Every PR | **Yes** — fails CI |
| **Trivy** (action) | Container images + filesystem for OS package CVEs, misconfigurations | Every PR | Yes, on HIGH/CRITICAL |
| **pip-audit** | Python deps for CVEs (complements Dependabot) | Every PR | Yes, on HIGH/CRITICAL |
| **npm audit** | Node deps | Every PR | Yes, on HIGH/CRITICAL |
| **OSV-Scanner** | Catch-all across ecosystems | Weekly scheduled | No, file as issues |

### 9.2 Enable Dependabot

Create `.github/dependabot.yml`:

```yaml
version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/api"
    schedule: { interval: "daily" }
    open-pull-requests-limit: 10
    labels: ["dependencies", "security"]

  - package-ecosystem: "npm"
    directory: "/web"
    schedule: { interval: "daily" }
    open-pull-requests-limit: 10
    labels: ["dependencies", "security"]

  - package-ecosystem: "swift"
    directory: "/ios"
    schedule: { interval: "weekly" }
    labels: ["dependencies", "security"]

  - package-ecosystem: "docker"
    directory: "/api"
    schedule: { interval: "weekly" }

  - package-ecosystem: "github-actions"
    directory: "/"
    schedule: { interval: "weekly" }
```

Then in **GitHub Settings → Code security**:
- Enable Dependabot alerts
- Enable Dependabot security updates
- Enable secret scanning
- Enable push protection for secrets

All free for private repos.

### 9.3 Security scans in CI

`.github/workflows/security.yml`:

```yaml
name: Security
on:
  pull_request:
  push:
    branches: [main, develop]
  schedule:
    - cron: '0 6 * * 1'    # weekly OSV scan

jobs:
  gitleaks:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - uses: gitleaks/gitleaks-action@v2

  trivy-fs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: aquasecurity/trivy-action@master
        with:
          scan-type: fs
          severity: HIGH,CRITICAL
          exit-code: '1'
          ignore-unfixed: true

  trivy-image:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: docker build -t temple-api:scan ./api
      - uses: aquasecurity/trivy-action@master
        with:
          image-ref: temple-api:scan
          severity: HIGH,CRITICAL
          exit-code: '1'
          ignore-unfixed: true

  pip-audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: pip install pip-audit
      - run: pip-audit -r api/requirements.txt --strict

  osv-scan:
    if: github.event_name == 'schedule'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: google/osv-scanner-action/osv-scanner-action@v1
```

### 9.4 Secrets rotation schedule

| Secret | Rotation cadence | How |
|---|---|---|
| Fly deploy tokens (per app) | 90 days | `flyctl tokens create deploy` + update GitHub secrets; revoke old via `flyctl tokens revoke` |
| Neon Postgres user password | 90 days | `neonctl branches roles reset-password ...` + `flyctl secrets set DATABASE_URL=...` |
| JWT signing keys (access + refresh) | 180 days | `flyctl secrets set JWT_SIGNING_KEY=...`; forces re-login for all users — plan on a Sunday morning |
| R2 API tokens | 90 days | Cloudflare dashboard → regenerate → `flyctl secrets set R2_*` |
| SendGrid API key | 180 days | SendGrid dashboard → regenerate → `flyctl secrets set SENDGRID_API_KEY=...` |
| Twilio auth token | 180 days | Twilio dashboard → regenerate → `flyctl secrets set TWILIO_AUTH_TOKEN=...` |
| Sentry DSN | only on compromise | project-scoped, low sensitivity |

Automation: a monthly scheduled task (see `schedule` skill) emails Jim a checklist of what's due. See `11_security_baseline.md` §4 for the full rotation policy.

### 9.5 The Claude security review

Per CLAUDE.md, before every push to `main` or tag to prod:

```bash
/security-review
```

This runs a deeper, context-aware review against the actual diff, catching issues the scanners won't (auth logic gaps, authorization bypasses, logic errors). Not a substitute for scanners — complementary.

### 9.6 When a Dependabot PR arrives

1. Review the changelog linked in the PR
2. Check CI — if green, the change didn't break anything
3. Patch/minor updates: merge after CI passes
4. Major updates: read the migration guide, merge if safe, defer if it requires code changes (create an issue to track)

Don't let them pile up — review weekly minimum.

---

## 10. Fly.io Production Hardening Checklist

These are the security and reliability settings that make the POC deployment safe for real production traffic at small scale. Verify each one on prod before cutover to real customers.

### 10.1 App-level settings

- [ ] `min_machines_running = 1` on prod API (no cold starts for customer-facing traffic)
- [ ] `auto_stop_machines = true` on dev and staging; `false` on prod
- [ ] Internal port `8000`; Fly handles TLS termination at 443
- [ ] Health check at `/api/v1/health` configured in `fly.toml` with grace period 30s
- [ ] `kill_signal = "SIGTERM"` + `kill_timeout = "30s"` for graceful shutdown
- [ ] Concurrency limits set: soft 25, hard 50 per Machine (tune after load test)

Example `fly.toml` snippet:

```toml
[[services]]
  internal_port = 8000
  protocol = "tcp"

  [services.concurrency]
    type = "requests"
    hard_limit = 50
    soft_limit = 25

  [[services.ports]]
    port = 443
    handlers = ["tls", "http"]

  [[services.ports]]
    port = 80
    handlers = ["http"]
    force_https = true

  [[services.http_checks]]
    path = "/api/v1/health"
    interval = "15s"
    grace_period = "30s"
    method = "get"
    timeout = "10s"
```

### 10.2 Private networking

- [ ] App-to-app communication uses Fly's **6PN** private IPv6 network (`http://temple-api-prod.internal:8000`), never the public `*.fly.dev` hostname
- [ ] Backup Machine in a separate Fly app reaches Neon over Neon's private endpoint, not the public URL
- [ ] iOS app talks to the public hostname behind Cloudflare — there is no direct exposure of `*.fly.dev` to customers

### 10.3 Secrets and environment

- [ ] **Zero secrets in `fly.toml`, Dockerfile, or git history** — all via `fly secrets set`
- [ ] `DATABASE_URL` uses the Neon pooled connection string (PgBouncer), not the direct one
- [ ] Runtime environment is `production`; `DEBUG=false`; FastAPI `docs_url=None` on prod
- [ ] `.env.example` committed with placeholders; `.env` in `.gitignore`

### 10.4 Image and build

- [ ] Dockerfile uses a pinned base (`python:3.12.9-slim-bookworm`, not `:slim`)
- [ ] Multi-stage build: deps installed in builder stage, app runs as non-root user
- [ ] `USER app` before the CMD; no root at runtime
- [ ] Trivy scan green on every PR (see §9)

### 10.5 Network edge

- [ ] Cloudflare proxy ON for prod hostnames; SSL/TLS Full (Strict)
- [ ] Cloudflare Managed Ruleset enabled on prod zone
- [ ] Cloudflare Rate Limiting: 100 requests/minute per IP on `/api/*`
- [ ] Cloudflare Bot Fight Mode enabled
- [ ] Cloudflare "Always Use HTTPS" + HSTS 6 months + includeSubdomains + preload

### 10.6 Access control

- [ ] Fly org requires 2FA for all members
- [ ] Per-app deploy tokens (not personal tokens) used by GitHub Actions
- [ ] GitHub repo private; Settings → Moderation → Require 2FA for all collaborators
- [ ] Neon org requires 2FA; API keys scoped per environment
- [ ] Cloudflare, Sentry, SendGrid, Twilio all have 2FA enabled on Jim's account

### 10.7 Data

- [ ] Neon Pro plan active with PITR 7 days
- [ ] Daily `pg_dump` backup Fly Machine running (§6.2)
- [ ] R2 object versioning enabled on all three buckets
- [ ] R2 lifecycle rules reviewed quarterly (old photos → Infrequent Access class if/when R2 adds it)
- [ ] Alembic migrations include tested `downgrade()` paths

### 10.8 Observability

- [ ] Sentry wired, DSN per environment
- [ ] BetterStack log shipper active for prod API + prod web
- [ ] UptimeRobot monitors on prod hostnames, alerting to SMS + Slack + email
- [ ] GitHub Actions posts deploy events to Sentry via `sentry-cli releases`
- [ ] Structured JSON logging verified in BetterStack

### 10.9 CI/CD

- [ ] Security scanning workflow (§9.3) passing on `main`
- [ ] Branch protection on `main` and `develop`: require CI green, require PR review
- [ ] prod GitHub Environment: required reviewer = Jim, 5-minute wait timer
- [ ] pre-commit hooks on laptop: ruff, eslint, swiftlint, gitleaks
- [ ] Dependabot PRs reviewed weekly

### 10.10 Legal and compliance baseline

- [ ] ToS + Privacy Policy published and linked from customer portal (Phase 2 Feature 2.1.3)
- [ ] CAN-SPAM: unsubscribe link on every marketing email; physical address in footer
- [ ] SMS: A2P 10DLC registration complete before first SMS (§5 of `11_security_baseline.md`)
- [ ] SPF / DKIM / DMARC DNS records active on SendGrid domain
- [ ] Data export endpoint and soft-delete with 30-day grace (Phase 2 Features 2.6.1–2.6.3)
- [ ] Incident notification plan documented (§11)

Walk through this entire list once when cutting the first real production release. Re-walk every quarter.

---

## 11. Incident Response Playbook

Incidents are rare but when they happen, you're the only person on call. Follow this sequence.

### 11.1 When an alert fires

1. **Acknowledge in Slack** within 5 minutes (reduces stress; makes the timeline trackable)
2. **Triage severity:**
   - P0 — customer-facing outage, data loss, security incident → work immediately
   - P1 — degraded service, single feature broken → work within 1 hour
   - P2 — non-urgent, warning → review in morning triage
3. **Open `project_notes/incidents.md`** and create a new entry with timestamp, alert text
4. **Check the usual suspects** (§11.2)
5. **If it's going to take > 30 min:** post a status to customers (§11.5)
6. **After resolution:** write a 5-sentence postmortem (what, why, how fixed, how prevented)

### 11.2 Common incident checks

**API returning 5xx:**

```bash
# Fly logs (last hour, errors only)
flyctl logs --app temple-api-prod --no-tail | grep -iE "(error|critical|traceback)" | tail -50

# Recent releases (which one is running?)
flyctl releases --app temple-api-prod --limit 5

# Machine states
flyctl status --app temple-api-prod

# Neon status
neonctl branches list --project-id $NEON_PROJECT_ID
```

If a recent deployment correlates: roll back (§5.1).

**Uptime check failing but logs look normal:**

```bash
# Is Cloudflare getting through?
curl -v -H "Host: api.templehe.com" https://api.templehe.com/api/v1/health

# Is Fly responding bypassing Cloudflare?
flyctl ssh console --app temple-api-prod --command "curl -fsSL http://localhost:8000/api/v1/health"

# Cloudflare dashboard → Analytics & Logs → look for WAF blocks
```

**Database issue:**

```bash
# Connection status — try a query
flyctl ssh console --app temple-api-prod --command "psql \$DATABASE_URL -c 'SELECT now()'"

# Check long-running queries
flyctl ssh console --app temple-api-prod --command "psql \$DATABASE_URL -c \"
SELECT pid, age(clock_timestamp(), query_start), state, query
FROM pg_stat_activity
WHERE state != 'idle' AND query_start < now() - interval '30 seconds'
ORDER BY query_start\""

# Neon dashboard → branch → Metrics for CPU/memory/connections
```

**Customer reports "my data is gone":**

1. Don't touch anything
2. Pull the audit log for that record:
   ```bash
   flyctl ssh console --app temple-api-prod --command "psql \$DATABASE_URL -c \"
   SELECT * FROM audit_logs WHERE target_id='<uuid>' ORDER BY created_at DESC\""
   ```
3. If soft-deleted, restore via admin panel (Phase 4 Feature 4.2)
4. If hard-deleted, restore from Neon PITR (§6.3) or the R2 daily dump

### 11.3 Security incident (suspected breach)

Severity P0 regardless of scope.

1. **Rotate the obviously compromised credentials first:**
   ```bash
   # JWT signing keys — invalidates all active sessions immediately
   flyctl secrets set \
     JWT_SIGNING_KEY="$(openssl rand -base64 64)" \
     JWT_REFRESH_KEY="$(openssl rand -base64 64)" \
     --app temple-api-prod
   ```
2. **If database credentials may be compromised:**
   ```bash
   neonctl branches roles reset-password --project-id $NEON_PROJECT_ID \
     --branch-id <prod-id> --role-name <role>
   flyctl secrets set DATABASE_URL="<new-url>" --app temple-api-prod
   ```
3. **Enable maintenance mode** (§5.3) if you need time to investigate
4. **Export audit logs** for the affected time window to R2 for forensics
5. **Enable Cloudflare "Under Attack" mode** if the breach looks active
6. **Notify customers within 72 hours** if PII was accessed (many US states require this; see `11_security_baseline.md` §6)
7. **Write a full postmortem** in `project_notes/incidents.md` documenting root cause and preventive changes

### 11.4 Certificate / domain / DNS

Fly manages Let's Encrypt auto-renewal on custom hostnames. If something fails:

```bash
flyctl certs list --app temple-api-prod
flyctl certs show api.templehe.com --app temple-api-prod

# If stuck: remove + re-add
flyctl certs remove api.templehe.com --app temple-api-prod --yes
flyctl certs add api.templehe.com --app temple-api-prod
```

Cloudflare edge cert is separate — managed via Cloudflare dashboard, auto-renews.

### 11.5 Customer-facing status page

Simplest option: a static page on **Cloudflare Pages** (free), separate zone from the platform, that you manually update during incidents. Don't host it on the same infrastructure you're trying to report about.

Template text:

> **[2026-04-18 14:30 ET] Investigating** — We're seeing elevated error rates on customer portal submissions. Our team is investigating. The appraiser iOS app is unaffected.
>
> **[2026-04-18 14:55 ET] Identified** — Root cause identified; deploying a fix.
>
> **[2026-04-18 15:20 ET] Resolved** — Fix deployed. All services operational. A detailed postmortem will follow.

---

## 12. New Employee Onboarding (when you eventually hire)

When someone joins who needs access:

```bash
# 1. Invite to Fly org (least-privilege role: Member, not Admin)
flyctl orgs invite temple-he newhire@company.com

# 2. Invite to Neon project
neonctl projects permissions grant --project-id $NEON_PROJECT_ID \
  --email newhire@company.com --role developer

# 3. Invite to GitHub repo (Write, not Admin)
gh api --method PUT "/repos/YOUR_ORG/temple-he-platform/collaborators/NEWHIRE_USERNAME" -f permission=push

# 4. Invite to Sentry (Member role)
# 5. Invite to Cloudflare (Analytics role; Admin only for specific need)
# 6. Invite to BetterStack (Read role)
# 7. Invite to the #alerts Slack channel
# 8. Walk them through this runbook and 11_security_baseline.md
```

Remove access in reverse order at offboarding. See Phase 4 Feature 4.2.2 for the staff departure handoff in the application itself.

---

## 13. Day-1 Checklist

A launch-day checklist so nothing slips through:

- [ ] Fly org created with 2FA required; all six apps exist (`temple-{api,web}-{dev,staging,prod}`)
- [ ] Neon project + three branches (`dev`, `staging`, `prod`) + Pro plan active
- [ ] Cloudflare account + zone set up; DNS proxied for prod hostnames
- [ ] R2 buckets created with object versioning
- [ ] GitHub repo created with branch protection on `main` and `develop`
- [ ] GitHub Environments (`dev`, `staging`, `prod`) with prod approval gate
- [ ] Per-app Fly deploy tokens created, stored in GitHub secrets, local copies destroyed
- [ ] `fly secrets` populated for all three environments
- [ ] Dependabot and secret scanning enabled
- [ ] Security CI workflow (`.github/workflows/security.yml`) committed and passing
- [ ] Deploy CI workflow (`.github/workflows/deploy.yml`) committed; hello-world deploys green to `temple-api-dev`
- [ ] Sentry org + projects created with DSNs added to `fly secrets`
- [ ] BetterStack source token added; log shipper active on prod API + prod web
- [ ] UptimeRobot monitors created for prod hostnames with SMS alerting
- [ ] Slack `#alerts` channel with webhook tested (simulate a 5xx)
- [ ] SendGrid account + domain authenticated (SPF/DKIM/DMARC) — see `11_security_baseline.md` §5
- [ ] Twilio account + A2P 10DLC registration started — see `11_security_baseline.md` §5
- [ ] First quarterly backup restore drill scheduled on calendar
- [ ] `project_notes/` directory populated: `decisions.md` (already done, ADR-001), `known-issues.md`, `progress.md`, `incidents.md`, `drills.md`
- [ ] `§10 Fly.io Production Hardening Checklist` walked top-to-bottom; every box green

---

## 14. AI-DLC workflow reference

Because this plan is built to be executed with Claude Code, a short note on how AI fits into the operations above:

- **Specs are the contract.** These plan files are read by Claude at the start of every coding session. If behavior is missing from the spec, it won't exist in code. Keep the specs authoritative.
- **ADRs capture the "why".** `project_notes/decisions.md` is the second file Claude reads each session. New non-obvious architectural decisions go in as ADRs; they outlive any single session.
- **Claude does PR review first, you approve.** `/review` and `/security-review` skills run before you merge. The human signal is still required — don't auto-merge AI-written code.
- **Claude maintains `project_notes/`.** Decisions, known issues, incidents, and drills captured at end of each session persist across sessions. This is the knowledge store a team of humans would have in their heads.
- **Ephemeral Neon branches per PR** (§3.4) let multiple Claude-driven PRs run their integration tests in parallel without stepping on each other's data. This is a meaningful AI-DLC accelerator.
- **Incidents get documented.** Every entry in `project_notes/incidents.md` becomes context for future sessions. Over time, Claude will recognize patterns ("this error looks like the April 18 incident") faster than a new engineer could.
- **Claude-in-Chrome for staging smoke tests.** You can automate manual staging smoke tests via browser MCP rather than hand-clicking.

The short version: AI-DLC lets a one-person ops team run a platform that would traditionally need three. The scaffolding in this runbook (scanning, monitoring, automated rollbacks, hardening checklist) is what makes that safe.

---

## 15. When to migrate to GCP

Per ADR-001, the trigger to lift to GCP is **any one of**:

- Sustained traffic > 500 RPS or > 10K MAU on the public listing page
- Need for SOC 2 / enterprise compliance (an enterprise customer asks)
- A second sustained Fly or Neon outage of > 4 hours within 90 days
- Total monthly Fly + Neon cost exceeds $150 (cost-parity inflection point)

When triggered, follow `13_hosting_migration_plan.md` end-to-end. The target architecture is documented in `12_gcp_production_target.md`.

---

## 16. Code Review Remediations (Phase 1 Hardening)

Post-Sprint-5 code review produced `project_notes/code_review_phase1.md` (also published to Outline at https://kb.saltrun.net/doc/baXdhfglbk). 14 workstreams shipped on branch `phase1-hardening`; the resolution table and per-finding `Resolved` / `Deferred` markers live in that document. ADR-012 in `project_notes/decisions.md` codifies the cross-cutting design decisions.

Operational items worth surfacing here:

- **`temple-sweeper` Fly Machine.** New scheduled machine runs `scripts/sweep_retention.py` hourly. Must be provisioned once via `fly machine run . --app temple-sweeper --schedule hourly` — not part of the CI-driven deploy. Monitor via `fly logs -a temple-sweeper`. See §7 for retention-sweep alerting.
- **Health check R2 semantics changed.** `/api/v1/health` now returns 503 in production when R2 is `unconfigured` — this is the rotated-key detection signal. Confirm staging and prod both pass the probe after any R2 credential rotation.
- **`audit_logs` is now partitioned monthly.** Any ops procedure that directly touches the table (pg_dump, backup, reindex) must account for monthly child tables. Default `pg_dump` captures the parent + all children; targeted dumps by partition name (e.g. `audit_logs_2026_07`) are available.
- **Trivy CI lane tightened.** `ignore-unfixed: false` means unfixed CRITICAL/HIGH CVEs fail the scan. If a failure is justified (upstream no-fix, acceptable risk), add a per-CVE entry to `.trivyignore` with written justification — don't re-flip the policy.

**Items deferred from the review** (documented, not implemented in Phase 1 Hardening):

| Item | Deferred to | Document |
|---|---|---|
| TOTP `MultiFernet` rotation | Phase 5 Sprint 0 | `dev_plan/05_phase5_ios_app.md` + `11_security_baseline.md §14` |
| Prometheus `/metrics` | Later phase | `11_security_baseline.md §14` |
| boto3 → aioboto3 | Not planned | `11_security_baseline.md §14` |
| PII retention (row-level on `audit_logs`, `user_sessions`, `known_devices`) | Phase 2 data export/deletion | `11_security_baseline.md §7` |
