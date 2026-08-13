# Operations

Practical guidance for running, monitoring, and troubleshooting the RAB
Automation service.

## Running in production

### Process model

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

Considerations:

- The approval state machine (`ApprovalService`) is **in-memory**. With multiple
  workers, callbacks may not hit the worker that created the approval. Use a
  single worker, or move approval state into SQLite/Redis if you scale out.
- The SQLite connection is a shared singleton in-process. SQLite handles
  concurrent readers well but serializes writes; for heavy write volume consider
  a connection pool or PostgreSQL.
- The task queue is in-process and per-worker.

### Reverse proxy

Terminate TLS at a reverse proxy (nginx / Azure Front Door / IIS ARR) and proxy
to uvicorn. Forward the `Host` header and set `X-Forwarded-Proto` so redirects
and links are correct. Uvicorn's `ProxyHeadersMiddleware` is enabled by default
and will honor these headers.

### Webhook visibility

Jira must reach `POST /webhooks/jira` over HTTPS. Jira retries webhook
deliveries, so:

- keep the webhook endpoint idempotent (it is — `X-Idempotency-Key` and the
  `webhook_events` ledger protect against double-processing);
- monitor `/health` and `/metrics` to catch outages before Jira's retries
  accumulate.

## Health & readiness

`GET /health` reports connectivity for each integration. A green check:

```json
{ "jira": { "connected": true, "details": "Jira API is reachable and authenticated." } }
```

Unconfigured integrations are reported as disconnected, which is expected.

## Metrics

`GET /metrics` returns uptime, request totals, failures, average duration, and
task-queue depth. Scrape it with Prometheus or poll it from a monitor. There is
no auth on `/metrics` or `/health` by default — restrict access via the reverse
proxy if these are publicly exposed.

## Logging

Logging is configured in `app/logging_config.py`:

- Format: `%(asctime)s | %(levelname)-8s | %(name)s | %(message)s`
- Level from `LOG_LEVEL` (default `INFO`)
- Writes to stdout (captured by the process manager)
- `uvicorn.access` is quieted to `WARNING`

To debug integrations, set `LOG_LEVEL=DEBUG`. Note: the Key Vault URL is only
logged at `DEBUG`.

## Configuration changes

All configuration is environment-driven. Restart the process after changing
`.env` or environment variables. `DATABASE_PATH` can point to a different
location for rolling environments.

## Backups

`rab_automation.db` is the audit source of truth. Back it up regularly. SQLite
can be copied while the app is running for a point-in-time snapshot, but a
consistent backup is best taken via `sqlite3 .backup` or by stopping writes
briefly.

## Troubleshooting

### `PermissionError` on the SQLite DB file

A leftover process holds the file open (common on Windows after Ctrl+C or a
timed-out run). Find and stop it:

```powershell
Get-Process | Where-Object { $_.ProcessName -match 'python|uvicorn' }
Stop-Process -Id <pid> -Force
```

Be careful not to kill unrelated Python processes.

### `NotImplementedError` from the test runner

uvicorn's default event loop on Windows (`SelectorEventLoop`) does not support
`asyncio.create_subprocess_exec`. The test runner already avoids this by using
`subprocess.run` inside `asyncio.to_thread`. If you see this error, you're on an
older code path — restart the server to pick up the fix.

### Jira webhook returns 422

The issue key failed validation (`^[A-Z][A-Z0-9_]+-\d+$`) or the body was
malformed. Check the Jira payload: the key must be present and well-formed.

### Duplicate processing despite retries

Dedup requires `X-Idempotency-Key`. Jira doesn't set custom headers natively,
so standard Jira retries will reprocess. If you need strict dedup on Jira
retries, either use a webhook middleware that injects a key based on the event
ID, or make the workflow naturally idempotent (the orchestrator updates rather
than duplicates `rab_records` rows).

### Logs stop appearing

Check that `LOG_LEVEL` isn't `ERROR`/`CRITICAL` and that stdout isn't being
swallowed by the process manager. On Windows PowerShell, `uvicorn` with `--reload`
spawns a child; Ctrl+C once to stop reloader and child.

## Security checklist

- Rotate `JIRA_API_TOKEN`, `AZURE_DEVOPS_PAT`, and `TEAMS_BOT_CLIENT_SECRET`
  periodically; store them in Azure Key Vault in production.
- Treat `TEAMS_WEBHOOK_URL` like a credential — anyone with the URL can post to
  the channel. Reset the connector in Teams if it leaks.
- Keep `JIRA_WEBHOOK_URL` internal — it is the callback target for Jira.
- Restrict `/metrics`, `/health`, `/rab/records`, and the dashboard to trusted
  networks / SSO via the reverse proxy.
- The dummy flow and test runner write to real records/database — do not expose
  `/demo/flow` or `/dashboard/test` publicly.
