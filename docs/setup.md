# Setup & Configuration

## Requirements

- **Python 3.11+** (project targets ≥ 3.11; developed and tested on 3.12)
- **pip** for dependency installation
- A **Jira Cloud instance** (required for the real webhook flow)
- Optional: Azure DevOps, Azure Bot Service / Teams, Azure Key Vault

## 1. Install dependencies

```bash
pip install -r requirements.txt
```

`requirements.txt` contains:

- `fastapi` — web framework
- `uvicorn[standard]` — ASGI server
- `pydantic-settings` — environment-driven configuration
- `aiosqlite` — async SQLite driver
- `httpx` — async HTTP client for Jira / Azure / Teams
- `jinja2` — HTML dashboard templates
- `python-multipart` — form parsing (Bot Framework activities)
- Test deps: `pytest`, `pytest-asyncio`, `httpx` (TestClient)

## 2. Environment variables

Copy the example file and fill in your values. For step-by-step instructions
on creating each credential (Atlassian API tokens, Azure DevOps PATs, Teams
webhooks/bot secrets, Key Vault secrets), see the
[Credentials Guide](credentials.md):

```bash
cp .env.example .env
```

On Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

### Required

| Variable | Purpose |
|----------|---------|
| `JIRA_WEBHOOK_URL` | The URL you configure in Jira for webhook delivery, e.g. `https://your-host/webhooks/jira` |

This is the **only strictly required** variable. Without it the app refuses to
start. All other settings are optional — unconfigured integrations simply report
"not connected" on `/health` and the dashboard.

### Core

| Variable | Default | Purpose |
|----------|---------|---------|
| `APP_NAME` | `rab-automation` | Service name used in health responses |
| `APP_ENV` | `local` | Environment label (`local`, `test`, `prod`) |
| `LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `DATABASE_PATH` | `rab_automation.db` | Override the SQLite file location |

### Jira API (needed for the full workflow)

| Variable | Purpose |
|----------|---------|
| `JIRA_BASE_URL` | e.g. `https://yourcompany.atlassian.net` |
| `JIRA_EMAIL` | The email on the API token account |
| `JIRA_API_TOKEN` | An [Atlassian API token](https://id.atlassian.com/manage-profile/security/api-tokens) |
| `JIRA_PROJECT_KEY` | Target project key (informational) |

### Jira custom field mappings

Map the logical RAB field names to the Jira field keys (standard names like
`assignee`/`reporter`, or `customfield_12345`):

| Variable | RAB field |
|----------|-----------|
| `JIRA_FIELD_PR_LINK` | PR Link |
| `JIRA_FIELD_PIPELINE_LINK` | Pipeline Link |
| `JIRA_FIELD_RAB_APPROVER` | RAB Approver |
| `JIRA_FIELD_DEVELOPER` | Developer |
| `JIRA_FIELD_TEAM_LEAD` | Team Lead |
| `JIRA_FIELD_PM` | PM |
| `JIRA_FIELD_QA` | QA |
| `JIRA_FIELD_ENVIRONMENT` | Environment |
| `JIRA_FIELD_ROLLBACK_DETAILS` | Rollback/Mitigation Details |
| `JIRA_FIELD_DATE_TIME` | Date/Time |

### Jira workflow transitions

| Variable | Purpose |
|----------|---------|
| `JIRA_TRANSITION_VALIDATE` | Transition ID for validation |
| `JIRA_TRANSITION_REQUEST_APPROVAL` | Transition ID to request approval |
| `JIRA_TRANSITION_APPROVE` | Transition ID to approve |
| `JIRA_TRANSITION_REJECT` | Transition ID to reject |

### Azure DevOps (optional)

| Variable | Purpose |
|----------|---------|
| `AZURE_DEVOPS_ORG` | Organization name |
| `AZURE_DEVOPS_PROJECT` | Project name |
| `AZURE_DEVOPS_REPO_ID` | Repository ID for PR lookups |
| `AZURE_DEVOPS_PAT` | Personal Access Token |
| `AZURE_DEVOPS_API_VERSION` | REST API version (default `7.1`) |

### Teams (optional — two modes)

The service uses the **incoming webhook** mode automatically when `TEAMS_WEBHOOK_URL`
is set; otherwise it falls back to the Azure Bot mode.

**Option A — incoming webhook** (no app registration, no premium license):

| Variable | Purpose |
|----------|---------|
| `TEAMS_WEBHOOK_URL` | Connector URL from a Teams channel's Incoming Webhook connector |
| `TEAMS_CALLBACK_URL` | Public URL pointing at `/webhooks/teams`, used as the `HttpPOST` target for card buttons |

**Option B — Azure Bot** (full interactive adaptive cards with reason input):

| Variable | Purpose |
|----------|---------|
| `TEAMS_TENANT_ID` | Microsoft tenant ID |
| `TEAMS_BOT_APP_ID` | Azure Bot application (client) ID |
| `TEAMS_BOT_CLIENT_SECRET` | Azure Bot client secret |
| `TEAMS_CHANNEL_ID` | Target channel/conversation for proactive messages |

### SharePoint (reserved)

| Variable | Purpose |
|----------|---------|
| `SHAREPOINT_SITE_ID` | Reserved for future SharePoint integration |
| `SHAREPOINT_LIST_ID` | Reserved for future SharePoint integration |

### Azure Key Vault

Key Vault is optional. If `KeyVaultClient` is constructed with a `vault_url`,
it attempts to resolve secrets from Azure; otherwise (and as a fallback) it reads
plain environment variables. Error messages never expose secret names, and the
vault URL is logged at `DEBUG` level only.

## 3. Run locally

```bash
uvicorn app.main:app --reload
```

The service starts at `http://localhost:8000`.

- Dashboard: `http://localhost:8000/dashboard/health`
- API docs (OpenAPI/Swagger): `http://localhost:8000/docs`
- Raw OpenAPI JSON: `http://localhost:8000/openapi.json`

## 4. Point Jira at the webhook

1. Jira → **Project Settings → Webhooks**.
2. Add a webhook to `POST /webhooks/jira` with your public URL.
3. Select the events you want (e.g., `jira:issue_created`).
4. Optionally set a custom header `X-Idempotency-Key` (Jira cannot set custom
   headers natively — retries typically arrive with the same event payload, and
   dedup is keyed on that header when present).

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| App won't start | `JIRA_WEBHOOK_URL` is missing — set it in `.env` or export it |
| Health shows Jira disconnected | Check `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN` |
| `PermissionError` on the SQLite DB | A leftover process holds the file — stop the old uvicorn/python |
| `NotImplementedError` for subprocess | Known Windows event-loop limitation — the test runner uses `subprocess.run` via a thread instead |
