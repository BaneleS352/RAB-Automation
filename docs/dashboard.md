# Dashboard & Demo

The service includes a server-rendered HTML dashboard (Jinja2 + CSS) plus a
demo endpoint for exercising the workflow without external services.

## Pages

| Page | Route | Shows |
|------|-------|-------|
| Overview | `/dashboard/health` | Connection status (Jira, Azure DevOps, Teams) + pipeline KPIs, tickets waiting on approval, recent failures. Auto-refreshes every 30s |
| Audit Records | `/dashboard/records` | Paginated `rab_records` with issue-key search and status filter |
| Record Detail | `/dashboard/records/{issue_key}` | All record fields + the approval-event timeline (`approval_events`) |
| Webhooks | `/dashboard/webhooks` | Recent `webhook_events` (receipts, dedup, event types) |
| Metrics | `/dashboard/metrics` | Human-readable version of `/metrics` (uptime, requests, queue load) |
| Demo | `/dashboard/demo` | Form-driven dummy approval flow |
| Test Results | `/dashboard/test` | Runs the full pytest suite and shows a summary + per-test breakdown |

Templates live in `app/templates/` (`base.html`, `health.html`, `records.html`,
`record_detail.html`, `webhooks.html`, `metrics.html`, `demo.html`, `test.html`)
with styling in `app/static/css/style.css`.

## Overview KPIs

`/dashboard/health` computes status counts (`get_status_counts`) and buckets
them into cards: **Total Tickets**, **Validated**, **Pending Approval**,
**Release Ready**, **Meeting Scheduled**, **Validation Failed**, and **Rejected**.
It also lists tickets still waiting on an approval decision older than
`?aging_days=` (default 2) and the most recent validation failures/rejections.

## Search, filter, pagination

`/dashboard/records` accepts `?q=` (issue-key substring) and `?status=` (exact
status) plus `?offset=` for paging (25 rows per page). The same filters are
exposed on the JSON endpoint `/rab/records`.

## "Run Tests" button

The navbar has a **Run Tests** button linking to `/dashboard/test`. Clicking it:

1. Launches `pytest` in a subprocess (via `app/services/test_runner.py`).
2. Points that subprocess at an isolated temp SQLite DB (`DATABASE_PATH`), so
   tests never touch the live database.
3. Parses the verbose output into per-test rows (`PASSED` / `FAILED` /
   `ERROR` / `SKIPPED`) plus totals and duration.
4. Renders the summary card, the breakdown table, and the raw output.

Because the full suite takes ~40–70s, the request blocks until pytest finishes.
If it exceeds the 120s timeout, the run is killed and the page shows a
"Timed Out" message.

The runner uses `subprocess.run` inside `asyncio.to_thread` rather than
`asyncio.create_subprocess_exec` — the latter raises `NotImplementedError`
under uvicorn's default `SelectorEventLoop` on Windows.

## Demo approval flow

`/dashboard/demo` provides a form (issue key, summary, meeting-needed and
reject toggles) that submits to the same `DummyFlowService` used by the raw
`GET /demo/flow` endpoint. The form runs the **real** orchestrator against a
stub Jira client — no network calls are made, but every stage is logged at
`INFO` and persisted to the audit trail, exactly like a real ticket.

The raw endpoint:

| Query param | Default | Meaning |
|-------------|---------|---------|
| `issue_key` | `DEMO-1` | Issue key to simulate |
| `summary` | `Demo release ticket` | Summary stored on the record |
| `needs_meeting` | `false` | `true` → ends `meeting_scheduled`; `false` → `release_ready` |
| `reject` | `false` | `true` → SDL rejects and the flow stops |

Example:

```bash
curl "http://localhost:8000/demo/flow?needs_meeting=true&summary=My%20demo"
```

Response lists each step with its outcome. Then check the audit trail:

```bash
curl "http://localhost:8000/rab/records/DEMO-1"
```

or open `/dashboard/records`.

The `DummyFlowService` (in `app/services/dummy_flow.py`) reuses
`RabOrchestrator` with `StubJiraClient` injected. Two run modes:

- `run_full_approval(needs_meeting)` — validation → SDL approve → SDM approve →
  meeting decision.
- `run_rejection()` — validation → SDL reject → stop.

## Typical demo walkthrough

1. Start the server: `uvicorn app.main:app --reload`
2. Open `/dashboard/demo`, enter an issue key, and click **Run Flow** (or use
   `curl "http://localhost:8000/demo/flow?needs_meeting=false"`).
3. Watch the terminal — each stage is logged:
   - `Starting dummy RAB flow for DEMO-1`
   - `validation: approval_requested_sdl`
   - `sdl_approval: SDL approved — SDM approval requested`
   - `sdm_approval: All approvals complete`
   - `meeting_decision: release_ready`
4. Open `/dashboard/records` to see `DEMO-1` with `status=release_ready`,
   `sdl_approval=approved`, `sdm_approval=approved`; click through to the
   per-issue detail page to see the full approval timeline.
5. Try the reject path from the form or
   `curl "http://localhost:8000/demo/flow?reject=true"`.
