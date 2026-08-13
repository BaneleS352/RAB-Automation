# Testing

## Overview

The project uses `pytest` with `pytest-asyncio` (auto mode). **163 tests**
across **18 files** currently pass. Tests are fully self-contained: no `.env`,
no live Jira/Azure/Teams, and no touching the real database.

## Running the suite

```bash
pytest                      # full suite
pytest -q                   # quiet
pytest tests/test_demo_flow.py          # one file
pytest tests/test_dashboard.py -k empty # one test by keyword
```

### On Windows

Run pytest from the repo root:

```powershell
python -m pytest -q --no-header -p no:cacheprovider
```

The `--no-header -p no:cacheprovider` flags keep output compact and avoid
`.pytest_cache` churn, but are optional.

## Test isolation

`tests/conftest.py` handles session setup:

1. Sets `APP_ENV=test` **and** `DATABASE_PATH` to a fresh unique temp file
   (`rab_pytest_<uuid>.db`) **before** importing the app, so:
   - the live `rab_automation.db` is never touched;
   - every session starts from a clean, empty database (no record bleed).
2. Creates the schema via `init_db()`.
3. `pytest_sessionfinish` closes the SQLite connection so the process exits
   cleanly. (Without this, the aiosqlite background thread keeps the process
   alive and the shell appears to "hang" after a passing run.)

## What's covered

| File | Coverage |
|------|----------|
| `test_approval_service.py` | SDL→SDM state machine, approve/reject, IDs |
| `test_azure_devops_client.py` | Config checks, PR URL parsing, API errors |
| `test_dashboard.py` | Health/records/detail/webhooks/metrics/demo pages, nav, root redirect |
| `test_database.py` | Schema creation, idempotency, connection lifecycle |
| `test_demo_flow.py` | Dummy flow audit writes + `/demo/flow` endpoint |
| `test_field_validator.py` | Required-field validation logic |
| `test_health.py` | `/health` JSON + connection status |
| `test_jira_client.py` | Config guard, comments, connection check |
| `test_jira_webhook.py` | Webhook processing + response model |
| `test_key_vault_client.py` | Env fallback, error handling |
| `test_metrics.py` | `/metrics` fields and counters |
| `test_rab_api.py` | `/rab/records` list/detail/filters, events, webhook events, summary |
| `test_rab_repository.py` | All persistence methods, pagination, dedup |
| `test_task_queue.py` | Enqueue, completion, failure, stop/start |
| `test_teams_client.py` | Cards, MessageCard conversion, webhook delivery, conversation store, config checks |
| `test_teams_webhook.py` | Bot activity handling + MessageCard `HttpPOST` callbacks |
| `test_webhook_idempotency.py` | `X-Idempotency-Key` dedup |

## Adding a new test

Follow the existing patterns:

- Async service tests: just write `async def test_...` — `asyncio_mode = "auto"`
  runs them without `@pytest.mark.asyncio`.
- HTTP tests: build a client with `from app.main import create_app;
  TestClient(create_app())`, set env vars via a `monkeypatch.setenv` fixture,
  and mock external clients (see `tests/test_dashboard.py` for the pattern).
- Never assume the DB is empty — other tests may have written records. Mock the
  repository when a test needs specific data (as `test_shows_empty_state` does).

## Running tests from the dashboard

The "Run Tests" button at `/dashboard/test` launches the suite in a subprocess
with an isolated temp DB. See [Dashboard & Demo](dashboard.md).

## Performance

The full suite runs in roughly 40–70 seconds depending on the machine (much of
it is the HTTP-level webhook tests). If you only changed a service, run the
matching test file for a faster loop.
