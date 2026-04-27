# Hosting Migration Plan — Fly.io → GCP

> **Purpose:** Step-by-step playbook for lifting the platform from its POC home (Fly.io + Neon + R2 + Cloudflare) to its production target (GCP: Cloud Run + Cloud SQL + Memorystore + Cloud Storage). Follow this when one of the migration triggers in `project_notes/decisions.md` ADR-001 fires.
>
> **Audience:** Jim, executing this as a solo operator over a planned 1–2 week window.
> **Pre-conditions:** You've built and run the Fly.io platform for ≥ 3 months. All `project_notes/incidents.md` entries are closed. Quarterly restore drills have all passed. Neon PITR works. `10_operations_runbook.md` §10 hardening checklist is green.

---

## 1. Principles

1. **No surprises.** Rehearse the entire migration on staging before touching prod.
2. **Keep Fly warm as a rollback.** Do not decommission Fly apps until 30 days after GCP prod is serving real traffic.
3. **One concern at a time.** Don't also refactor the application. Don't upgrade the DB schema during cutover. Don't add features. Only the platform changes.
4. **Freeze-then-move.** Lock prod data before moving it; brief maintenance window is acceptable for a planned migration.
5. **Every step has a rollback.** Even tiny ones. Nothing is irreversible until the 30-day keep-warm period ends.

---

## 2. Pre-Migration Readiness (2–3 weeks before cutover)

### 2.1 Confirm the migration trigger

In `project_notes/decisions.md`, either an ADR-002 or an addendum to ADR-001 records **why** now. Examples:
- "Enterprise customer signed on 2026-11-01 requiring SOC 2; GCP gives us a realistic SOC 2 path"
- "Fly postgres had two P0 outages in Aug and Sep 2026; Neon PITR got us through but the reliability math is shifting"
- "Monthly Fly + Neon bill exceeded $150 for three consecutive months; GCP at this scale is cost-competitive"

### 2.2 Freeze scope

Nothing new ships during the 2–3 week migration window except bug fixes. Create a branch protection rule: `main` accepts only PRs labeled `migration` or `bugfix`.

### 2.3 Stand up the GCP target architecture

Walk through `12_gcp_production_target.md` §2 end-to-end on staging only:

- [ ] Create `temple-staging-gcp` (or reuse the naming from ADR-001)
- [ ] Enable all APIs listed in §2.3
- [ ] Terraform state bucket bootstrapped
- [ ] Workload Identity Federation configured for the GitHub repo
- [ ] Cloud SQL (Postgres 16) instance provisioned with PITR enabled
- [ ] Memorystore Redis (Basic, 1 GB) provisioned
- [ ] Cloud Storage buckets created (photos, reports), versioning on, lifecycle rules applied
- [ ] Artifact Registry repository created for the API Docker image
- [ ] Cloud Run services stubbed (no image deployed yet) with Cloud SQL + Redis sidecars attached
- [ ] Secret Manager populated with the same secret *names* as Fly (values will be updated at cutover)
- [ ] **Integration credentials migration plan rehearsed.** Phase 4 Sprint 7 ships `api/services/credentials_vault.py` with a clean interface (`encrypt(plaintext) -> bytes`, `decrypt(ciphertext) -> str`, MultiFernet rotation support). For GCP cutover, swap the backend to read from Secret Manager directly: each integration credential becomes a separate secret (`templehe-twilio`, `templehe-slack`, etc.) and `credentials_vault.get(name)` reads from `gcp_secret_manager.get_secret_version(name)` instead of the `integration_credentials` table. The vault's public API is unchanged so admin reveal/test/store flows don't move. ADR-020 §1 locks this contract.

### 2.4 Dual-write or dual-read? Decide.

For a small-scale SMB platform with a planned maintenance window, **freeze-and-move** is simpler than dual-writing. The migration window is scoped to a weekend at low traffic; during it, Fly serves a read-only maintenance page while the DB copies across.

If traffic has grown enough that a 2-hour maintenance window is unacceptable, switch to a logical-replication approach (use `pg_dump` + `pg_restore` for initial load, then set up `pglogical` or Postgres native logical replication from Neon → Cloud SQL for the delta; cutover happens at flip-the-DNS moment). That's more complex — if you need it, add a pre-flight ADR.

**Default assumption for this plan: freeze-and-move, 2-hour window.**

### 2.5 Rehearsal on staging (mandatory)

Run the full cutover procedure (§4) end-to-end on staging. Do not proceed to prod until staging migration works cleanly, the rollback also works cleanly, and you've timed every step.

Write a rehearsal log in `project_notes/migration-rehearsal.md` with your actual timings. That becomes the communication template for the real cutover announcement.

### 2.6 Backup everything

- [ ] Fresh `pg_dump` of the prod Neon branch → downloaded locally + stored in R2 + copied to a separate encrypted USB drive
- [ ] Fresh R2 bucket snapshot (use `rclone sync` to a separate local disk)
- [ ] `fly secrets list` output captured for every app
- [ ] Current Fly release versions noted — you may need to roll back to these if GCP cutover fails

### 2.7 Customer communication

Draft the email 7 days out; send 48 hours before:

> **Subject: Scheduled maintenance — Saturday 2026-Dec-06, 02:00–04:00 ET**
>
> We're upgrading our platform's hosting infrastructure to support continued growth. During the window above, the customer portal and mobile app will be unavailable for approximately 2 hours. All submitted data is safe and will be fully available once the maintenance completes. We'll send a follow-up confirmation as soon as services are restored.

Post the same notice on the status page (`10_operations_runbook.md` §11.5).

---

## 3. Migration Sequence (overview)

The cutover itself is a sequenced set of independent moves. Each column is prerequisite for the column to its right.

```
┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
│ T-7 days        │   │ T-0 cutover     │   │ T+1 stabilize   │   │ T+30 sunset     │
│ GCP target up   │──▶│ Freeze, move,   │──▶│ Monitor, tune,  │──▶│ Decommission    │
│ on staging,     │   │ flip DNS        │   │ fix drift       │   │ Fly + Neon      │
│ rehearsed       │   │ in 2-hour       │   │ for a month     │   │ once clean      │
│                 │   │ window          │   │                 │   │                 │
└─────────────────┘   └─────────────────┘   └─────────────────┘   └─────────────────┘
```

---

## 4. Cutover Day Runbook

A strict, ordered checklist. Do not skip ahead. Do not parallelize steps marked serial. Work from a single terminal session with `tmux` or similar so you can reconnect without losing context.

### 4.1 T-90 min — pre-flight

- [ ] All team members acknowledged in Slack
- [ ] Status page updated: "Scheduled maintenance begins in 90 minutes"
- [ ] Customer email sent (confirmation)
- [ ] GCP target on **prod** is provisioned and idle (not receiving traffic)
- [ ] GCP secrets populated (Secret Manager) with up-to-date values
- [ ] Cloud Run services deployed with the *current* prod image tag, set to 0% traffic
- [ ] DNS TTL for `api.templehe.com` and `app.templehe.com` dropped to **60 seconds** at Cloudflare at least 24 hours in advance (this lets traffic flip fast at cutover)
- [ ] Rollback plan printed on paper next to keyboard

### 4.2 T-0 — enter maintenance mode

```bash
# Enable maintenance mode on the Fly API
flyctl secrets set MAINTENANCE_MODE=true --app temple-api-prod

# Confirm — should return 503 with maintenance HTML
curl -s https://api.templehe.com/api/v1/somewhere | head -20
```

Status page: **"Maintenance window active. Estimated completion: [+2h]."**

### 4.3 T+5 — stop writes, take a final snapshot

```bash
# Fly app has returned 503 on everything except /health since T-0.
# Confirm no writes have landed in the last 5 minutes:
flyctl ssh console --app temple-api-prod --command "psql \$DATABASE_URL -c \"
SELECT max(created_at), max(updated_at)
FROM audit_logs\""

# Final Neon snapshot — creates a branch at exactly this moment
neonctl branches create --project-id $NEON_PROJECT_ID \
  --name "cutover-$(date -u +%Y%m%dT%H%M)" \
  --parent prod

# Record the snapshot branch ID in your migration log
```

### 4.4 T+15 — dump Neon prod, restore into Cloud SQL

```bash
# Export
pg_dump "$NEON_PROD_URL" \
  --no-owner --no-privileges --clean --if-exists \
  --exclude-schema=neon_admin \
  > /tmp/prod-cutover.sql

# Verify size looks plausible
ls -lh /tmp/prod-cutover.sql

# Restore into Cloud SQL
psql "$CLOUDSQL_PROD_URL" < /tmp/prod-cutover.sql

# Row-count check — should match on every critical table
for tbl in customers equipment_records appraisal_submissions audit_logs users; do
  NEON_COUNT=$(psql "$NEON_PROD_URL" -tAc "SELECT count(*) FROM $tbl")
  GCP_COUNT=$(psql "$CLOUDSQL_PROD_URL" -tAc "SELECT count(*) FROM $tbl")
  echo "$tbl: Neon=$NEON_COUNT  GCP=$GCP_COUNT"
  [[ "$NEON_COUNT" == "$GCP_COUNT" ]] || echo "MISMATCH"
done
```

**If counts don't match: STOP. Roll back (§5). Investigate before retrying.**

### 4.5 T+45 — sync object storage

```bash
# Use rclone to do a one-pass mirror from R2 → GCS (both are S3-compatible enough)
# Configure rclone remotes: "r2" (for Cloudflare R2) and "gcs" (for Google Cloud Storage)
rclone sync r2:temple-he-photos gcs:temple-prod-photos \
  --progress --transfers 16 --checkers 32 \
  --exclude ".version_history/**"

rclone sync r2:temple-he-reports gcs:temple-prod-reports \
  --progress --transfers 16 --checkers 32

# Verify counts
rclone size r2:temple-he-photos
rclone size gcs:temple-prod-photos
# Sizes should match within a tolerance (GCS may report slightly different due to storage class metadata)
```

Object versioning is not preserved by `rclone sync`. If ransomware recovery was relying on R2 versioning, note that the first GCS snapshot begins at cutover — older versions remain on R2 until sunset.

### 4.6 T+75 — deploy the production image to Cloud Run and smoke-test

```bash
# Build was done pre-flight; image is in Artifact Registry
# Deploy with 0% traffic (canary) pointed at the now-populated Cloud SQL

gcloud run deploy temple-api \
  --project=temple-prod \
  --region=us-central1 \
  --image=us-central1-docker.pkg.dev/temple-prod/temple/api:v1.0.0 \
  --no-traffic \
  --tag=cutover

# Hit the canary URL directly
CANARY_URL=$(gcloud run services describe temple-api --region=us-central1 --project=temple-prod \
  --format='value(status.traffic[?tag=cutover].url)')

curl -fsSL "$CANARY_URL/api/v1/health"
curl -fsSL "$CANARY_URL/api/v1/auth/login" -X POST ...   # synthetic login
```

Run the full E2E smoke suite (the one Phase 1 CI uses) against the canary URL. All green → proceed. Any red → STOP, roll back.

### 4.7 T+90 — flip DNS

```bash
# In Cloudflare:
#   DNS → api.templehe.com CNAME target
#     change from: temple-api-prod.fly.dev (POC)
#     change to:   temple-api.run.app  (or your Cloud Run custom domain target)
#   DNS → app.templehe.com CNAME target similarly
#   Proxy status stays ON (Cloudflare remains in front)

# Verify from multiple regions
for host in 1.1.1.1 8.8.8.8; do
  dig @$host api.templehe.com +short
done

# Shift Cloud Run traffic to 100% on the new revision
gcloud run services update-traffic temple-api \
  --project=temple-prod \
  --region=us-central1 \
  --to-latest
```

DNS TTL is 60 seconds, so worst-case rollover is 60 seconds. Cloudflare DNS propagation is effectively instant.

### 4.8 T+95 — exit maintenance mode

```bash
# Cloud Run side: ensure MAINTENANCE_MODE is unset
gcloud run services update temple-api --project=temple-prod --region=us-central1 \
  --remove-env-vars=MAINTENANCE_MODE

# Fly side: leave MAINTENANCE_MODE=true so Fly continues returning 503 if traffic trickles back to it
# (This is a safety — if DNS cache somewhere still points at Fly, customers get a maintenance page, not stale data)
```

### 4.9 T+100 — end-to-end verification

Run through the production sanity script (store this in `scripts/post-cutover-check.sh`):

- [ ] Customer login works (use a real test account, not admin)
- [ ] Equipment intake: submit a test record end-to-end
- [ ] Appraiser iOS app: sign in and hit the config endpoint
- [ ] Admin panel loads and paginates a list
- [ ] A PDF report renders for a known equipment record
- [ ] A test SMS and email are delivered
- [ ] Sentry shows the new release marker
- [ ] Cloud Monitoring uptime check for `/api/v1/health` is green
- [ ] Audit log entry for the test actions is written to Cloud SQL

All green → status page update.

### 4.10 T+120 — announce "resolved"

Status page: **"Maintenance window completed. All systems operational. Customers may need to log in again."**

Email the customer list: "We're back online, thanks for your patience."

Record total cutover time in `project_notes/migration-rehearsal.md` (rename to `migration-log.md` once done).

---

## 5. Rollback Plan

### 5.1 Decision tree

A rollback decision happens when **any one** of these is true:

- Row counts don't match between Neon and Cloud SQL after dump+restore
- Smoke tests fail on the Cloud Run canary (before DNS flip)
- Post-DNS-flip smoke tests or real traffic shows elevated 5xx or customer-visible errors and the root cause isn't immediately obvious

### 5.2 Pre-DNS-flip rollback (steps 4.1–4.6 complete; 4.7 not yet run)

Easy — nothing customer-facing changed.

```bash
# 1. Exit maintenance mode on Fly
flyctl secrets unset MAINTENANCE_MODE --app temple-api-prod

# 2. Tear down the half-migrated Cloud SQL prod DB
gcloud sql instances delete temple-prod-pg --project=temple-prod --quiet

# 3. Status page: "Maintenance postponed. All services restored."

# 4. Root-cause the failure in project_notes/incidents.md before rescheduling
```

Fly is still serving. Neon is untouched. Nothing was lost.

### 5.3 Post-DNS-flip rollback (steps 4.7+ complete)

Harder because traffic has already hit Cloud Run and new writes landed in Cloud SQL. The choice is: (a) roll forward (fix the issue, keep the Cloud SQL data), or (b) roll back to Neon and accept losing any data written to Cloud SQL in the intervening minutes.

**Option A — roll forward (preferred):**

- Identify the problem (log, metric, error)
- Patch code or config and redeploy to Cloud Run
- Use Cloud SQL PITR if data damage occurred (`12_gcp_production_target.md` §6.3)

**Option B — flip back to Fly (only if Option A is unworkable):**

```bash
# 1. Enable maintenance on Cloud Run
gcloud run services update temple-api --project=temple-prod --region=us-central1 \
  --set-env-vars=MAINTENANCE_MODE=true

# 2. Export any new data from Cloud SQL (since cutover)
pg_dump "$CLOUDSQL_PROD_URL" \
  --data-only \
  --where "created_at > 'CUTOVER_TIMESTAMP'" \
  --table "customers" --table "equipment_records" --table "appraisal_submissions" \
  > /tmp/delta.sql

# 3. Load delta into Neon
psql "$NEON_PROD_URL" < /tmp/delta.sql

# 4. Verify row counts again

# 5. Disable maintenance on Fly
flyctl secrets unset MAINTENANCE_MODE --app temple-api-prod

# 6. Flip DNS back to Fly
#    Cloudflare → api.templehe.com CNAME back to temple-api-prod.fly.dev

# 7. Enable maintenance on Cloud Run permanently, keep the GCP env warm but dark
# 8. Status page: "Rollback completed. Investigating root cause."
```

Either way — document in `project_notes/incidents.md` and do a full postmortem before the next attempt.

---

## 6. Post-Cutover Stabilization (T+0 through T+30 days)

### 6.1 First week — active monitoring

- [ ] Daily triage ritual (`12_gcp_production_target.md` §7.6) every morning
- [ ] Sentry: any new issues? Resolve or file.
- [ ] Cloud Monitoring: all alert policies green?
- [ ] Cloud SQL slow-query log: anything new?
- [ ] Cost dashboard: tracking to budget?
- [ ] Customer support inbox: any cutover-related complaints?

### 6.2 Cost reconciliation

Compare actual GCP billing for week 1 to the projection in `12_gcp_production_target.md` §1.2. If off by > 20%, investigate (usually Cloud Run min-instances or Cloud SQL sizing).

### 6.3 Update documentation

- [ ] `project_notes/decisions.md` — add ADR-002 recording the cutover completion, actual timings, any deviations from plan
- [ ] `10_operations_runbook.md` — mark Fly.io as "legacy, kept warm until DATE"
- [ ] `12_gcp_production_target.md` — promote to primary reference; `10_operations_runbook.md` demoted to legacy
- [ ] `00_overview.md` — update Tech Stack section to reflect GCP as active
- [ ] `11_security_baseline.md` — review Fly-specific items (log shipping, Cloudflare WAF) and port to GCP equivalents (Cloud Logging, Cloud Armor)

---

## 7. Sunset (T+30 days)

Decommission Fly and Neon once the GCP platform has been stable for 30 days. Do **not** skip the waiting period.

### 7.1 Final data sync from Fly to GCS (archival)

Even though Neon data is duplicated into Cloud SQL, keep a final cold archive:

```bash
# One last Neon dump
pg_dump "$NEON_PROD_URL" | gzip -9 > /tmp/neon-final-$(date +%Y%m%d).sql.gz

# Upload to GCS with a long lifecycle (7 years)
gsutil cp /tmp/neon-final-*.sql.gz gs://temple-prod-archive/cutover/
gsutil lifecycle set lifecycle-archive.json gs://temple-prod-archive
```

### 7.2 Decommission Fly

```bash
# Stop each app (keeps the app definition, zero billing)
for app in temple-api-dev temple-api-staging temple-api-prod \
           temple-web-dev temple-web-staging temple-web-prod \
           temple-he-backup; do
  flyctl scale count 0 --app "$app" --yes
done

# Wait 7 more days to confirm nothing breaks (the Fly apps are still addressable)

# Delete
for app in ...; do flyctl apps destroy "$app" --yes; done

# Revoke all Fly API tokens
flyctl tokens list | grep -v '^ID' | awk '{print $1}' | xargs -I{} flyctl tokens revoke {}
```

### 7.3 Decommission Neon

```bash
# Final verification: row counts in Cloud SQL still match what was in Neon
# (compare against the saved row-count report from T+100)

# Delete branches in reverse order
neonctl branches delete --project-id $NEON_PROJECT_ID --id <dev-branch-id>
neonctl branches delete --project-id $NEON_PROJECT_ID --id <staging-branch-id>
neonctl branches delete --project-id $NEON_PROJECT_ID --id <prod-branch-id>

# Delete project
neonctl projects delete --id $NEON_PROJECT_ID
```

### 7.4 Decommission R2

```bash
# Migrate remaining objects if any drifted in between cutover and sunset (shouldn't have, but check)
rclone sync r2:temple-he-photos gcs:temple-prod-photos --dry-run

# If clean:
rclone purge r2:temple-he-photos
rclone purge r2:temple-he-reports
# Keep R2 backups bucket for another 90 days as belt-and-suspenders
```

### 7.5 Update `project_notes/decisions.md`

Append ADR-003: "Fly.io and Neon sunset completed, data archived to `gs://temple-prod-archive/`, CI and runbook references updated to GCP-only."

---

## 8. Checklists Summary

**Pre-flight:**
- [ ] GCP target architecture standing on staging
- [ ] Staging rehearsal run and timed
- [ ] DNS TTLs dropped to 60 s at T-24h
- [ ] Backups fresh (Neon + R2 + secrets)
- [ ] Customer email sent 48 hours out

**Cutover:**
- [ ] Maintenance mode → Neon final snapshot → Neon dump → Cloud SQL restore → row-count check
- [ ] R2 → GCS rclone sync → size check
- [ ] Cloud Run canary deploy → smoke tests pass
- [ ] DNS flip → 100% traffic to Cloud Run
- [ ] Exit maintenance → end-to-end verification
- [ ] Status page + email resolved

**Stabilization (T+1 to T+30):**
- [ ] Daily triage for first 7 days
- [ ] Cost reconciliation at T+7
- [ ] Documentation updates complete by T+14

**Sunset (T+30+):**
- [ ] Final Neon dump archived to GCS
- [ ] Fly apps destroyed
- [ ] Neon project destroyed
- [ ] R2 primary buckets emptied
- [ ] ADR-003 committed
- [ ] Runbook references cleaned up

---

## 9. Related documents

- `project_notes/decisions.md` — ADRs for the migration decision
- `10_operations_runbook.md` — Fly.io active ops (legacy after cutover)
- `12_gcp_production_target.md` — GCP target architecture (primary after cutover)
- `11_security_baseline.md` — application-level security (platform-agnostic; carries over unchanged)
