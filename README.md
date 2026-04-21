# Temple Heavy Equipment — Consignment Platform

Internal platform for equipment intake, appraisal, and consignment management.

## Quickstart (< 10 minutes)

**Prerequisites:** Docker, Node 22+, Python 3.12+, [uv](https://docs.astral.sh/uv/)

```bash
# 1. Clone and copy env template
git clone <repo-url> templehe-consign && cd templehe-consign
cp .env.example .env
# Edit .env — set JWT_SECRET_KEY, TOTP_ENCRYPTION_KEY, SEED_ADMIN_EMAIL, SEED_ADMIN_PASSWORD

# 2. Install dependencies
make install

# 3. Start Docker services, run migrations, seed database
make dev

# 4. Start the API server (new terminal)
cd api && uv run uvicorn main:app --reload --port 8000

# 5. Start the web server (new terminal)
cd web && npm run dev
```

Open [http://localhost:5173](http://localhost:5173) for the web app.
Open [http://localhost:8025](http://localhost:8025) for the email catcher (Mailpit).
API docs at [http://localhost:8000/docs](http://localhost:8000/docs).

## Key Commands

| Command | Description |
|---|---|
| `make dev` | Start Docker + migrate + seed |
| `make reset` | Wipe volumes and rebuild |
| `make seed` | Re-seed database (idempotent) |
| `make test-unit-api` | API unit tests (85% coverage gate) |
| `make test-integration-api` | API integration tests |
| `make lint` | Lint Python + TypeScript |

## Generating Secret Keys

```bash
# JWT keys
python -c "import secrets; print(secrets.token_hex(64))"

# Fernet key for TOTP encryption
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Architecture

See `dev_plan/00_overview.md` for the full architecture reference.

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic |
| Frontend | React 18, TypeScript (strict), Tailwind CSS, React Query |
| Database | PostgreSQL 15 (local Docker → Neon POC → Cloud SQL GCP) |
| Email | Mailpit (local) → SendGrid (staging/prod) |
| Hosting | Docker Compose (local) → Fly.io (POC) → GCP Cloud Run (prod) |

## Infra Setup (Fly.io POC)

See `docs/fly-provisioning.md` for the step-by-step Fly.io and Neon provisioning guide.

## Project Notes

- `project_notes/decisions.md` — ADR log (all architecture decisions)
- `project_notes/progress.md` — What's done and in-flight
- `project_notes/known-issues.md` — Open bugs and blockers
