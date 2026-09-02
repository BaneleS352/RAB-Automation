# Architecture

## High-level flow

```
Jira  ──webhook──▶  POST /webhooks/jira  ──▶  RabOrchestrator
                                                  │
                    ┌─────────────────────────────┤
                    ▼                             ▼
            JiraClient (fetch issue)      FieldValidator (12 fields)
                    │                             │
                    └──────────┬──────────────────┘
                               ▼
                    ApprovalService (state machine)
                               │
               SDL request ─▶ SDL approve ─▶ SDM request ─▶ SDM approve
                               │                              │
                               ▼                              ▼
                     (reject stops flow)             Meeting decision card
                                                              │
                                                              ▼
                                                meeting_scheduled | release_ready
```

Every stage writes to SQLite through `RabRepository`:

- Validation result → `rab_records.validation_result`, `status`
- Approval decisions → `rab_records.sdl_approval/sdm_approval` +
  one row in `approval_events`
- Meeting decision → `rab_records.meeting_needed`, `status`
- Webhook ingestion → `webhook_events` (dedup)

## Application entry point — `app/main.py`

`create_app()` builds the FastAPI app:

- loads settings (`get_settings()`) and configures logging
- lifespan handler: `init_db()` → start task queue → `yield` →
  stop queue → `close_db()`
- mounts `/static`, includes all routers, adds `MetricsMiddleware`
- `/` redirects to `/dashboard/health`

The module-level `app = create_app()` is what uvicorn imports.

## Routers

| Module | Router prefix | Responsibility |
|--------|---------------|----------------|
| `app/api/health.py` | `/health` | JSON health with per-integration status |
| `app/api/webhooks.py` | `/webhooks/jira` | Jira event ingestion + idempotency |
| `app/api/teams.py` | `/webhooks/teams` | Bot Framework activities + MessageCard `HttpPOST` callbacks (card clicks) |
| `app/api/rab.py` | `/rab` | Audit-record JSON queries (records, timeline, webhook events, summary) |
| `app/api/demo.py` | `/demo` | Simulated approval flow |
| `app/api/dashboard.py` | `/dashboard` | HTML pages (overview, records, detail, webhooks, metrics, demo, tests) |
| `app/api/metrics.py` | `/metrics` | Operational counters + ASGI middleware |

All are aggregated in `app/api/routes.py`.

## Service layer — `app/services/`

### `rab_orchestrator.py` — `RabOrchestrator`

Central workflow coordinator. Accepts optional injected collaborators so tests
and Demo Lab scenarios use live Jira tickets:

```python
RabOrchestrator(
    jira_client=..., field_validator=..., teams_client=...,
    approval_service=..., rab_repo=...,
)
```

Key methods:

- `handle_jira_event(issue_key, event_type, payload)` — fetch issue, validate,
  persist validation, comment + notify, create approval, request SDL approval.
- `handle_approval_callback(issue_key, action, approver, reason)` — delegates to
  `ApprovalService`, persists the event, sends cards/comments, then requests the
  next step (SDM) or the meeting decision.
- `handle_meeting_callback(issue_key, needs_meeting)` — persists the final state.

### `approval_service.py` — `ApprovalService`

In-memory sequential state machine (`ApprovalStep.SDL → SDM`).

- `create_approval(issue_key, summary)` — create state
- `process_response(issue_key, action, reason)` — approve/reject; returns
  `decision`, `rejected_by`, `next_step`
- `is_fully_approved` / `is_rejected` — convenience queries

State is stored in a module-level dict (`_store`), so it resets on restart.
Persistence of decisions lives in `RabRepository` (the source of truth for the
audit trail).

### `jira_client.py` — `JiraClient`

Async httpx client for the Jira REST API (`/rest/api/3`). Methods: `get_issue`,
`get_issue_comments`, `add_comment`, `update_issue`, `transition_issue`,
`get_issue_remote_links`, `check_connection`. All requests use a 30s timeout.

### `field_validator.py` — `FieldValidator`

Checks the 12 required RAB fields. Builds a map from logical names to configured
Jira field keys (`JIRA_FIELD_*`); standard fields `assignee`/`reporter` map to
Jira's standard names. Returns a `ValidationResult(valid, missing_fields, detail)`.

### `azure_devops_client.py` — `AzureDevOpsClient`

Optional. Queries PRs (`/git/repositories/{repo}/pullrequests/{id}`) and builds
(`/build/builds/{id}`). `parse_pr_url()` extracts org/project/repo/PR id from a
PR URL. Unconfigured → `check_connection()` returns disconnected.

### `teams_client.py` — `TeamsClient`

Two delivery modes. When `TEAMS_WEBHOOK_URL` is set, cards are posted to the
incoming webhook as MessageCards (`send_adaptive_card_via_webhook` converts via
`to_message_card`, turning `Action.Submit` buttons into `HttpPOST` actions
targeting `TEAMS_CALLBACK_URL`). Otherwise the Bot Framework client is used:
`_get_token()` caches the bearer token with a 60-second expiry buffer;
`send_activity` / `send_message` / `send_adaptive_card` post to
`{serviceUrl}/v3/conversations/{id}/activities`. Also manages an in-memory
conversation store (`register_conversation` / `get_conversation`).

### `card_templates.py`

Adaptive Card builders: `validation_passed_card`, `validation_failed_card`,
`approval_request_card`, `rejection_notification_card`, `meeting_decision_card`,
`developer_notification_card`. `to_message_card(card, callback_url)` converts an
AdaptiveCard into an Office 365 MessageCard for incoming-webhook delivery.

### `key_vault_client.py` — `KeyVaultClient`

Resolves secrets from Azure Key Vault when a vault URL is provided, otherwise
falls back to environment variables. Error messages are generic (never leak
secret names); the vault URL is logged at `DEBUG`.

### `task_queue.py` — `TaskQueue`

In-process async worker. `enqueue(coro)` runs up to `max_concurrent` (default 4)
tasks concurrently; tracks `Task` states (`pending`, `running`, `completed`,
`failed`). `get_task_queue()` returns the singleton. `start()`/`stop()` are
idempotent; `stop()` guards against a not-running worker.

### `dummy_flow.py` — `DummyFlowService`

Demo Lab: creates a live Jira ticket, then runs the real orchestrator through
the selected lifecycle scenario. See [Dashboard & Demo](dashboard.md).

### `test_runner.py`

Runs `pytest` in a subprocess from the dashboard. Uses `subprocess.run` inside
`asyncio.to_thread` (avoids the Windows `SelectorEventLoop` subprocess
limitation) and points tests at an isolated temp DB via `DATABASE_PATH`.

## Repository layer — `app/repositories/rab_repository.py`

`RabRepository` is the single persistence gateway. It builds SQL with **column
allowlisting** (`ALLOWED_RAB_COLUMNS`, `ALLOWED_EVENT_COLUMNS`) so no untrusted
input reaches SQL identifiers.

| Method | Purpose |
|--------|---------|
| `upsert_record(issue_key, data)` | Insert or update a `rab_records` row |
| `record_validation(issue_key, valid, detail)` | Persist the validation result |
| `record_approval_event(...)` | Insert an `approval_events` row + update status |
| `record_webhook_event(...)` | Insert a dedup row (returns False on conflict) |
| `get_all_records(limit, offset)` | Paginated list |
| `get_all_records_with_count(limit, offset, status, q)` | Paginated list + total with optional status/search filters |
| `get_record(issue_key)` | One record |
| `get_approval_events(issue_key)` | Full `approval_events` timeline for an issue |
| `get_status_counts()` | `status → count` for the dashboard KPIs |
| `get_aging_records(days)` | Tickets still waiting on approval past `days` |
| `get_recent_failures(limit)` | Latest validation failures / rejections |
| `get_webhook_events(limit)` / `get_webhook_events_with_count(...)` | Webhook ingestion history |

## Middleware

`MetricsMiddleware` (`app/api/metrics.py`) is a raw ASGI middleware that counts
requests, failures, and cumulative duration in module-level counters exposed at
`/metrics`.

## Security & hardening notes

- Column allowlisting prevents SQL injection via dynamic identifiers.
- Issue keys are regex-validated.
- HTTP clients all set `httpx.Timeout(30.0)`.
- Key Vault error text is sanitized.
- Dashboard templates escape user data via Jinja2 autoescaping.
- Test sessions use a fresh unique temp SQLite DB (see [Testing](testing.md)).
