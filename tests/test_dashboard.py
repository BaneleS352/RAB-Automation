"""Tests for the HTML dashboard views."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _set_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_WEBHOOK_URL", "http://testserver/webhooks/jira")
    monkeypatch.setenv("APP_ENV", "test")


@pytest.fixture(autouse=True)
def _mock_connections(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.jira_client import JiraClient
    from app.services.azure_devops_client import AzureDevOpsClient
    from app.services.teams_client import TeamsClient

    async def mock_check(self):
        return {"connected": True, "details": "Mock connection OK"}
    monkeypatch.setattr(JiraClient, "check_connection", mock_check)
    monkeypatch.setattr(AzureDevOpsClient, "check_connection", mock_check)
    monkeypatch.setattr(TeamsClient, "check_connection", mock_check)


@pytest.fixture()
def client() -> TestClient:
    from app.main import create_app
    return TestClient(create_app())


class TestDashboardHealth:
    def test_returns_html(self, client: TestClient) -> None:
        response = client.get("/dashboard/health")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")

    def test_contains_health_cards(self, client: TestClient) -> None:
        body = client.get("/dashboard/health").text
        assert "health-card" in body
        assert "jira" in body.lower()
        assert "azure_devops" in body.lower() or "azure" in body.lower()
        assert "teams" in body.lower()

    def test_shows_connected_status(self, client: TestClient) -> None:
        body = client.get("/dashboard/health").text
        assert "Connected" in body

    def test_contains_navigation(self, client: TestClient) -> None:
        body = client.get("/dashboard/health").text
        assert "nav" in body
        assert "Audit Records" in body


class TestDashboardRecords:
    def test_returns_html(self, client: TestClient) -> None:
        response = client.get("/dashboard/records")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")

    def test_shows_title(self, client: TestClient) -> None:
        body = client.get("/dashboard/records").text
        assert "RAB Audit Records" in body

    def test_shows_empty_state(self, client: TestClient) -> None:
        body = client.get("/dashboard/records").text
        assert "No audit records found" in body


class TestRootRedirect:
    def test_root_returns_health_content(self, client: TestClient) -> None:
        response = client.get("/")
        assert response.status_code == 200
        assert "health-card" in response.text or "RAB Automation" in response.text


class TestDashboardTest:
    @pytest.fixture(autouse=True)
    def _mock_test_runner(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.services.test_runner import TestRunResult

        async def mock_run(timeout: int = 120) -> TestRunResult:
            return TestRunResult(
                success=True,
                passed=118,
                failed=0,
                errors=0,
                skipped=2,
                duration_seconds=3.5,
                output="118 passed, 2 skipped in 3.5s",
                tests=[
                    {"nodeid": "tests/test_approval_service.py::TestApprovalService::test_create_approval", "status": "PASSED"},
                    {"nodeid": "tests/test_approval_service.py::TestApprovalService::test_sdl_approve_moves_to_sdm", "status": "PASSED"},
                    {"nodeid": "tests/test_rab_repository.py::test_record_validation_passed", "status": "SKIPPED"},
                ],
            )
        monkeypatch.setattr("app.api.dashboard.run_test_suite", mock_run)

    def test_returns_html(self, client: TestClient) -> None:
        response = client.get("/dashboard/test")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")

    def test_shows_pass_summary(self, client: TestClient) -> None:
        body = client.get("/dashboard/test").text
        assert "118 passed" in body
        assert "PASS" in body
        assert "Run Tests Again" in body

    def test_shows_test_breakdown(self, client: TestClient) -> None:
        body = client.get("/dashboard/test").text
        assert "Tests Run (3)" in body
        assert "test_create_approval" in body
        assert "test_sdl_approve_moves_to_sdm" in body
        assert "badge-validated" in body
        assert "badge-pending" in body

    def test_failure_shows_fail_badge(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.services.test_runner import TestRunResult

        async def mock_run(timeout: int = 120) -> TestRunResult:
            return TestRunResult(
                success=False,
                passed=110,
                failed=8,
                errors=0,
                duration_seconds=4.2,
                output="8 failed, 110 passed in 4.2s",
                tests=[
                    {"nodeid": "tests/test_rab_repository.py::test_record_validation_passed", "status": "FAILED"},
                ],
            )
        monkeypatch.setattr("app.api.dashboard.run_test_suite", mock_run)
        body = client.get("/dashboard/test").text
        assert "8 failed" in body
        assert "FAIL" in body
        assert "badge-validation_failed" in body

    def test_nav_contains_run_tests_button(self, client: TestClient) -> None:
        body = client.get("/dashboard/health").text
        assert "Run Tests" in body
