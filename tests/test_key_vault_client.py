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
