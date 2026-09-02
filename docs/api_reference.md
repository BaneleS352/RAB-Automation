# API Reference

Base URL: `http://localhost:8000` (default). Interactive docs: `/docs`.

All JSON responses use UTF-8. Webhook endpoints accept `application/json`.

---

## Dashboard (HTML)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Redirect to `/dashboard/health` |
| GET | `/dashboard/health` | HTML: connection status for Jira, Azure DevOps, Teams |
| GET | `/dashboard/records` | HTML: audit-trail table of processed issues |
| GET | `/dashboard/test` | HTML: runs the full pytest suite and shows results |

---

## Health & Metrics

### `GET /health`

Returns service status plus per-integration connectivity.

```json
{
  "status": "ok",
  "service": "rab-automation",
  "environment": "local",
  "jira": { "connected": true, "details": "Jira API is reachable and authenticated." }
}
```

`connected` is a boolean; `details` explains the current state. When `JIRA_FIELD_*`/`JIRA_PROJECT_KEY`/`JIRA_TRANSITION_*` are empty, `details` appends `Config warnings: ...` (same silent no-op class as the former blank-details bug — now surfaced).

### `GET /metrics`

Prometheus-style operational counters:

| Field | Description |
|-------|-------------|
| `uptime_seconds` | Seconds since the worker started |
| `requests_total` | Total HTTP requests through the middleware |
| `requests_failed` | Requests that raised an exception |
| `avg_duration_ms` | Average request duration (milliseconds) |
| `queue_pending` | Tasks waiting in the async queue |
| `queue_tasks_completed` | Tasks that completed successfully |
| `queue_tasks_failed` | Tasks that failed |

---

## Webhooks

### `POST /webhooks/jira`

Receives Jira events and drives the RAB workflow.

**Headers:**
- `Content-Type: application/json`
- `X-Idempotency-Key` (optional) — deduplicates retries

**Request body:**

```json
{
  "webhookEvent": "jira:issue_created",
  "issue": { "key": "PROJ-123" }
}
```

The payload model allows extra fields (Jira sends many). The issue key is
validated against `^[A-Z][A-Z0-9_]+-\d+$`.

**Responses:**

| Code | Scenario |
|------|----------|
| 200 | Accepted; orchestration result returned |
| 400 | Missing issue key (`MissingIssueKeyError`) |
| 422 | Malformed JSON / invalid issue key format |

**Success response:**

```json
{
  "status": "accepted",
  "issue_key": "PROJ-123",
  "event_type": "jira:issue_created",
  "result": "approval_requested_sdl",
  "idempotent_replay": false
}
```

`result` values include: `approval_requested_sdl`, `validation_failed: <detail>`,
`error_fetching_issue_data`.

**Idempotent replay** — when `X-Idempotency-Key` is supplied and the event was
already processed, the response is `idempotent_replay: true` and `result` is the
cached record status.

### `POST /webhooks/teams`

Receives Bot Framework activities (adaptive-card clicks) **or** MessageCard
`HttpPOST` callbacks from an incoming webhook.

**Request body** (activity envelope):

```json
{
  "type": "message",
  "value": {
    "action": "approve",
    "approval_id": "uuid",
    "issue_key": "PROJ-123",
    "reason": "Optional reason"
  },
  "from": { "name": "Jane Doe" }
}
```

In webhook mode the button payload is POSTed directly (raw JSON or
form-url-encoded), without the activity envelope:

```json
{ "action": "approve", "approval_id": "uuid", "issue_key": "PROJ-123" }
```

Supported `value.action` values:

| Action | Orchestrator call |
|--------|-------------------|
| `approve` | `handle_approval_callback(issue_key, "approve", approver, reason)` |
| `reject` | `handle_approval_callback(issue_key, "reject", approver, reason)` |
| `meeting_yes` | `handle_meeting_callback(issue_key, needs_meeting=True)` |
| `meeting_no` | `handle_meeting_callback(issue_key, needs_meeting=False)` |

`conversationUpdate` activities register the sender so the bot can send
proactive messages back to the channel.

---

## RAB Audit Trail (JSON)

### `GET /rab/records`

List audit records, most recently updated first.

**Query params:**
- `limit` — default `50`, min `1`, max `200`
- `offset` — default `0`
- `status` — exact status filter (e.g. `sdl_requested`, `release_ready`)
- `q` — issue-key substring search

**Response:**

```json
{
  "total": 1,
  "records": [
    {
      "id": 1,
      "issue_key": "PROJ-123",
      "summary": "Deploy new feature",
      "status": "release_ready",
      "validation_result": "All required fields are present.",
      "sdl_approval": "approved",
      "sdm_approval": "approved",
      "rejection_reason": "",
      "rejected_by": "",
      "meeting_needed": 0,
      "created_at": "2026-08-07T09:00:00+00:00",
      "updated_at": "2026-08-07T09:05:00+00:00"
    }
  ]
}
```

### `GET /rab/records/{issue_key}`

Return the audit record for one issue, or `null` if not found.

```json
{
  "id": 1,
  "issue_key": "PROJ-123",
  "status": "release_ready",
  "sdl_approval": "approved",
  "sdm_approval": "approved",
  "meeting_needed": 0
}
```

### `GET /rab/records/{issue_key}/events`

Return the approval-event timeline for one issue (`approval_events` rows in
chronological order).

```json
[
  {
    "id": 1,
    "issue_key": "PROJ-123",
    "step": "SDL",
    "action": "approve",
    "approver": "Jane Doe",
    "reason": "Looks good",
    "created_at": "2026-08-07T09:02:00+00:00"
  }
]
```

### `GET /rab/webhook-events`

List webhook deliveries recorded in `webhook_events`, newest first.

**Query params:** `limit` (default `50`, max `200`), `offset` (default `0`).

```json
{
  "total": 1,
  "events": [
    {
      "id": 1,
      "event_id": "event-12345",
      "issue_key": "PROJ-123",
      "event_type": "jira:issue_created",
      "status": "received",
      "created_at": "2026-08-07T09:00:00+00:00"
    }
  ]
}
```

### `GET /rab/summary`

Pipeline status counts and aging approvals, used by the dashboard overview.

**Query params:** `aging_days` — tickets waiting on approval longer than this
(default `2`).

```json
{
  "total": 5,
  "counts": { "release_ready": 3, "sdl_requested": 2 },
  "pending_approval": 2,
  "validation_failed": 0,
  "rejected": 0,
  "release_ready": 3,
  "meeting_scheduled": 0,
  "aging": []
}
```

---

## Demo / Dummy Flow

### `GET /demo/flow`

Creates a live Jira ticket and runs the RAB workflow against it, producing real
`INFO` logs and audit records.

**Query params:**

| Param | Default | Purpose |
|-------|---------|---------|
| `issue_key` | `DEMO-1` | Issue key to simulate |
| `summary` | `Demo release ticket` | Summary stored on the record |
| `needs_meeting` | `false` | End with meeting scheduled vs release-ready |
| `reject` | `false` | Run the rejection path (SDL rejects) instead |

**Response:**

```json
{
  "issue_key": "DEMO-1",
  "status": "ok",
  "steps": [
    { "step": "validation", "detail": "approval_requested_sdl" },
    { "step": "sdl_approval", "detail": "SDL approved — SDM approval requested" },
    { "step": "sdm_approval", "detail": "All approvals complete" },
    { "step": "meeting_decision", "detail": "release_ready" }
  ]
}
```

After running it, inspect `GET /rab/records/{issue_key}` or
`/dashboard/records` to see the persisted lifecycle.
