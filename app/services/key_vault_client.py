"""Azure Key Vault client for secret resolution."""

import logging
import os

logger = logging.getLogger(__name__)


class KeyVaultClientError(Exception):
    """Raised when Key Vault operations fail."""


class KeyVaultClient:
    """Lightweight Azure Key Vault wrapper.

    Falls back to environment variables when Key Vault is not configured,
    making it safe to use in development without Azure.
    """

    def __init__(self, vault_url: str | None = None) -> None:
        self.vault_url = vault_url
        self._use_key_vault = bool(vault_url)
        if self._use_key_vault:
            logger.debug("Key Vault configured: %s", vault_url)
        else:
            logger.debug("Key Vault not configured — using env vars")

    def get_secret(self, secret_name: str) -> str:
        """Retrieve a secret. Falls back to environment variable."""
        if not self._use_key_vault:
            value = os.environ.get(secret_name, "")
            if not value:
                raise KeyVaultClientError("Secret not found in environment")
            return value

        try:
            from azure.identity import DefaultAzureCredential
            from azure.keyvault.secrets import SecretClient

            credential = DefaultAzureCredential()
            client = SecretClient(vault_url=self.vault_url, credential=credential)
            secret = client.get_secret(secret_name)
            return secret.value
        except ImportError:
            logger.warning("Azure SDK packages not installed, falling back to env")
            value = os.environ.get(secret_name, "")
            if not value:
                raise KeyVaultClientError("Secret not found in env or Key Vault")
            return value
        except Exception as e:
            # Key Vault is an optional override. A transient outage or missing
            # local credential must not prevent env-based development startup.
            logger.warning("Key Vault lookup failed for '%s'; using environment fallback", secret_name)
            value = os.environ.get(secret_name, "")
            if value:
                return value
            raise KeyVaultClientError("Secret not found in env or Key Vault") from e

    def is_configured(self) -> bool:
        return self._use_key_vault
