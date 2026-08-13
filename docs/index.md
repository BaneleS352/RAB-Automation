# RAB Automation Service — Documentation Index

Comprehensive documentation for the **Jira Release Advisory Board (RAB) automation
service**, a FastAPI application that drives a sequential SDL → SDM approval
workflow with an SQLite audit trail, Teams notifications, and an HTML dashboard.

## Quick start

| Topic | Guide |
|-------|-------|
| Install & configure | [Setup & Configuration](setup.md) |
| All HTTP endpoints & payloads | [API Reference](api_reference.md) |
| The SDL → SDM workflow in detail | [Architecture](architecture.md) |
| SQLite schema & repository layer | [Data & Audit Trail](database.md) |
| Running & writing tests | [Testing](testing.md) |
| Dashboard & demo (Run Tests, dummy flow) | [Dashboard & Demo](dashboard.md) |
| Deployment, security, operations | [Operations](operations.md) |
| Project roadmap & status | [Roadmap](roadmap.md) |

## At a glance

- **Language / runtime**: Python ≥ 3.11, installed under 3.12/3.13
- **Framework**: FastAPI (Uvicorn ASGI server)
- **Persistence**: async SQLite via `aiosqlite`
- **External integrations**: Jira Cloud (required for full flow),
  Azure DevOps, Microsoft Teams (incoming webhook or Bot Framework; optional)
- **Observability**: `/health`, `/metrics`, HTML dashboard,
  structured `INFO` logging
- **Tests**: `pytest` with `pytest-asyncio`, **163 tests** across 18 files

## Feature checklist

- [x] Jira webhook ingestion (`POST /webhooks/jira`)
- [x] Webhook idempotency via `X-Idempotency-Key`
- [x] Jira issue-key validation (strict pattern)
- [x] RAB field validation (12 required fields)
- [x] Sequential SDL → SDM approval state machine
- [x] Approval / rejection decisions persisted to SQLite
- [x] Meeting-decision step (needs / no meeting)
- [x] SQLite audit trail (`rab_records`, `approval_events`, `webhook_events`)
- [x] `GET /rab/records` JSON API with pagination
- [x] Azure DevOps client (PR + pipeline checks; optional)
- [x] Teams notifications via incoming webhook (MessageCard `HttpPOST` buttons) or Bot Framework (optional)
- [x] Azure Key Vault secret resolution with env fallback
- [x] In-process async task queue
- [x] `/metrics` endpoint + request middleware
- [x] HTTP client timeouts (30s) everywhere
- [x] SQL-injection-safe column allowlisting
- [x] HTML dashboard (overview KPIs, records search/filter/pagination, per-issue timeline, webhook ledger, metrics, demo)
- [x] "Run Tests" button in the dashboard
- [x] Dummy approval flow (`GET /demo/flow`)

---

See the side-table guides above for deep dives into each area.