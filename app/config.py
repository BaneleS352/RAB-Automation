"""Application settings loaded from environment variables using pydantic-settings.

Optional integration with Azure Key Vault: when AZURE_VAULT_URL is set, secret
settings (JIRA_API_TOKEN, AZURE_DEVOPS_PAT, TEAMS_BOT_CLIENT_SECRET,
ACCESS_TOKEN) are resolved from the vault on first access and cached. Values
fall back to the corresponding environment variable when the vault is
unreachable or the Azure SDK is not installed.
"""

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.services.key_vault_client import KeyVaultClient, KeyVaultClientError

# Secret-bearing settings that may be resolved from Azure Key Vault.
_SECRET_FIELDS = ("JIRA_API_TOKEN", "AZURE_DEVOPS_PAT", "TEAMS_BOT_CLIENT_SECRET", "ACCESS_TOKEN")


class Settings(BaseSettings):
    """RAB Automation service configuration.

    Required settings will cause the app to fail on startup if missing.
    Optional settings are placeholders for future integration phases.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Core
    APP_NAME: str = "rab-automation"
    APP_ENV: str = "local"
    LOG_LEVEL: str = "INFO"
    DATABASE_PATH: str = ""

    # Optional shared secret protecting all HTTP endpoints. When set, every
    # request except /static must present it via `Authorization: Bearer`,
    # `X-API-Key`, the `?access_token=` query parameter (dashboard), or the
    # `rab_access_token` cookie. Empty (default) leaves the service open.
    ACCESS_TOKEN: str = ""

    # Optional: Azure Key Vault for secret resolution (see module docstring).
    AZURE_VAULT_URL: str = ""

    # Required: Jira webhook endpoint
    JIRA_WEBHOOK_URL: str

    # Jira API
    JIRA_BASE_URL: str | None = None
    JIRA_EMAIL: str | None = None
    JIRA_API_TOKEN: str | None = None

    # Jira project
    JIRA_PROJECT_KEY: str = ""

    # Custom field mappings (Jira custom field IDs or standard field names)
    JIRA_FIELD_PR_LINK: str = ""
    JIRA_FIELD_PIPELINE_LINK: str = ""
    JIRA_FIELD_RAB_APPROVER: str = ""
    JIRA_FIELD_DEVELOPER: str = ""
    JIRA_FIELD_TEAM_LEAD: str = ""
    JIRA_FIELD_PM: str = ""
    JIRA_FIELD_QA: str = ""
    JIRA_FIELD_ENVIRONMENT: str = ""
    JIRA_FIELD_ROLLBACK_DETAILS: str = ""
    JIRA_FIELD_DATE_TIME: str = ""

    # Workflow transition IDs
    JIRA_TRANSITION_VALIDATE: str = ""
    JIRA_TRANSITION_REQUEST_APPROVAL: str = ""
    JIRA_TRANSITION_APPROVE: str = ""
    JIRA_TRANSITION_REJECT: str = ""

    # Optional: Azure DevOps (future phases)
    AZURE_DEVOPS_ORG: str = ""
    AZURE_DEVOPS_PROJECT: str = ""
    AZURE_DEVOPS_REPO_ID: str = ""
    AZURE_DEVOPS_PAT: str | None = None
    AZURE_DEVOPS_API_VERSION: str = "7.1"

    # Optional: SharePoint (future phases)
    SHAREPOINT_SITE_ID: str | None = None
    SHAREPOINT_LIST_ID: str | None = None

    # Optional: Teams (future phases)
    TEAMS_TENANT_ID: str = ""
    TEAMS_BOT_APP_ID: str = ""
    TEAMS_BOT_CLIENT_SECRET: str = ""
    TEAMS_CHANNEL_ID: str = ""

    # Optional: Teams incoming webhook (no bot registration required).
    # TEAMS_WEBHOOK_URL is the connector URL; button presses are posted back
    # to TEAMS_CALLBACK_URL (a publicly reachable URL pointing at /webhooks/teams).
    TEAMS_WEBHOOK_URL: str = ""
    TEAMS_CALLBACK_URL: str = ""


@lru_cache(maxsize=None)
def _resolve_vault_secrets(vault_url: str) -> tuple[tuple[str, str], ...]:
    """Resolve secret settings from Key Vault (cached; empty-return on fallback)."""
    kv = KeyVaultClient(vault_url=vault_url)
    resolved: list[tuple[str, str]] = []
    for field in _SECRET_FIELDS:
        try:
            value = kv.get_secret(field)
        except KeyVaultClientError:
            value = os.environ.get(field, "")
        if value:
            resolved.append((field, value))
    return tuple(resolved)


def get_settings() -> Settings:
    """Return a Settings instance, overlaying env values with vault secrets when configured."""
    settings = Settings()
    if settings.AZURE_VAULT_URL:
        overrides = dict(_resolve_vault_secrets(settings.AZURE_VAULT_URL))
        if overrides:
            settings = settings.model_copy(update=overrides)
    return settings
