"""Application settings loaded from environment variables using pydantic-settings.

Optional integration with Azure Key Vault: when AZURE_VAULT_URL is set, secret
settings (JIRA_API_TOKEN, ACCESS_TOKEN) are resolved from the vault on first
access and cached. Values fall back to the corresponding environment variable
when the vault is unreachable or the Azure SDK is not installed.
"""

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.services.key_vault_client import KeyVaultClient, KeyVaultClientError

# Secret-bearing settings that may be resolved from Azure Key Vault.
_SECRET_FIELDS = ("JIRA_API_TOKEN", "ACCESS_TOKEN")


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
    ENABLE_DEMO: bool | None = None
    ENABLE_TEST_UI: bool | None = None

    # Optional: Azure Key Vault for secret resolution (see module docstring).
    AZURE_VAULT_URL: str = ""

    # Required: Jira webhook endpoint — defaults to localhost for tests/dev so import doesn't crash when .env missing
    JIRA_WEBHOOK_URL: str = "http://localhost:8000/webhooks/jira"

    # Jira API
    JIRA_BASE_URL: str | None = None
    JIRA_EMAIL: str | None = None
    JIRA_API_TOKEN: str | None = None

    # Jira project
    JIRA_PROJECT_KEY: str = ""

    # Custom field mappings (Jira custom field IDs or standard field names)
    # When empty, the validator now falls back to parsing the Jira description text (RAB block) and the standard 'environment' field — fixes blank-details without requiring customfields
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

    # Advisory vs strict validation: when False (default, per data structure.drawio.html),
    # we GET the ticket and NOTE which of the 12 RAB fields are present/missing, but do not
    # block the workflow. When True, missing fields cause validation_failed and halt.
    RAB_STRICT_VALIDATION: bool = False

    # Teams alerting (power-automate workflow webhook) — alerting basis only, final release state.
    # Re-uses the proven pattern from scripts/send_to_teams.py (TEAMS_WORKFLOW_WEBHOOK_URL).
    TEAMS_WORKFLOW_WEBHOOK_URL: str = ""
    # Back-compat alias for the older incoming-webhook variable name
    TEAMS_WEBHOOK_URL: str = ""

    @property
    def effective_teams_webhook_url(self) -> str:
        """Single source for Teams webhook — prefers workflow URL, falls back to legacy."""
        return (self.TEAMS_WORKFLOW_WEBHOOK_URL or self.TEAMS_WEBHOOK_URL).strip()

    def feature_enabled(self, value: bool | None) -> bool:
        """Enable local-only features by default, require explicit prod opt-in."""
        return value if value is not None else self.APP_ENV.lower() in {"local", "test", "development"}

    


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
    # Not cached — tests use monkeypatch to change env per-test and expect fresh Settings.
    # Vault resolution is still cached via _resolve_vault_secrets.
    settings = Settings()
    if settings.AZURE_VAULT_URL:
        overrides = dict(_resolve_vault_secrets(settings.AZURE_VAULT_URL))
        if overrides:
            settings = settings.model_copy(update=overrides)
    return settings
