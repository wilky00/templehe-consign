# Phase 3 Status Report — Sales CRM, Lead Routing & Shared Calendar

**Branch:** `phase3-sales-crm` (cut from `main` at commit `a42ad7b` on 2026-04-24)
**Phase spec:** `dev_plan/03_phase3_sales_crm.md`
**Started:** 2026-04-24

---

## Sprint 1 — Record Locking + Duplicate Change-Request Guard

**Completed:** 2026-04-24
**Scope:** Epic 3.5 (Record Locking, manager override) + Phase 2 Sprint 3 carry-over (duplicate change-request guard).

### Built

| Layer | File | Notes |
|---|---|---|
| Migration | `api/alembic/versions/009_phase3_change_request_resolution_and_uniqueness.py` | Adds `change_requests.resolved_by`; partial UNIQUE index forcing one pending per record. |
| Model | `api/database/models.py` (ChangeRequest) | `resolved_by` FK column. |
| Service | `api/services/record_lock_service.py` | POC impl — unique-constraint-as-primitive, 15-min TTL, self-heal stale rows. Redis-swap stable. |
| Schema | `api/schemas/record_lock.py` | `LockAcquireRequest`, `LockInfoOut`, `LockConflictOut`. |
| Router | `api/routers/record_locks.py` | POST acquire · PUT heartbeat · DELETE release · DELETE override. Audit every state transition. |
| Service fix | `api/services/change_request_service.py` | Catch `IntegrityError` on duplicate pending → 409. |
| Infra | `api/main.py`, `api/routers/health.py` | Wire router, bump `_EXPECTED_MIGRATION_HEAD` → `"009"`. |

### Key decisions

1. **Postgres unique constraint is the lock's atomic primitive.** ADR-002 offered `pg_try_advisory_lock` as the acquire mechanism; we chose the table's UNIQUE constraint on `(record_id, record_type)` instead. Simpler code, visible in `psql`, and the unique index guarantees at-most-one active lock row. Advisory locks are session-scoped and would muddy forensic SQL.
2. **Release deletes the row.** The `overridden_by` / `overridden_at` columns on the Phase 1 `record_locks` schema go unused in the POC — the audit trail lives in `audit_logs`. Keeping them in the schema is harmless and documents intent; dropping them is future scope only if we rewrite.
3. **One-pending-per-record enforced at the DB, not just the service.** The partial unique index means the rule can't be violated from any callsite (direct SQL, seed script, future sales endpoint). The service-layer 409 is just the translation.
4. **Redis-swap contract locked in.** The service exports four functions with stable signatures: `acquire(record_id, record_type, user_id) → LockInfo`, `heartbeat(...) → LockInfo`, `release(...) → bool`, `override(...) → LockInfo | None`. Every test hits only these. Swapping the bodies to `SET NX PX 900000` + `PEXPIRE` at GCP migration keeps every caller green. Noted as a Phase 3 addendum to ADR-013 (to be committed when Sprint 3's round-robin lands the same pattern).

### Tests added (12)

- `test_record_locks.py` (10): acquire happy + audit, 409 with locked_by body, same-user refresh, replaces expired lock from other user, heartbeat refresh, heartbeat 404 (no lock / non-owner), release (owner deletes, idempotent on missing), manager override (happy + audit + prior-holder info in before_state), customer forbidden from override (403), cross-record isolation.
- `test_change_requests.py` (2): second pending request on same record → 409 with "already pending" copy; new request accepted after first is resolved (partial index only binds pending rows).

### Test results

- `make test-api`: **209/209 passed, 95.86% coverage** (85% floor).
- No prior tests regressed (Phase 2 baseline was 195/195).

### Bugs found + fixed

None introduced; the duplicate-change-request guard was carry-over from Phase 2's known-issues list (now closed).

### Open follow-ups for later sprints

- **Expired-lock sweeping**: Sprint 1 self-heals a stale lock on the next acquire. Scale-out via `fn_sweep_retention()` (extend in Sprint 3 or 4 migration) — not urgent at POC volume.
- **Sales dashboard lock integration** (Sprint 2): the `/sales/equipment/{id}` detail page must acquire on open, heartbeat every 60s, release on close / navigation.
- **No new manual tasks** for Jim — zero new secrets, DNS records, or third-party setups required this sprint.

### Next

- **Sprint 2 — Sales Dashboard + Record View + Cascade + Manual Publish + Change-Request Resolution.** Starts after this close-out commit lands.
