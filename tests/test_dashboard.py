"""Tests for the HTML dashboard views - updated for integration removal."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _set_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_WEBHOOK_URL", "http://testserver/webhooks/jira")
    monkeypatch.setenv("APP_ENV", "test")


@pytest.fixture(autouse=True)
def _mock_jira_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.dashboard import _health_cache
    from app.services.jira_client import JiraClient

    _health_cache["services"] = None
    _health_cache["at"] = 0.0

    async def mock_check(self):
        return {"connected": True, "details": "Jira API is reachable and authenticated."}
    monkeypatch.setattr(JiraClient, "check_connection", mock_check)


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

    def test_shows_empty_state(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.repositories.rab_repository import RabRepository

        async def mock_get_all(self, limit=25, offset=0, status="", q=""):
            return [], 0
        monkeypatch.setattr(RabRepository, "get_all_records_with_count", mock_get_all)
        body = client.get("/dashboard/records").text
        assert "No audit records found" in body


class TestDashboardHealthCache:
    def test_connection_checks_are_cached_within_ttl(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.api import dashboard as dashboard_mod
        from app.services.jira_client import JiraClient

        dashboard_mod._health_cache["services"] = None
        dashboard_mod._health_cache["at"] = 0.0
        calls = {"jira": 0}

        async def jira_check(self):
            calls["jira"] += 1
            return {"connected": True, "details": "ok"}

        monkeypatch.setattr(JiraClient, "check_connection", jira_check)

        client.get("/dashboard/health")
        client.get("/dashboard/health")
        assert calls["jira"] == 1


class TestDashboardOverview:
    def test_shows_pipeline_summary(self, client: TestClient) -> None:
        body = client.get("/dashboard/health").text
        assert "Pipeline Summary" in body
        assert "Total Tickets" in body

    def test_shows_aging_and_failures_sections(self, client: TestClient) -> None:
        body = client.get("/dashboard/health").text
        assert "Waiting for Approval" in body
        assert "Recent Failures" in body

    def test_auto_refreshes(self, client: TestClient) -> None:
        body = client.get("/dashboard/health").text
        assert 'http-equiv="refresh"' in body
        assert "Refresh" in body


class TestDashboardRecordsFiltering:
    def test_shows_filter_form(self, client: TestClient) -> None:
        body = client.get("/dashboard/records").text
        assert "Search issue key" in body
        assert "All statuses" in body

    def test_filters_by_status(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.repositories.rab_repository import RabRepository

        row = {
            "issue_key": "FILT-1", "summary": "Filter test", "status": "release_ready",
            "validation_result": "", "sdl_approval": "approved", "sdm_approval": "approved",
            "meeting_needed": 0, "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00",
        }

        async def mock_get_all(self, limit=25, offset=0, status="", q=""):
            if status == "release_ready":
                return [row], 1
            return [], 0
        monkeypatch.setattr(RabRepository, "get_all_records_with_count", mock_get_all)
        body = client.get("/dashboard/records?status=release_ready").text
        assert "FILT-1" in body
        assert "1 of 1 records shown" in body

    def test_pagination_next_link_when_more_pages(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.repositories.rab_repository import RabRepository

        row = {
            "issue_key": "PAG-1", "summary": "", "status": "pending",
            "validation_result": "", "sdl_approval": "pending", "sdm_approval": "pending",
            "meeting_needed": 0, "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00",
        }

        async def mock_get_all(self, limit=25, offset=0, status="", q=""):
            return [row] * 25, 100

        monkeypatch.setattr(RabRepository, "get_all_records_with_count", mock_get_all)
        body = client.get("/dashboard/records").text
        assert "Next »" in body
        assert "Page 1" in body


class TestDashboardRecordDetail:
    @pytest.fixture(autouse=True)
    def _mock_repo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.repositories.rab_repository import RabRepository

        async def mock_get_record(self, issue_key):
            return {
                "id": 1, "issue_key": issue_key, "summary": "Release v2", "status": "meeting_scheduled",
                "validation_result": "All required fields are present.", "sdl_approval": "approved",
                "sdm_approval": "approved", "rejection_reason": "", "rejected_by": "",
                "meeting_needed": 1,
                "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00",
            }

        async def mock_get_events(self, issue_key):
            return [{
                "id": 1, "issue_key": issue_key, "step": "SDL", "action": "approve",
                "approver": "Jane", "reason": "Looks good", "created_at": "2026-01-01T00:00:00",
            }]

        monkeypatch.setattr(RabRepository, "get_record", mock_get_record)
        monkeypatch.setattr(RabRepository, "get_approval_events", mock_get_events)

    def test_shows_record_fields_and_timeline(self, client: TestClient) -> None:
        body = client.get("/dashboard/records/DET-1").text
        assert "Release v2" in body
        assert "All required fields are present." in body
        assert "Approval Timeline" in body
        assert "Jane" in body
        assert "Looks good" in body

    def test_missing_record(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.repositories.rab_repository import RabRepository

        async def none(self, issue_key):
            return None

        monkeypatch.setattr(RabRepository, "get_record", none)
        body = client.get("/dashboard/records/NOPE").text
        assert "No record found" in body


class TestDashboardWebhooks:
    @pytest.fixture(autouse=True)
    def _mock_repo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.repositories.rab_repository import RabRepository

        async def mock_get(self, limit=100, offset=0):
            return [{
                "id": 1, "event_id": "evt-1", "issue_key": "WH-1",
                "event_type": "jira:issue_created", "status": "received",
                "created_at": "2026-01-01T00:00:00",
            }]

        monkeypatch.setattr(RabRepository, "get_webhook_events", mock_get)

    def test_shows_events(self, client: TestClient) -> None:
        body = client.get("/dashboard/webhooks").text
        assert "Webhook Activity" in body
        assert "evt-1" in body
        assert "WH-1" in body


class TestDashboardMetrics:
    def test_shows_counters(self, client: TestClient) -> None:
        body = client.get("/dashboard/metrics").text
        assert "Operational Metrics" in body
        assert "Requests" in body
        assert "Uptime" in body


class TestDashboardDemo:
    def test_shows_form(self, client: TestClient) -> None:
        body = client.get("/dashboard/demo").text
        assert "Demo Approval Flow" in body
        assert "Run Flow" in body

    def test_run_shows_steps(self, client: TestClient) -> None:
        body = client.post(
            "/dashboard/demo",
            data={"issue_key": "DEMO-UI-1"},
        ).text
        assert "Result: OK" in body
        assert "sdl_approval" in body
        assert "meeting_decision" in body


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
        body = client.post("/dashboard/test").text
        assert "118 passed" in body
        assert "PASS" in body
        assert "Run Tests Again" in body

    def test_shows_test_breakdown(self, client: TestClient) -> None:
        body = client.post("/dashboard/test").text
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
        body = client.post("/dashboard/test").text
        assert "8 failed" in body
        assert "FAIL" in body
        assert "badge-validation_failed" in body

    def test_nav_contains_run_tests_button(self, client: TestClient) -> None:
        body = client.get("/dashboard/health").text
        assert "Run Tests" in body