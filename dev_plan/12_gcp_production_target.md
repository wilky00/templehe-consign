# GCP Production Target Architecture

> **Status:** This is the **target state** the platform migrates to once the Fly.io POC has stabilized and the migration triggers in `project_notes/decisions.md` ADR-001 fire. While the platform runs on Fly.io (per `10_operations_runbook.md`), treat this file as the architectural reference and the destination of the migration playbook in `13_hosting_migration_plan.md`.
>
> **Audience:** Jim, when the time comes to lift to GCP. Same operating model — solo supporter, 8–24 hour SLA — at higher scale and with enterprise-grade infrastructure.
>
> **Read this file before running any `gcloud`, `terraform`, or `git tag` command against a GCP environment.**

---

## 1. Environment Architecture

### 1.1 Three GCP projects + local Docker

| Environment | Purpose | Where it runs | Who can deploy |
|---|---|---|---|
| **Local** | Day-to-day coding | Docker Compose on your laptop | You |
| **`temple-dev`** | Integration testing for GCP-specific features (Pub/Sub, Secret Manager, GCS signed URLs) | GCP project | Auto-deploy on push to `develop` branch |
| **`temple-staging`** | Pre-prod mirror; E2E tests run here; where you manually verify a release candidate | GCP project | Auto-deploy on merge to `main` |
| **`temple-prod`** | Customer-facing production | GCP project | Tag `v*` + manual GitHub Actions approval |

**Why three projects:** blast-radius isolation. An accidental `terraform destroy` against the wrong workspace can only wipe one environment, never prod. Separate IAM, separate billing, separate quotas.

**Why also local Docker:** most of your development never needs the cloud. Running Postgres locally via Compose is free, ~10x faster to iterate on, and keeps your GCP dev costs low.

### 1.2 Realistic monthly cost (USD)

| Project | Expected cost | Notes |
|---|---|---|
| `temple-dev` | $30–50 | Tiny Cloud SQL, smallest Redis, Cloud Run scales to zero. Schedule SQL to stop nights/weekends (§8.3) to halve this. |
| `temple-staging` | $50–80 | One size up from dev. Full E2E test environment. |
| `temple-prod` | $120–180 | `db-custom-1-3840` Cloud SQL with HA, 1GB Memorystore HA. |
| **Total** | **$200–310/mo** | Budget $300/mo with 20% buffer. |

Set GCP budget alerts at 50%, 80%, and 100% of $300 (§8).

---

## 2. Initial One-Time Setup

Run these once, in order. Every command is copy-paste-ready. Replace `YOUR_BILLING_ACCOUNT_ID` and email placeholders.

### 2.1 Install prerequisites on your laptop

```bash
# macOS (per your CLAUDE.md macos.md standards)
brew install --cask google-cloud-sdk docker
brew install terraform gh git pre-commit
gcloud components install beta alpha

# Verify
gcloud --version
terraform --version
gh --version
docker --version
```

### 2.2 Authenticate

```bash
gcloud auth login
gcloud auth application-default login
gh auth login    # authenticates GitHub CLI
```

### 2.3 Create the three GCP projects

```bash
# Find your billing account
gcloud billing accounts list

export BILLING_ID="YOUR_BILLING_ACCOUNT_ID"

for env in dev staging prod; do
  PROJECT_ID="temple-${env}"
  gcloud projects create "$PROJECT_ID" --name="TempleHE ${env}"
  gcloud billing projects link "$PROJECT_ID" --billing-account="$BILLING_ID"
  gcloud config set project "$PROJECT_ID"
  gcloud services enable \
    run.googleapis.com \
    sqladmin.googleapis.com \
    redis.googleapis.com \
    secretmanager.googleapis.com \
    pubsub.googleapis.com \
    storage.googleapis.com \
    artifactregistry.googleapis.com \
    cloudbuild.googleapis.com \
    monitoring.googleapis.com \
    logging.googleapis.com \
    clouderrorreporting.googleapis.com \
    iap.googleapis.com \
    cloudscheduler.googleapis.com
done
```

### 2.4 Bootstrap Terraform state buckets

Terraform stores its state (which resources exist where) in a GCS bucket, one per environment.

```bash
for env in dev staging prod; do
  PROJECT_ID="temple-${env}"
  BUCKET="tfstate-${PROJECT_ID}"
  gcloud storage buckets create "gs://${BUCKET}" \
    --project="$PROJECT_ID" \
    --location=us-central1 \
    --uniform-bucket-level-access
  gcloud storage buckets update "gs://${BUCKET}" --versioning
done
```

### 2.5 GitHub Actions service account for deployments

Each GCP project needs a service account GitHub can use to deploy.

```bash
for env in dev staging prod; do
  PROJECT_ID="temple-${env}"
  SA_NAME="github-deployer"
  gcloud iam service-accounts create "$SA_NAME" \
    --project="$PROJECT_ID" \
    --display-name="GitHub Actions deployer"

  SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

  for role in roles/run.admin roles/storage.admin roles/iam.serviceAccountUser \
              roles/secretmanager.admin roles/cloudsql.admin roles/pubsub.admin \
              roles/artifactregistry.admin; do
    gcloud projects add-iam-policy-binding "$PROJECT_ID" \
      --member="serviceAccount:${SA_EMAIL}" --role="$role"
  done
done
```

### 2.6 Workload Identity Federation (no static keys)

Set up Workload Identity Federation so GitHub Actions can authenticate to GCP without a JSON key (no static credentials = one fewer rotation chore).

```bash
# For each project, create a workload identity pool bound to your GitHub repo
# so GitHub can mint short-lived GCP tokens. Full script:
./scripts/setup-github-oidc.sh temple-dev    YOUR_GITHUB_USER/temple-he-platform
./scripts/setup-github-oidc.sh temple-staging YOUR_GITHUB_USER/temple-he-platform
./scripts/setup-github-oidc.sh temple-prod   YOUR_GITHUB_USER/temple-he-platform
```

The script does the IAM plumbing. Commit the script; it's idempotent.

### 2.7 Configure GitHub environments with approval gates

In the GitHub repo, go to **Settings → Environments** and create three environments: `dev`, `staging`, `prod`.

- `dev`: no protection rules
- `staging`: no protection rules
- `prod`: **Required reviewers: Jim**. Optionally add a wait timer (5 minutes).

This is what gives you the one-click approval step before a prod deploy runs.

---

## 3. Local Development Loop

Same as POC — see `10_operations_runbook.md` §3. The local Docker Compose stack is identical regardless of cloud target. Only the deploy commands change.

---

## 4. Deployment Flow

### 4.1 The pipeline at a glance

```
feature-branch ──PR──▶ develop ──▶ [CI] ──▶ auto-deploy to temple-dev
                                                    │
                                                    ▼
                                              E2E tests on dev
                                                    │
develop ──PR──▶ main ──▶ [CI] ──▶ auto-deploy to temple-staging
                                                    │
                                                    ▼
                                          E2E + accessibility tests
                                                    │
main ──git tag v*──▶ [CI + manual approve] ──▶ deploy to temple-prod
                                                    │
                                                    ▼
                                          Smoke tests + health check
                                                    │
                                      ┌─ pass ──▶ traffic shifted to new revision
                                      └─ fail ──▶ auto-rollback (§5)
```

### 4.2 Cutting a production release

```bash
# Make sure staging is green
gh run list --branch main --limit 1
gh run view <run-id>    # confirm all green

# Tag a version (semantic versioning)
git checkout main && git pull
git tag v1.0.0 -m "Release 1.0.0 — first GCP production release"
git push origin v1.0.0
```

The tag push triggers the prod workflow. Go to **GitHub → Actions → Deploy to Prod** and click **Review deployments → prod → Approve**. The workflow:

1. Builds production Docker image, pushes to Artifact Registry
2. Runs DB migration with `alembic upgrade head` (prod DB)
3. Deploys new Cloud Run revision with **0% traffic** (canary)
4. Runs smoke tests against the new revision via its dedicated URL
5. If smoke tests pass: shifts traffic 100% to new revision
6. If smoke tests fail: auto-rollback (keeps old revision serving)

### 4.3 Database migrations

**Always forward-only. Always reversible.** Every Alembic migration has a working `downgrade()` — tested locally before commit.

The prod workflow runs migrations *before* the app deploy, so a broken migration blocks the deploy. If a migration fails mid-run:

```bash
# Check what happened
gcloud logging read 'resource.type="cloud_run_revision" severity>=ERROR' \
  --project=temple-prod --limit=50 --format=json

# Roll the migration back manually
gcloud run jobs execute db-migrate-rollback --project=temple-prod --region=us-central1 --wait
```

Destructive migrations (DROP COLUMN, TYPE changes) are split into two releases:

1. Release N: deploy code that reads + writes both old and new columns
2. Release N+1: drop the old column after verifying no traffic references it

Never ship a destructive migration and the code that depends on it in the same release.

---

## 5. Rollback Procedures

### 5.1 Fast rollback (code only) — 30 seconds

Cloud Run keeps the last 100 revisions. Roll traffic back to the previous revision:

```bash
# List recent revisions
gcloud run revisions list \
  --service=temple-api --region=us-central1 --project=temple-prod \
  --limit=5 --format='table(metadata.name,metadata.creationTimestamp,status.conditions[0].status)'

# Shift 100% traffic to the prior revision
gcloud run services update-traffic temple-api \
  --region=us-central1 --project=temple-prod \
  --to-revisions=temple-api-00042-abc=100
```

Same pattern for the frontend (Cloud Storage versioned bucket):

```bash
# List versions of the index.html
gcloud storage ls -a gs://temple-prod-web/index.html

# Restore prior version
gcloud storage cp "gs://temple-prod-web/index.html#<generation-id>" \
                  "gs://temple-prod-web/index.html"
```

### 5.2 Rollback including a DB migration — 5–15 minutes

If the bad release shipped a migration:

1. Roll code traffic back first (§5.1)
2. Run the downgrade:
   ```bash
   gcloud run jobs execute db-migrate \
     --project=temple-prod --region=us-central1 \
     --args="downgrade,-1" --wait
   ```
3. Confirm schema matches the code now serving by checking migration version:
   ```bash
   gcloud sql connect temple-prod-pg --project=temple-prod --user=postgres
   # in psql:
   SELECT version_num FROM alembic_version;
   ```

### 5.3 "Prod is completely broken" — the panic path

If the API is returning 5xx for all requests and rollback doesn't help:

```bash
# Put the API into maintenance mode
gcloud run services update temple-api \
  --region=us-central1 --project=temple-prod \
  --set-env-vars=MAINTENANCE_MODE=true
```

Maintenance mode is implemented by a middleware (Phase 1 Feature 1.1.3) that returns 503 + a friendly HTML page to all requests except `/api/v1/health`. Buys you time to investigate without customers seeing 500 errors.

Once fixed:

```bash
gcloud run services update temple-api \
  --region=us-central1 --project=temple-prod \
  --remove-env-vars=MAINTENANCE_MODE
```

---

## 6. Backup & Disaster Recovery

### 6.1 Recovery targets (committed)

| Metric | Target | Notes |
|---|---|---|
| **RTO** (time to restore service) | 4 hours | Realistic for solo support. |
| **RPO** (max acceptable data loss) | 1 hour | Cloud SQL PITR with binlog retention. |
| **Backup retention** | 30 days automated + 1 year of monthly snapshots | |
| **Restore drill frequency** | Every quarter | On calendar, not optional. |

### 6.2 What's backed up and how

**Cloud SQL (Postgres):**
- **Automated daily backups, 30-day retention** (Terraform sets this).
- **Point-in-time recovery enabled** — binlog retention 7 days. You can restore to any second in the last week.
- **Monthly manual snapshot exported** to a separate GCS bucket, retained 1 year, for ransomware/malicious-delete protection.

Set via Terraform:

```hcl
resource "google_sql_database_instance" "main" {
  settings {
    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
      start_time                     = "03:00"
      backup_retention_settings {
        retained_backups = 30
        retention_unit   = "COUNT"
      }
      transaction_log_retention_days = 7
    }
  }
}
```

**Cloud Storage (photos + PDFs):**
- **Object versioning enabled** on `temple-prod-photos` and `temple-prod-reports` buckets. Deletes and overwrites are recoverable for 90 days.
- **Lifecycle policy:** photos > 1 year move to Nearline storage (~50% cheaper), > 3 years move to Coldline.
- **Cross-region replication** not worth the cost at SMB scale; single-region us-central1 is acceptable given the RTO.

**Redis:** not backed up. It's a cache and lock store — everything in it is either ephemeral or recoverable from Postgres/Pub/Sub.

**Secrets:** Secret Manager has 6 versions retained automatically. Export all secrets to an encrypted offline backup quarterly (§6.5).

### 6.3 Restoring from backup — step by step

**Scenario: PITR restore to 2 hours ago (e.g., bad DELETE swept through customers table).**

```bash
# 1. Confirm the timestamp you want to restore to (UTC)
export RESTORE_TIME="2026-04-18T14:00:00Z"

# 2. Clone the prod DB to a new instance at that point in time
gcloud sql instances clone temple-prod-pg temple-prod-pg-restored-$(date +%Y%m%d) \
  --project=temple-prod \
  --point-in-time="$RESTORE_TIME"

# 3. Inspect the clone to confirm the data looks right
gcloud sql connect temple-prod-pg-restored-20260418 --project=temple-prod --user=postgres

# 4. Once confirmed, swap: point the API at the restored DB, or dump+restore
#    specific tables back into the live instance. Dump+restore is less disruptive:
pg_dump -h <restored-instance-ip> -U postgres -d temple \
        -t customers -t equipment_records \
        --data-only --on-conflict=do-nothing \
        > /tmp/recovered.sql
psql -h <live-instance-ip> -U postgres -d temple < /tmp/recovered.sql

# 5. Delete the restored clone once done
gcloud sql instances delete temple-prod-pg-restored-20260418 --project=temple-prod
```

**Scenario: full instance failure.**

```bash
gcloud sql backups list --instance=temple-prod-pg --project=temple-prod
gcloud sql backups restore <BACKUP_ID> --restore-instance=temple-prod-pg --project=temple-prod
```

### 6.4 Quarterly restore drill (mandatory)

Set a recurring calendar event: **first Monday of each quarter, 2 hours blocked.**

```bash
# 1. Pick a random timestamp from last week
# 2. Run the PITR clone procedure above against temple-staging (never prod)
# 3. Spot-check: row counts, a known equipment record, a known customer
# 4. Write a 3-sentence summary in project_notes/drills.md with date + result
# 5. Delete the cloned instance
```

If the drill ever fails, the issue is logged as a P1 and fixed before the next deploy.

### 6.5 Offline encrypted backup of secrets

Quarterly, export Secret Manager values to an encrypted archive you keep somewhere not on GCP (external drive, 1Password vault, whatever):

```bash
mkdir -p /tmp/secrets-backup
cd /tmp/secrets-backup

gcloud secrets list --project=temple-prod --format='value(name)' | while read secret; do
  gcloud secrets versions access latest --secret="$secret" --project=temple-prod \
    > "${secret}.txt"
done

# Encrypt the whole thing with a password only you know
tar czf - . | gpg -c --output "/tmp/temple-secrets-$(date +%Y%m%d).tar.gz.gpg"
rm -rf /tmp/secrets-backup
```

Store the encrypted archive outside GCP. The passphrase lives in your password manager, not in any git repo.

---

## 7. Monitoring & Alerts

### 7.1 The monitoring stack

| Tool | What it does | Cost |
|---|---|---|
| **Cloud Monitoring** (built-in GCP) | Infrastructure metrics, uptime checks, alert policies | Free tier covers SMB easily |
| **Cloud Logging** (built-in GCP) | All API logs, structured JSON, searchable | Free up to 50GB/mo per project |
| **Sentry** (free tier or paid) | Application errors with stack traces, deploy tracking, release correlation | Free: 5K errors/mo. Upgrade to Team ($26/mo) when you outgrow it |
| **Cloud Error Reporting** (built-in GCP) | Backup error aggregation | Free |
| **Slack** (your existing) | Where all alerts land | Free |

### 7.2 What to instrument (carries over from POC)

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

Cloud Logging auto-indexes these fields for filtering. All `ERROR` logs are automatically forwarded to Sentry via the Sentry Python SDK.

### 7.3 Alert policies (Terraform-provisioned)

| Alert | Condition | Channel | Priority |
|---|---|---|---|
| API 5xx rate | > 1% of requests over 5 min | Slack #alerts + email | P1 |
| API latency | P95 > 2s for 10 min | Slack #alerts | P2 |
| Cloud SQL CPU | > 80% for 15 min | Slack #alerts | P2 |
| Cloud SQL disk | > 80% full | Slack #alerts + email | P1 |
| Redis memory | > 80% for 15 min | Slack #alerts | P2 |
| Pub/Sub DLQ | any message present | Slack #alerts + email | P1 |
| Uptime check (`/api/v1/health`) | 2 consecutive failures | Slack #alerts + email + SMS | P0 |
| GCP budget | > 80% of $300/mo | Email | P2 |
| Sentry new issue | severity=error, seen in prod | Slack #alerts | P2 |
| Background job failure | Any Cloud Run Job with exit code ≠ 0 | Slack #alerts | P1 |

P0 alerts go to SMS so a 2am outage actually wakes you up. Everything else is Slack + email so you see it in your morning triage.

### 7.4 Uptime checks

```bash
# Runs every 60s from 6 global locations, alerts if 2+ fail
gcloud monitoring uptime-check-configs create temple-api-prod \
  --project=temple-prod \
  --display-name="Temple API production" \
  --resource-type=uptime-url \
  --host=api.templehe.com \
  --path=/api/v1/health \
  --period=60s
```

### 7.5 Sentry setup

Same Sentry projects as POC — at GCP cutover, only `SENTRY_ENVIRONMENT` and `SENTRY_RELEASE` change. The DSNs are reused.

### 7.6 Daily triage ritual (5–10 minutes)

Same as POC ops loop — see `10_operations_runbook.md` §6.6.

---

## 8. Cost Management

### 8.1 Set budget alerts

```bash
for env in dev staging prod; do
  case $env in
    dev)     AMOUNT=75  ;;
    staging) AMOUNT=100 ;;
    prod)    AMOUNT=200 ;;
  esac

  gcloud billing budgets create \
    --billing-account=$BILLING_ID \
    --display-name="temple-${env} monthly" \
    --budget-amount="${AMOUNT}USD" \
    --threshold-rule=percent=0.5 \
    --threshold-rule=percent=0.8 \
    --threshold-rule=percent=1.0 \
    --filter-projects="projects/temple-${env}"
done
```

### 8.2 Cost drivers to watch

1. **Google Maps Distance Matrix calls** — Phase 3 caches these in Redis for 6 hours. Monitor Maps API usage in Cloud Console; cap quota if it spikes.
2. **Cloud SQL storage growth** — photos live in GCS, but audit_logs grow forever. Phase 4 §4.4 should include an `audit_log` archival job (move rows > 2 years old to a separate long-term table).
3. **Cloud Storage (photos + PDFs)** — Terraform lifecycle rule moves to Nearline after 365d and Coldline after 3y. No manual action needed.
4. **Cloud Run cold starts** — if latency becomes a UX problem, set `min-instances=1` on prod API (~$40/mo adder).

### 8.3 Scheduled shutdown of dev environment

Dev doesn't need to run nights and weekends. Create a Cloud Scheduler job that stops the Cloud SQL instance evenings and starts it weekday mornings:

```bash
# Stop dev SQL at 8pm weekdays
gcloud scheduler jobs create http temple-dev-sql-stop \
  --project=temple-dev \
  --schedule="0 20 * * 1-5" --time-zone="America/New_York" \
  --http-method=POST \
  --uri="https://sqladmin.googleapis.com/v1/projects/temple-dev/instances/temple-dev-pg/stop" \
  --oauth-service-account-email="scheduler@temple-dev.iam.gserviceaccount.com"

# Start dev SQL at 8am weekdays
gcloud scheduler jobs create http temple-dev-sql-start \
  --project=temple-dev \
  --schedule="0 8 * * 1-5" --time-zone="America/New_York" \
  --http-method=POST \
  --uri="https://sqladmin.googleapis.com/v1/projects/temple-dev/instances/temple-dev-pg/start" \
  --oauth-service-account-email="scheduler@temple-dev.iam.gserviceaccount.com"
```

Saves roughly 50% on the dev SQL bill.

---

## 9. GitHub Security Scanning

Identical to POC — see `10_operations_runbook.md` §8. The scanning stack (Dependabot, secret scanning, gitleaks, Trivy, pip-audit, npm audit, OSV-Scanner) is platform-agnostic and carries over unchanged.

---

## 10. Incident Response Playbook

Same playbook structure as POC; only the diagnostic commands differ. See `10_operations_runbook.md` §9 for the structure (acknowledge → triage → check → mitigate → postmortem). The GCP-specific commands:

**API returning 5xx:**

```bash
# Latest error logs
gcloud logging read 'resource.type="cloud_run_revision" severity>=ERROR' \
  --project=temple-prod --limit=20 --freshness=30m --format=json

# Recent deployments
gcloud run revisions list --service=temple-api --region=us-central1 \
  --project=temple-prod --limit=3

# Cloud SQL status
gcloud sql instances describe temple-prod-pg --project=temple-prod --format='value(state)'

# Redis status
gcloud redis instances describe temple-prod-redis --region=us-central1 --project=temple-prod --format='value(state)'
```

If a recent deployment correlates: roll back (§5.1).

**Uptime check failing but logs look normal:**

```bash
gcloud run services describe temple-api --region=us-central1 --project=temple-prod
gcloud run services logs read temple-api --region=us-central1 --project=temple-prod --limit=50
```

Often a cold-start issue after a long idle period. If it recurs, set `min-instances=1` on prod.

**Database issue:**

```bash
gcloud sql instances describe temple-prod-pg --project=temple-prod \
  --format='value(settings.databaseFlags,state,serverCaCert.expirationTime)'

gcloud sql connect temple-prod-pg --project=temple-prod --user=postgres
# then:
SELECT pid, age(clock_timestamp(), query_start), state, query
FROM pg_stat_activity
WHERE state != 'idle' AND query_start < now() - interval '30 seconds'
ORDER BY query_start;
```

**Security incident — rotate compromised credentials:**

```bash
# Example: rotate JWT signing key
gcloud secrets versions add jwt-signing-key --data-file=<(openssl rand -base64 64) --project=temple-prod
gcloud run services update temple-api --region=us-central1 --project=temple-prod \
  --update-secrets=JWT_SIGNING_KEY=jwt-signing-key:latest

# Invalidate all active sessions (Memorystore Redis)
gcloud redis instances describe temple-prod-redis --region=us-central1 --project=temple-prod --format='value(host)'
# redis-cli> FLUSHDB
```

### 10.4 Certificate / domain / DNS

DNS and certs auto-renew via Google-managed SSL on Cloud Run. If something fails:

```bash
gcloud compute ssl-certificates list --project=temple-prod
gcloud run domain-mappings list --project=temple-prod --region=us-central1
```

Re-issuing usually means deleting and recreating the mapping; Google handles LetsEncrypt automatically.

---

## 11. New Employee Onboarding (when you eventually hire)

```bash
# 1. Add their Google account to the GCP projects at minimum-needed role
for env in dev staging prod; do
  gcloud projects add-iam-policy-binding "temple-${env}" \
    --member="user:newhire@company.com" \
    --role="roles/viewer"    # start read-only
done

# 2. Invite to GitHub repo (Write, not Admin)
gh api --method PUT "/repos/YOUR_ORG/temple-he-platform/collaborators/NEWHIRE_USERNAME" -f permission=push

# 3. Invite to Sentry (Member role)
# 4. Invite to the #alerts Slack channel
# 5. Walk them through this runbook
```

Remove access in reverse order at offboarding.

---

## 12. GCP Cutover Day-1 Checklist

When the migration trigger fires (per ADR-001) and you're ready to lift to GCP:

- [ ] All three GCP projects created, billing linked, budgets set
- [ ] Terraform workspaces applied for dev and staging (prod comes later)
- [ ] Workload Identity Federation configured for GitHub → GCP
- [ ] GitHub environments configured with prod approval gate
- [ ] Cloud Monitoring uptime checks created for `/api/v1/health`
- [ ] Sentry environments + DSNs swapped per env
- [ ] Slack webhook for `#alerts` re-tested against GCP alert policies
- [ ] Migration playbook in `13_hosting_migration_plan.md` followed end-to-end
- [ ] Old Fly.io apps put into maintenance mode, kept warm for 30 days as rollback safety net
- [ ] First quarterly backup restore drill scheduled on calendar

---
