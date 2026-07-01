# RAB Automation Service

Lightweight Jira RAB automation webhook service built with FastAPI.

## Overview

This service receives Jira webhook events, validates them against a shared secret, extracts the issue key, and delegates processing to an orchestration layer. Currently in **Phase 1** — the orchestrator is a stub returning `"queued_for_processing"`.

## Project Structure

```
rab-automation/
  app/
    main.py              # FastAPI entry point
    config.py            # pydantic-settings configuration
    logging_config.py    # Logging setup
    exceptions.py        # Custom HTTP exceptions
    api/
      health.py          # GET / and GET /health
      webhooks.py        # POST /webhooks/jira
      routes.py          # Router aggregation
    models/
      webhook.py         # Jira webhook payload models
      responses.py       # API response models
    services/
      rab_orchestrator.py  # Orchestration stub
  tests/
    test_health.py
    test_jira_webhook.py
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

The only **required** variable for this phase is `JIRA_WEBHOOK_SHARED_SECRET`.

### 3. Run locally

```bash
uvicorn app.main:app --reload
```

The service starts at `http://localhost:8000`.

## Endpoints

### Health check

```bash
curl http://localhost:8000/health
```

Response:

```json
{"status": "ok", "service": "rab-automation", "environment": "local"}
```

### Root

```bash
curl http://localhost:8000/
```

Response:

```json
{"service": "rab-automation", "status": "running"}
```

### Jira webhook

```bash
curl -X POST http://localhost:8000/webhooks/jira \
  -H "Content-Type: application/json" \
  -H "X-RAB-Automation-Secret: your-secret-here" \
  -d '{
    "webhookEvent": "jira:issue_created",
    "issue": {
      "key": "ABC-123"
    }
  }'
```

Response:

```json
{
  "status": "accepted",
  "issue_key": "ABC-123",
  "event_type": "jira:issue_created",
  "result": "queued_for_processing"
}
```

## Running Tests

```bash
pytest
```

Tests use monkeypatched environment variables — no `.env` file required.

## Next Phase

- **Phase 2**: Jira API integration — fetch issue details, parse PR links
- **Phase 3**: Azure DevOps integration — read PR diffs
- **Phase 4**: SharePoint integration — write RAB entries
- **Phase 5**: Power Automate / Teams notifications
