# Roadmap & Status

## Current status

The service is feature-complete for the core RAB automation loop and fully
documented. **129 tests pass** across 18 files.

### What works today

- Jira webhook ingestion with idempotency (`X-Idempotency-Key`)
- RAB field validation (12 required fields) with strict issue-key validation
- Sequential SDL → SDM approval state machine with approve/reject + reason
- Meeting-decision step (`meeting_scheduled` / `release_ready`)
- Full SQLite audit trail (`rab_records`, `approval_events`, `webhook_events`)
- JSON query API (`/rab/records`) + Prometheus-style metrics (`/metrics`)
- HTML dashboard (health, records, test results) with a "Run Tests" button
- Dummy approval flow (`/demo/flow`) for end-to-end demos without external deps
- Optional Azure DevOps, Teams/Bot, SharePoint, Azure Key Vault integrations
- Production hardening: timeouts, column allowlisting, key-vault error
  sanitization, configurable logging

## Documentation map

| Document | Status |
|----------|--------|
| [index](index.md) — overview & links | Done |
| [setup](setup.md) — install & configure | Done |
| [architecture](architecture.md) — workflow, services, middleware | Done |
| [database](database.md) — schema, repository, isolation | Done |
| [testing](testing.md) — running & writing tests | Done |
| [dashboard](dashboard.md) — dashboard & dummy flow | Done |
| [operations](operations.md) — deploy, security, troubleshooting | Done |
| [api_reference](api_reference.md) — all endpoints & payloads | Done |

## Completed milestones

1. **Core service (Phases 1–6)** — webhook ingestion, field validation,
   approval state machine, integrations, SQLite audit trail, task queue,
   metrics, dashboard.
2. **Code audit (29 issues)** — addressed sql-injection hardening, error/secret
   leak prevention, HTTP timeouts, config extraction, task-queue race, token
   expiry, and dozens of smaller correctness/doc issues.
3. **Run Tests from the dashboard** — isolated subprocess runner with per-test
   breakdown UI.
4. **Dummy approval flow** — `/demo/flow` end-to-end simulation via the real
   orchestrator with dependency injection + stub Jira client.
5. **Documentation** — README + full `docs/` guide set.

## Known limitations & backlog

### Correctness / production-readiness

- [ ] **Persistent approval state.** `ApprovalService` keeps state in-memory; it
      resets on restart and is not multi-worker safe. Move state to SQLite/Redis
      for horizontal scaling.
- [ ] **Multi-worker SQLite.** Writes are serialized by SQLite. A connection pool
      or PostgreSQL is recommended for high write volume.
- [ ] **Retry logic on integrations.** Audit item M-02 (request retries) was
      intentionally skipped; a bounded retry/backoff for Jira/Azure/Teams calls
      is a good next step.

### Governance / workflow
- [ ] **Azure DevOps PR + pipeline verification** currently resolves links; a
      hard gate that blocks release until PRs are approved and pipelines green.
- [ ] **Webhook-level dedup for Jira retries.** Standard Jira retries lack custom
      headers, so they may reprocess. Consider an event-ID-based webhook layer.

### UX / tooling
- [ ] **Auth on the dashboard & metrics.** `/metrics`, `/health`, `/rab/records`,
      and the dashboard have no default auth — gate via reverse proxy or add
      SSO/middleware auth.
- [ ] **`/demo/flow` & `/dashboard/test` exposure** — great for demos, but should
      be feature-flagged or network-restricted in prod (they write real records /
      run subprocesses).
- [ ] **Email/Comment escalation** on rejected approvals.

### Observability
- [ ] Structured log aggregation (e.g., stdout → a log pipeline) and alerting on
      webhook failure rate.

## Suggested next steps (prioritized)

1. Move approval state to the database (enable multi-worker safety).
2. Add a request-retry middleware to the external HTTP clients.
3. Add auth to the dashboard and JSON APIs before public exposure.
4. Gate the `/demo/flow` and `/dashboard/test` endpoints for production.
5. Hard verification-gate for Azure PRs + pipeline status.