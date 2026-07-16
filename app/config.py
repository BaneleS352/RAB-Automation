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

    # Core
    APP_NAME: str = "rab-automation"
    APP_ENV: str = "local"
    LOG_LEVEL: str = "INFO"

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

    # Optional: SharePoint (future phases)
    SHAREPOINT_SITE_ID: str | None = None
    SHAREPOINT_LIST_ID: str | None = None

    # Optional: Teams (future phases)
    TEAMS_TENANT_ID: str = ""
    TEAMS_BOT_APP_ID: str = ""
    TEAMS_BOT_CLIENT_SECRET: str = ""
    TEAMS_CHANNEL_ID: str = ""


def get_settings() -> Settings:
    """Return a Settings instance."""
    return Settings()
