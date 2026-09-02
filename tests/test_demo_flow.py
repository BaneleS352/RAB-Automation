"""Tests for the dummy RAB approval flow and demo endpoint."""

import pytest
from fastapi.testclient import TestClient

from app.services.dummy_flow import DummyFlowService
from app.repositories.rab_repository import RabRepository


class TestDummyFlowService:
    @pytest.mark.asyncio
    async def test_full_approval_writes_audit_records(self) -> None:
        service = DummyFlowService(issue_key="DUMMY-A-1")
        result = await service.run_full_approval(needs_meeting=False)
        assert result.status == "ok"
        steps = [s["step"] for s in result.steps]
        assert steps == ["validation", "sdl_approval", "sdm_approval", "meeting_decision"]

        record = await RabRepository().get_record("DUMMY-A-1")
        assert record is not None
        assert record["sdl_approval"] == "approved"
        assert record["sdm_approval"] == "approved"
        assert record["status"] == "release_ready"
        assert record["meeting_needed"] == 0

    @pytest.mark.asyncio
    async def test_full_approval_with_meeting(self) -> None:
        service = DummyFlowService(issue_key="DUMMY-A-2")
        await service.run_full_approval(needs_meeting=True)
        record = await RabRepository().get_record("DUMMY-A-2")
        assert record["status"] == "meeting_scheduled"
        assert record["meeting_needed"] == 1

    @pytest.mark.asyncio
    async def test_rejection_stops_flow(self) -> None:
        service = DummyFlowService(issue_key="DUMMY-R-1")
        result = await service.run_rejection()
        steps = [s["step"] for s in result.steps]
        assert steps == ["validation", "sdl_rejection"]
        record = await RabRepository().get_record("DUMMY-R-1")
        assert record["sdl_approval"] == "rejected"
        assert record["status"] == "sdl_rejected"
        assert record["rejected_by"] == "Demo Creator"

    @pytest.mark.asyncio
    async def test_records_approval_events(self) -> None:
        service = DummyFlowService(issue_key="DUMMY-A-3")
        await service.run_full_approval()
        events = await RabRepository().get_approval_events("DUMMY-A-3")
        assert len(events) == 2
        assert {e["step"] for e in events} == {"SDL", "SDM"}
        assert all(e["action"] == "approve" for e in events)


class TestDemoEndpoint:
    @pytest.fixture(autouse=True)
    def _set_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JIRA_WEBHOOK_URL", "http://testserver/webhooks/jira")
        monkeypatch.setenv("APP_ENV", "test")

    @pytest.fixture()
    def client(self) -> TestClient:
        from app.main import create_app
        return TestClient(create_app())

    def test_flow_returns_steps(self, client: TestClient) -> None:
        resp = client.post(
            "/demo/flow",
            data={"issue_key": "DUMMY-API-1"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["issue_key"] == "DUMMY-API-1"
        assert data["status"] == "ok"
        step_names = [s["step"] for s in data["steps"]]
        assert "validation" in step_names
        assert "meeting_decision" in step_names

    def test_reject_flow(self, client: TestClient) -> None:
        resp = client.post(
            "/demo/flow",
            data={"issue_key": "DUMMY-API-R", "reject": "true"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "rejected"
        step_names = [s["step"] for s in data["steps"]]
        assert "sdl_rejection" in step_names
