"""Application settings loaded from environment variables using pydantic-settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # ── Core ──────────────────────────────────────────────────────────
    APP_NAME: str = "rab-automation"
    APP_ENV: str = "local"
    LOG_LEVEL: str = "INFO"

    # ── Required: Webhook security ────────────────────────────────────
    JIRA_WEBHOOK_SHARED_SECRET: str

    # ── Optional: Jira API (future phases) ────────────────────────────
    JIRA_BASE_URL: str | None = None
    JIRA_EMAIL: str | None = None
    JIRA_API_TOKEN: str | None = None

    # ── Optional: Azure DevOps (future phases) ────────────────────────
    AZURE_DEVOPS_PAT: str | None = None

    # ── Optional: SharePoint (future phases) ──────────────────────────
    SHAREPOINT_SITE_ID: str | None = None
    SHAREPOINT_LIST_ID: str | None = None


def get_settings() -> Settings:
    """Return a cached Settings instance (pydantic-settings handles caching)."""
    return Settings()
