# Data & Audit Trail

## Database engine

The service uses **SQLite** through the async `aiosqlite` driver. The default
file is `rab_automation.db` in the project root; override with `DATABASE_PATH`.

Connection management lives in `app/database.py`:

- `get_db()` — opens (lazily) and returns a shared async connection
- `init_db()` — creates tables + indexes (`CREATE TABLE IF NOT EXISTS`)
- `close_db()` — closes the connection (called on shutdown and at the end of
  test sessions)

## Schema

### `rab_records`

One row per Jira issue, updated through its lifecycle.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | Auto-increment |
| `issue_key` | TEXT NOT NULL | e.g. `PROJ-123` |
| `summary` | TEXT | Issue summary |
| `status` | TEXT NOT NULL | See status values below |
| `validation_result` | TEXT | Pass/fail detail from the validator |
| `sdl_approval` | TEXT | `pending` / `requested` / `approved` / `rejected` |
| `sdm_approval` | TEXT | `pending` / `requested` / `approved` / `rejected` |
| `rejection_reason` | TEXT | Reason when rejected |
| `rejected_by` | TEXT | Who rejected (step name) |
| `meeting_needed` | INTEGER | `0` or `1` |
| `sdl_approval_id` | TEXT | SDL approval correlation ID (uuid) |
| `sdm_approval_id` | TEXT | SDM approval correlation ID (uuid) |
| `created_at` | TEXT NOT NULL | ISO timestamp |
| `updated_at` | TEXT NOT NULL | ISO timestamp |

**Status values:**

| Value | Meaning |
|-------|---------|
| `pending` | Initial state |
| `validated` | Validation passed (all 12 RAB fields present) |
| `validated_with_notes` | Advisory: GET and NOTE — workflow continues but some RAB fields missing (detail in `validation_result`, e.g. `RAB audit — Present 2/12…`); set when `RAB_STRICT_VALIDATION=false` (default per `data structure.drawio.html`) |
| `validation_failed` | Validation failed (strict mode `RAB_STRICT_VALIDATION=true` only) |
| `sdl_approved` / `sdl_rejected` | SDL decision recorded |
| `sdm_approved` / `sdm_rejected` | SDM decision recorded |
| `meeting_scheduled` | Meeting required after approvals |
| `release_ready` | No meeting needed; ready to deploy |

### `approval_events`

Append-only event log of every approval decision.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | Auto-increment |
| `issue_key` | TEXT NOT NULL | |
| `step` | TEXT NOT NULL | `SDL` or `SDM` |
| `action` | TEXT NOT NULL | `approve` or `reject` |
| `approver` | TEXT | Approver name |
| `reason` | TEXT | Reason (required for reject) |
| `created_at` | TEXT NOT NULL | ISO timestamp |

### `webhook_events`

Deduplication ledger for idempotency.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | Auto-increment |
| `event_id` | TEXT UNIQUE NOT NULL | From `X-Idempotency-Key` (or generated) |
| `issue_key` | TEXT NOT NULL | |
| `event_type` | TEXT | e.g. `jira:issue_created` |
| `status` | TEXT NOT NULL | `received` by default |
| `created_at` | TEXT NOT NULL | ISO timestamp |

### Indexes

- `idx_rab_issue` on `rab_records(issue_key)`
- `idx_approval_issue` on `approval_events(issue_key)`
- `idx_webhook_event_id` on `webhook_events(event_id)`

## How the lifecycle maps to rows

Using `GET /demo/flow` as a working example (`DEMO-1`):

1. **Validation** — `upsert_record` inserts with `status=validated`,
   `validation_result="All required fields are present."`
2. **SDL requested** — `sdl_approval=requested`
3. **SDL approved** — `record_approval_event` appends one `approval_events` row
   (`step=SDL, action=approve`) and sets `sdl_approval=approved`,
   `status=sdl_approved`
4. **SDM approved** — same for SDM; `status=sdm_approved`
5. **Meeting decision** — `meeting_needed=1|0`,
   `status=meeting_scheduled|release_ready`

The `updated_at` timestamp refreshes on every write.

## Querying the audit trail

From the API:

```bash
curl "http://localhost:8000/rab/records?limit=10&offset=0"
curl "http://localhost:8000/rab/records/DEMO-1"
```

From the dashboard: `http://localhost:8000/dashboard/records`.

## Isolation between tests and the live app

`tests/conftest.py` sets `DATABASE_PATH` to a **fresh unique temp file**
(`rab_pytest_<uuid>.db`) for every session, so the test suite never touches the
live `rab_automation.db` and each run starts from a clean slate. The
dashboard's "Run Tests" button does the same via the test runner.
