"""Tests for the health and root endpoints."""

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _set_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure required env vars are set for the test app."""
    monkeypatch.setenv("JIRA_WEBHOOK_URL", "http://testserver/webhooks/jira")
    monkeypatch.setenv("APP_ENV", "test")


@pytest.fixture()
def client() -> TestClient:
    """Create a fresh TestClient for each test."""
    # Import inside fixture so env vars from monkeypatch are active
    from app.main import create_app

    return TestClient(create_app())


class TestHealthEndpoint:
    """GET /health"""

    def test_returns_200(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.status_code == 200

    def test_response_contains_status_ok(self, client: TestClient) -> None:
        data = client.get("/health").json()
        assert data["status"] == "ok"

    def test_response_contains_service_name(self, client: TestClient) -> None:
        data = client.get("/health").json()
        assert data["service"] == "rab-automation"

    def test_response_contains_environment(self, client: TestClient) -> None:
        data = client.get("/health").json()
        assert data["environment"] == "test"


class TestRootEndpoint:
    """GET /"""

    def test_returns_200(self, client: TestClient) -> None:
        response = client.get("/")
        assert response.status_code == 200

    def test_response_contains_service_name(self, client: TestClient) -> None:
        data = client.get("/").json()
        assert data["service"] == "rab-automation"

    def test_response_contains_status_running(self, client: TestClient) -> None:
        data = client.get("/").json()
        assert data["status"] == "running"
