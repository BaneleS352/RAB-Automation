# Credentials Guide

Where every credential and configuration value used by RAB Automation comes
from, how to create it, and where to store it.

## Quick reference

| Variable | What it is | Secret? | Where to get it |
|----------|------------|---------|-----------------|
| `JIRA_WEBHOOK_URL` | Webhook delivery URL that Jira calls | No | Set in Jira project webhook config |
| `JIRA_BASE_URL` | Your Jira Cloud subdomain | No | e.g. `https://<company>.atlassian.net` |
| `JIRA_EMAIL` | Email on the API-token account | No | The account that owns the API token |
| `JIRA_API_TOKEN` | Atlassian API token | **Yes** | https://id.atlassian.com/manage-profile/security/api-tokens |
| `AZURE_DEVOPS_ORG` | Azure DevOps organization name | No | `dev.azure.com/<org>` |
| `AZURE_DEVOPS_PROJECT` | Azure DevOps project name | No | Inside your Azure DevOps org |
| `AZURE_DEVOPS_REPO_ID` | Repository ID for PR lookups | No | `dev.azure.com/<org>/<proj>/_apis/git/repositories` (API) |
| `AZURE_DEVOPS_PAT` | Azure DevOps Personal Access Token | **Yes** | `dev.azure.com` → user avatar → Personal Access Tokens |
| `TEAMS_WEBHOOK_URL` | Office 365 / Teams Incoming Webhook connector URL | **Yes** | Teams channel → Connectors → Incoming Webhook |
| `TEAMS_CALLBACK_URL` | Public HTTPS URL for card buttons | No | Your own publicly reachable endpoint (`/webhooks/teams`) |
| `TEAMS_TENANT_ID` | Entra ID (Azure AD) tenant ID | No | Azure Portal → Entra ID → Overview |
| `TEAMS_BOT_APP_ID` | Azure Bot application (client) ID | No | Azure Portal → App registration |
| `TEAMS_BOT_CLIENT_SECRET` | Azure Bot client secret | **Yes** | Azure Portal → App registration → Certificates & secrets |
| `TEAMS_CHANNEL_ID` | Target Teams channel/conversation ID for proactive messages | No | See "Find a channel ID" below |
| `ACCESS_TOKEN` | Shared secret guarding all HTTP routes | **Yes** | You generate this yourself |
| `AZURE_VAULT_URL` | Key Vault vault URI | No | Azure Portal → Key Vault → Overview → Vault URI |
| `SHAREPOINT_SITE_ID` / `SHAREPOINT_LIST_ID` | Reserved for future SharePoint integration | No | Not yet needed |

The following are **not credentials** but must be gathered from the same systems:

| Variable | Where to find it |
|----------|------------------|
| `JIRA_FIELD_*` (custom field IDs) | Jira → Project Settings → Fields → Custom fields (e.g. `customfield_12345`) |
| `JIRA_TRANSITION_*` (transition IDs) | Jira workflow admin → transition details, or via the Jira API |
| `JIRA_PROJECT_KEY` | Jira project key (e.g. `RAB`) |
| `AZURE_DEVOPS_API_VERSION` | Fixed default `7.1` — no setup |

---

## How to obtain each credential

### Jira Cloud

1. **`JIRA_BASE_URL`** — your instance URL, `https://<company>.atlassian.net`.
2. **`JIRA_EMAIL` + `JIRA_API_TOKEN`**
   1. Log in to the Atlassian account that runs the automation (a dedicated
      service account is recommended and must have Jira access).
   2. Open https://id.atlassian.com/manage-profile/security/api-tokens and click
      **Create API token**.
   3. Copy the token immediately — it is shown only once. Save it in your
      credential store / Key Vault as `JIRA_API_TOKEN`.
   4. Set `JIRA_EMAIL` to the email on that account.
3. **`JIRA_WEBHOOK_URL`** — the externally reachable URL of the service, e.g.
   `https://rab.mycompany.com/webhooks/jira`. Configure it in Jira →
   **Project Settings → Webhooks** (see [setup.md](setup.md) → "Point Jira at
   the webhook").

### Jira field & transition IDs (not secrets)

- **Custom field IDs**: Jira → Project Settings → Fields. Open a custom field to
  see its numeric ID (`customfield_12345`). Standard fields like `assignee` and
  `reporter` are used as-is.
- **Transition IDs**: Jira Settings → Workflows, or use the Jira API:
  `GET /rest/api/3/issue/{key}/transitions` to inspect the IDs for validate /
  request-approval / approve / reject transitions.

### Azure DevOps

1. **`AZURE_DEVOPS_ORG`** — the first path segment of `https://dev.azure.com/<org>`.
2. **`AZURE_DEVOPS_PROJECT`** — the project name inside that org.
3. **`AZURE_DEVOPS_REPO_ID`** — repository GUID. Find it under
   Project → Repos → your repo → Settings → General → Repository ID, or via
   `GET /_apis/git/repositories`.
4. **`AZURE_DEVOPS_PAT`** — in `dev.azure.com`, click your avatar → **Personal
   Access Tokens** → **+ New Token**:
   - Give it a name and expiry that matches your rotation policy.
   - Scope: at minimum **Code (read)**; grant **Build (read)** too if pipeline
     status is fetched.
   - Copy and store it as `AZURE_DEVOPS_PAT`.

### Microsoft Teams

Choose **one** delivery mode (the service auto-detects via `TEAMS_WEBHOOK_URL`):

**Option A — Incoming webhook (simplest, no bot)**
1. In the target Teams channel, open **… → Connectors → Incoming Webhook → Add**.
2. Create a webhook and copy the generated connector URL into `TEAMS_WEBHOOK_URL`.
3. Treat this URL as a secret — anyone holding it can post to the channel.
4. Set `TEAMS_CALLBACK_URL` to your public HTTPS path that reaches
   `/webhooks/teams` (used as the click target for adaptive-card buttons).

**Option B — Azure Bot / Bot Framework**
1. **`TEAMS_TENANT_ID`** — Azure Portal → **Microsoft Entra ID** → Overview →
   Tenant ID.
2. **`TEAMS_BOT_APP_ID`** — create an **App registration** (or a Bot in the
   Azure AI / Bot Framework area) and copy the **Application (client) ID**.
3. **`TEAMS_BOT_CLIENT_SECRET`** — in that app registration → **Certificates &
   secrets → New client secret**. Copy the value once and store it as
   `TEAMS_BOT_CLIENT_SECRET`.
4. **`TEAMS_CHANNEL_ID`** — the conversation/channel ID the bot posts to. Easiest
   to obtain from an outgoing test message or from your channel settings. See
   "Find a channel ID" below.

**Find a channel ID**
- The message payload received at `/webhooks/teams` includes `conversation.id`
  — log an inbound payload once and read the ID from it.
- Or, in Teams desktop, copy the channel link: the last path segment of
  `https://teams.microsoft.com/l/channel/<encoded-id>/...` is the encoded
  conversation ID (you may need to decode it).

### Access token (guards the app)

- **`ACCESS_TOKEN`** — you generate this. Use something long and random:
  ```bash
  python -c "import secrets; print(secrets.token_urlsafe(48))"
  ```
  When set, every route (except `/static`) requires it via `Authorization: Bearer`,
  `X-API-Key`, the `?access_token=` query param, or the `rab_access_token`
  cookie. Empty means **open by default** — set it in production.

### Azure Key Vault

1. Create a Key Vault in Azure Portal → **Key vaults → Create**.
2. Copy the **Vault URI** (e.g. `https://rab.vault.azure.net/`) into
   `AZURE_VAULT_URL`.
3. Add secrets named exactly as the settings, e.g.:
   `JIRA_API_TOKEN`, `AZURE_DEVOPS_PAT`, `TEAMS_BOT_CLIENT_SECRET`, `ACCESS_TOKEN`.
4. Give the app's identity access: in the vault → **Access policies → Add**, or
   via IAM (RBAC) grant the **Key Vault Secrets User** role to the service
   principal / managed identity the app runs as. The app authenticates through
   `DefaultAzureCredential` (required packages: `azure-identity`,
   `azure-keyvault-secrets`).
5. When `AZURE_VAULT_URL` is set, the vault values **override** the environment
   variables for those four settings; if the vault is unreachable it falls back
   to env vars.

---

## Which values are treated as secrets

Store these **only** in your secret manager (Key Vault in production), never in
source control or logs:

- `JIRA_API_TOKEN`
- `AZURE_DEVOPS_PAT`
- `TEAMS_BOT_CLIENT_SECRET`
- `TEAMS_WEBHOOK_URL`
- `ACCESS_TOKEN`

`TEAMS_WEBHOOK_URL` is not a password but is credential-like: anyone who has it
can post to your channel.

The Key Vault overlay only ever resolves these five secret-flagged settings; the
rest remain plain environment variables.

## Rotation

Rotate every secret on a schedule and update the store (Key Vault / env) +
restart the service (configuration is read at startup):

- `JIRA_API_TOKEN` — every 90 days (best practice for Atlassian)
- `AZURE_DEVOPS_PAT` — set a short expiry (e.g. 30–90 days) when creating it
- `TEAMS_BOT_CLIENT_SECRET` — per your Entra app secret policy
- `ACCESS_TOKEN` — whenever a holder changes or on suspected leak

If `TEAMS_WEBHOOK_URL` leaks, delete/recreate the connector in Teams and update
the env/server config.