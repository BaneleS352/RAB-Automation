# RAB Automation Service

Lightweight Jira **Release Advisory Board (RAB)** automation service built with FastAPI.

Receives Jira webhook events, validates RAB-required ticket fields, drives a sequential **SDL → SDM** approval workflow with Teams adaptive-card notifications, and persists a full audit trail to SQLite — surfaced through JSON APIs, Prometheus-style metrics, and an HTML dashboard.

## Features

- **Jira webhook ingestion** with idempotency dedup (`X-Idempotency-Key` header)
- **Field validation** of 12 RAB-required ticket fields (Date/Time, RAB Approver, PR Link, Pipeline Link, Developer, Team Lead, PM, QA, Environment, Rollback details, etc.)
- **Sequential approval state machine**: SDL → SDM, with approve/reject handling and reason capture
- **Azure DevOps integration**: pull-request and pipeline status checks (optional)
- **Teams notifications**: adaptive cards for validation, approval requests, decisions, and release-ready — via Azure Bot **or** a simple incoming webhook (no app registration, no premium licensing)
- **SQLite audit trail**: `rab_records`, `approval_events`, `webhook_events`
- **Production hardening**: async task queue, Azure Key Vault secret resolution, request metrics middleware, configurable HTTP timeouts, SQL-injection-safe column allowlisting
- **HTML dashboard**: overview KPIs, audit-trail search/filter/pagination, per-issue timeline, webhook ledger, metrics, and demo views (`/dashboard/*`)
- **Run tests from the UI**: a "Run Tests" button in the dashboard navbar executes the full pytest suite in an isolated subprocess
- **Dummy approval flow**: `/demo/flow` runs a full simulated SDL → SDM → meeting workflow against a stub Jira client, producing real logs and audit records with no external calls
- **163 passing tests** across 18 test files

## Project Structure

```text
rab-automation/
  app/
    main.py                    # FastAPI entry point (lifespan, static mount, middleware)
    config.py                  # pydantic-settings configuration
    logging_config.py          # Logging setup
    exceptions.py              # Custom HTTP exceptions
    database.py                # Async SQLite connection + schema
    api/
      health.py                # GET /health (JSON health with connection status)
      webhooks.py              # POST /webhooks/jira
      teams.py                 # POST /webhooks/teams (Bot Framework activities)
      rab.py                   # GET /rab/records (JSON audit trail)
      dashboard.py             # GET /dashboard/health, /dashboard/records (HTML)
      metrics.py               # GET /metrics + MetricsMiddleware
      routes.py                # Router aggregation
    models/
      webhook.py               # Jira webhook payload models (with issue-key validation)
      responses.py             # API response models
    repositories/
      rab_repository.py        # Audit-trail persistence (column allowlisting)
    services/
      rab_orchestrator.py      # RAB workflow orchestration
      approval_service.py      # SDL → SDM state machine
      jira_client.py           # Jira REST API client
      field_validator.py       # RAB field validation
      azure_devops_client.py   # Azure DevOps PR/pipeline checks
      teams_client.py          # Teams / Bot Framework client
      card_templates.py        # Adaptive Card templates
      key_vault_client.py      # Azure Key Vault with env fallback
      task_queue.py            # In-process async worker
      test_runner.py           # Runs pytest in a subprocess with isolated DB
      dummy_flow.py            # Simulated RAB flow with stub Jira client
    templates/                 # Jinja2 HTML templates
    static/css/                # Dashboard styling
  tests/                       # 18 test files, 163 tests
  .env.example
  requirements.txt
  pyproject.toml
```

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Set environment variables

Copy the example env file and fill in your values:

```bash
cp .env.example .env
```

The only **required** variable is `JIRA_WEBHOOK_URL`. All other settings are optional — the service runs and tests pass without them (unconfigured integrations are reported as "not connected" on the health endpoint).

To use Jira API features (fetching issue details, validation, comments, approvals), configure:

```bash
JIRA_BASE_URL=https://yourcompany.atlassian.net
JIRA_EMAIL=automation.user@company.com
JIRA_API_TOKEN=your_token
```

See `.env.example` for the full list of settings, including custom Jira field mappings, workflow transition IDs, Azure DevOps, Teams/Bot, SharePoint, and Key Vault configuration.

### 3. Run locally

```bash
uvicorn app.main:app --reload
```

The service starts at `http://localhost:8000`. The dashboard is at `http://localhost:8000/dashboard/health`.

## Endpoints

### HTML dashboard

| Endpoint | Description |
|---|---|
| `/` | Redirects to `/dashboard/health` |
| `/dashboard/health` | **Overview** — connection status + pipeline KPIs, aging approvals, recent failures (auto-refreshes every 30s) |
| `/dashboard/records` | Audit-trail table with issue-key search, status filter, and pagination |
| `/dashboard/records/{issue_key}` | Per-issue detail page with the full approval-event timeline |
| `/dashboard/webhooks` | Webhook ingestion ledger (`webhook_events`) |
| `/dashboard/metrics` | Human-readable operational metrics (uptime, requests, queue load) |
| `/dashboard/demo` | Form-driven dummy approval flow |
| `/dashboard/test` | Runs the full pytest suite and shows pass/fail summary |

### JSON API

| Endpoint | Description |
|---|---|
| `GET /health` | Health status + per-integration connection details |
| `GET /metrics` | Prometheus-style metrics (uptime, requests, failures, queue state) |
| `GET /rab/records` | List audit records (`?limit=&offset=&status=&q=`) |
| `GET /rab/records/{issue_key}` | Audit record for a single issue |
| `GET /rab/records/{issue_key}/events` | Approval-event timeline for a single issue |
| `GET /rab/webhook-events` | Webhook ingestion history (`webhook_events`) |
| `GET /rab/summary` | Pipeline counts + aging approvals (`?aging_days=`) |

### Webhooks

| Endpoint | Description |
|---|---|
| `POST /webhooks/jira` | Receive Jira events; pass `X-Idempotency-Key` to deduplicate |
| `POST /webhooks/teams` | Receive Bot Framework activities **or** MessageCard `HttpPOST` callbacks (approve/reject/meeting card clicks) |
| `GET /demo/flow` | Run simulated RAB flow (`?issue_key=&reject=&needs_meeting=`) — produces logs + audit records |

#### Jira webhook example

```bash
curl -X POST "$JIRA_WEBHOOK_URL" \
  -H "Content-Type: application/json" \
  -H "X-Idempotency-Key: event-12345" \
  -d '{
    "webhookEvent": "jira:issue_created",
    "issue": {
      "key": "PROJ-123"
    }
  }'
```

Response:

```json
{
  "status": "accepted",
  "issue_key": "PROJ-123",
  "event_type": "jira:issue_created",
  "result": "approval_requested_sdl",
  "idempotent_replay": false
}
```

## Workflow

1. **Ingest** — a Jira webhook event arrives with an issue key.
2. **Validate** — required RAB fields are checked against Jira issue data; a comment and Teams card are posted on failure.
3. **SDL approval** — an adaptive card asks the SDL to approve or reject (with reason).
4. **SDM approval** — on SDL approval, the SDM is asked the same.
5. **Decision** — once both approvals pass, a meeting-required/no-meeting-needed card is sent; the issue is marked `release_ready` or `meeting_scheduled`.
6. **Persist** — every stage is written to SQLite (`rab_records`, `approval_events`, `webhook_events`).

Every stage is persisted via `app/repositories/rab_repository.py`, so the full lifecycle is queryable through `/rab/records`.

## Configuration Highlights

- `DATABASE_PATH` — override the SQLite file location (default: `rab_automation.db` in the project root).
- `AZURE_DEVOPS_API_VERSION` — Azure DevOps REST API version (default `7.1`).
- `JIRA_FIELD_*` — map logical RAB field names to Jira custom field IDs.
- `LOG_LEVEL` — `DEBUG`, `INFO`, `WARNING`, etc. (default `INFO`).

### Teams: two delivery modes

The service picks the incoming-webhook mode automatically when `TEAMS_WEBHOOK_URL` is set, and otherwise falls back to Azure Bot.

| Mode | Config | Notes |
|---|---|---|
| **Incoming webhook** (simplest) | `TEAMS_WEBHOOK_URL`, plus `TEAMS_CALLBACK_URL` | No app registration or premium license. Cards are delivered as MessageCards; `Action.Submit` buttons become `HttpPOST` buttons that POST back to `TEAMS_CALLBACK_URL` (a publicly reachable URL pointing at `/webhooks/teams`). MessageCards don't support text inputs, so the in-card rejection "reason" field is not captured in this mode. |
| **Azure Bot** | `TEAMS_BOT_APP_ID`, `TEAMS_BOT_CLIENT_SECRET`, `TEAMS_CHANNEL_ID` | Full adaptive-card `Action.Submit` interactivity with the reason input, but requires app registration and OAuth. |

## Running Tests

```bash
pytest
```

Tests use monkeypatched environment variables and an in-memory/test database — no `.env` file or external services required.

## Documentation

Full documentation lives in [`docs/`](docs/index.md): [setup](docs/setup.md),
[architecture](docs/architecture.md), [database](docs/database.md),
[testing](docs/testing.md), [dashboard & demo](docs/dashboard.md),
[operations](docs/operations.md), and [roadmap](docs/roadmap.md).

## Security Notes

- All SQL identifiers are validated against module-level column allowlists before use (no raw user input reaches SQL).
- Jira issue keys are validated against a strict `^[A-Z][A-Z0-9_]+-\d+$` pattern.
- HTTP clients use explicit timeouts (`30s`) to prevent hangs.
- Key Vault errors do not leak secret names; vault URLs are logged at DEBUG only.
