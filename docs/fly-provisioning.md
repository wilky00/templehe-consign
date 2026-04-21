# Fly.io Provisioning Guide

One-time manual setup. Run these commands in order. Claude will not execute them — they affect shared infrastructure.

## Prerequisites

```bash
# Install flyctl
brew install flyctl

# Log in (opens browser)
fly auth login

# Verify
fly auth whoami
```

## 1. Create the Fly.io Organization

```bash
# If temple-he org doesn't exist yet
fly orgs create temple-he

# Require 2FA for all org members (required per security checklist)
# Do this via: https://fly.io/orgs/temple-he/settings → Security → Require 2FA
```

## 2. Create the Six Apps

```bash
# API apps
fly apps create temple-api-dev    --org temple-he
fly apps create temple-api-staging --org temple-he
fly apps create temple-api-prod   --org temple-he

# Web apps
fly apps create temple-web-dev    --org temple-he
fly apps create temple-web-staging --org temple-he
fly apps create temple-web-prod   --org temple-he
```

## 3. Set Secrets (per app)

Each app needs its own `fly secrets set`. Example for dev:

```bash
fly secrets set -a temple-api-dev \
  DATABASE_URL="postgresql+asyncpg://..." \
  JWT_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(64))')" \
  TOTP_ENCRYPTION_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')" \
  ENVIRONMENT="development" \
  CORS_ORIGINS="https://temple-web-dev.fly.dev" \
  SENDGRID_API_KEY="..." \
  SENTRY_DSN="..."
```

Repeat for staging and prod. **Do not reuse secrets between environments.**

## 4. Neon Postgres Setup

1. Create account at [neon.tech](https://neon.tech)
2. Create project `temple-he` — select region US East
3. Create three branches: `dev`, `staging`, `prod`
4. Enable PITR on the `prod` branch (requires Pro plan)
5. Copy each branch's connection string as `DATABASE_URL` in the respective Fly app's secrets

## 5. Cloudflare R2 Buckets

Via Cloudflare dashboard (R2 → Create bucket) or Terraform (see `infra/cloudflare/`):

```
temple-he-photos   — versioning enabled
temple-he-reports  — versioning enabled
temple-he-backups  — versioning enabled
```

Create an R2 API token (R2 → Manage R2 API Tokens → Create Token) scoped to all three buckets. Set as `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` in each app's Fly secrets.

## 6. Deploy fly.toml Configs

Once the apps exist, deployment is automatic via GitHub Actions CI. To trigger manually:

```bash
# Deploy API to dev
fly deploy -a temple-api-dev --config infra/fly/temple-api-dev.toml

# Deploy web to dev
fly deploy -a temple-web-dev --config infra/fly/temple-web-dev.toml
```

## 7. Run Database Migrations (post-deploy)

```bash
# After first deploy to an environment
fly ssh console -a temple-api-dev --command "uv run alembic upgrade head"

# Then seed
fly ssh console -a temple-api-dev --command "uv run python scripts/seed.py"
```

## 8. Configure Spend Alerts

In the Fly.io dashboard: Settings → Billing → Spend Notifications:
- Alert at $20/month for `temple-he` org

In Neon: Project Settings → Billing → Alerts → $25/month.

## 9. Cloudflare Terraform (WAF + Rate Limiting)

```bash
cd infra/cloudflare
terraform init
terraform plan
terraform apply
```

You'll need `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ZONE_ID` set as env vars or in `terraform.tfvars` (gitignored).

## 10. Generate Per-App Deploy Tokens (for GitHub Actions)

```bash
# One token per app — NOT your personal auth token
fly tokens create deploy --name "github-actions" -a temple-api-dev
fly tokens create deploy --name "github-actions" -a temple-api-staging
fly tokens create deploy --name "github-actions" -a temple-api-prod
fly tokens create deploy --name "github-actions" -a temple-web-dev
fly tokens create deploy --name "github-actions" -a temple-web-staging
fly tokens create deploy --name "github-actions" -a temple-web-prod
```

Add each token as a GitHub Actions secret:
- `FLY_API_TOKEN_API_DEV`, `FLY_API_TOKEN_API_STAGING`, `FLY_API_TOKEN_API_PROD`
- `FLY_API_TOKEN_WEB_DEV`, `FLY_API_TOKEN_WEB_STAGING`, `FLY_API_TOKEN_WEB_PROD`

Destroy local token copies after adding to GitHub — they're in GitHub Secrets now.

## Google OAuth Setup (Phase 1 stub — not yet active)

When SSO is implemented:

1. Go to [console.cloud.google.com](https://console.cloud.google.com) → APIs & Services → OAuth 2.0 Client IDs
2. Application type: Web application
3. Authorized redirect URIs:
   - `https://temple-api-dev.fly.dev/api/v1/auth/google/callback`
   - `https://temple-api-staging.fly.dev/api/v1/auth/google/callback`
   - `https://api.templehe.com/api/v1/auth/google/callback`
4. Set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `GOOGLE_WORKSPACE_DOMAIN` in Fly secrets per environment
