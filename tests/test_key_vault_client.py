"""Tests for the Azure Key Vault client."""

import os

import pytest

from app.services.key_vault_client import KeyVaultClient, KeyVaultClientError


class TestKeyVaultClient:
    def test_not_configured_by_default(self) -> None:
        client = KeyVaultClient()
        assert client.is_configured() is False

    def test_configured_with_url(self) -> None:
        client = KeyVaultClient("https://myvault.vault.azure.net")
        assert client.is_configured() is True

    def test_get_secret_from_env(self) -> None:
        os.environ["TEST_SECRET"] = "my-test-value"
        client = KeyVaultClient()
        value = client.get_secret("TEST_SECRET")
        assert value == "my-test-value"

    def test_get_secret_raises_when_missing(self) -> None:
        if "MISSING_SECRET" in os.environ:
            del os.environ["MISSING_SECRET"]
        client = KeyVaultClient()
        with pytest.raises(KeyVaultClientError, match="not found in env"):
            client.get_secret("MISSING_SECRET")

    def test_get_secret_empty_env_raises(self) -> None:
        os.environ["EMPTY_SECRET"] = ""
        client = KeyVaultClient()
        with pytest.raises(KeyVaultClientError):
            client.get_secret("EMPTY_SECRET")

    def test_fallback_on_import_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        os.environ["FALLBACK_SECRET"] = "fallback-value"
        client = KeyVaultClient("https://myvault.vault.azure.net")
        value = client.get_secret("FALLBACK_SECRET")
        assert value == "fallback-value"


class TestKeyVaultConfigWiring:
    def test_settings_ignore_vault_when_not_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AZURE_VAULT_URL", "")
        monkeypatch.setenv("JIRA_API_TOKEN", "env-token")
        from app.config import get_settings
        assert get_settings().JIRA_API_TOKEN == "env-token"

    def test_settings_resolve_secrets_from_vault(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.config import _resolve_vault_secrets, get_settings

        _resolve_vault_secrets.cache_clear()
        monkeypatch.setenv("AZURE_VAULT_URL", "https://myvault.vault.azure.net")
        monkeypatch.setenv("JIRA_API_TOKEN", "env-token")
        monkeypatch.setenv("AZURE_DEVOPS_PAT", "env-pat")

        vault_values = {"JIRA_API_TOKEN": "vault-token", "TEAMS_BOT_CLIENT_SECRET": "vault-secret"}

        def fake_get_secret(self, secret_name: str) -> str:
            if secret_name in vault_values:
                return vault_values[secret_name]
            raise KeyVaultClientError(f"Secret not found: {secret_name}")

        monkeypatch.setattr(KeyVaultClient, "get_secret", fake_get_secret)

        settings = get_settings()
        assert settings.JIRA_API_TOKEN == "vault-token"
        assert settings.TEAMS_BOT_CLIENT_SECRET == "vault-secret"
        # Missing in vault → environment fallback
        assert settings.AZURE_DEVOPS_PAT == "env-pat"
        assert settings.AZURE_VAULT_URL == "https://myvault.vault.azure.net"
