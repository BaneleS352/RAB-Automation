"""Tests for the RabOrchestrator approval workflow wiring."""

import pytest

from app.repositories.rab_repository import RabRepository
from app.services.approval_service import ApprovalStep
from app.services.rab_orchestrator import RabOrchestrator


class StubJiraClient:
    async def get_issue(self, issue_key: str, fields: str | None = None) -> dict:
        return {
            "key": issue_key,
            "fields": {
                "summary": "Test release",
                "assignee": {"displayName": "Demo Dev"},
                "reporter": {"displayName": "Demo PM"},
            },
        }

    async def add_comment(self, issue_key: str, body: str) -> dict:
        return {}


class StubAzureClient:
    def is_configured(self) -> bool:
        return True

    async def get_pull_request_by_url(self, pr_url: str) -> dict:
        return {"status": "completed", "title": "URL PR"}

    async def get_pipeline_run_by_url(self, pipeline_url: str) -> dict:
        return {"id": 5, "status": "completed", "result": "succeeded"}


class TestRequestApprovalStatus:
    @pytest.mark.asyncio
    async def test_sdl_request_sets_status(self) -> None:
        orch = RabOrchestrator(jira_client=StubJiraClient(), rab_repo=RabRepository())
        orch.approval_service.create_approval("ORCH-1", "Test")
        await orch._request_approval("ORCH-1", "Test", ApprovalStep.SDL)
        record = await RabRepository().get_record("ORCH-1")
        assert record["status"] == "sdl_requested"
        assert record["sdl_approval"] == "requested"

    @pytest.mark.asyncio
    async def test_sdm_request_sets_status(self) -> None:
        orch = RabOrchestrator(jira_client=StubJiraClient(), rab_repo=RabRepository())
        orch.approval_service.create_approval("ORCH-2", "Test")
        await orch._request_approval("ORCH-2", "Test", ApprovalStep.SDM)
        record = await RabRepository().get_record("ORCH-2")
        assert record["status"] == "sdm_requested"
        assert record["sdm_approval"] == "requested"


class TestCallbackHydration:
    @pytest.mark.asyncio
    async def test_callback_hydrates_state_after_restart(self) -> None:
        """A callback arriving with no in-memory state must reconstruct from the DB."""
        repo = RabRepository()
        orch = RabOrchestrator(jira_client=StubJiraClient(), rab_repo=repo)
        await repo.upsert_record("ORCH-R1", {
            "issue_key": "ORCH-R1", "summary": "Rehydrate", "status": "sdl_requested", "sdl_approval": "requested",
        })

        result = await orch.handle_approval_callback("ORCH-R1", "approve", approver="Manager", reason="ok")
        assert result["status"] == "approved"
        assert result["next"] == "sdm"

        record = await repo.get_record("ORCH-R1")
        assert record["sdl_approval"] == "approved"
        assert record["status"] == "sdm_requested"
        assert record["rejected_by"] == ""

    @pytest.mark.asyncio
    async def test_callback_unknown_issue_returns_error(self) -> None:
        orch = RabOrchestrator(jira_client=StubJiraClient(), rab_repo=RabRepository())
        result = await orch.handle_approval_callback("ORCH-NONE", "approve", approver="Manager")
        assert result["status"] == "error"
        assert result["detail"] == "No active approval"


class TestApprovalIdValidation:
    @pytest.mark.asyncio
    async def test_matching_approval_id_accepted(self) -> None:
        repo = RabRepository()
        orch = RabOrchestrator(jira_client=StubJiraClient(), rab_repo=repo)
        orch.approval_service.create_approval("ORCH-ID1", "Test")
        await orch._request_approval("ORCH-ID1", "Test", ApprovalStep.SDL)

        state = orch.approval_service.get_approval("ORCH-ID1")
        result = await orch.handle_approval_callback(
            "ORCH-ID1", "approve", approver="SDL", approval_id=state.sdl_approval_id,
        )
        assert result["status"] == "approved"

    @pytest.mark.asyncio
    async def test_stale_approval_id_rejected_without_state_change(self) -> None:
        repo = RabRepository()
        orch = RabOrchestrator(jira_client=StubJiraClient(), rab_repo=repo)
        orch.approval_service.create_approval("ORCH-ID2", "Test")
        await orch._request_approval("ORCH-ID2", "Test", ApprovalStep.SDL)

        result = await orch.handle_approval_callback(
            "ORCH-ID2", "approve", approver="SDL", approval_id="stale-id",
        )
        assert result["status"] == "error"
        assert "Invalid approval reference" in result["detail"]

        record = await repo.get_record("ORCH-ID2")
        assert record["sdl_approval"] == "requested"
        assert record["sdl_approval_id"] != "stale-id"

    @pytest.mark.asyncio
    async def test_stale_sdl_card_after_sdl_approved_is_rejected(self) -> None:
        """A replayed SDL card must NOT be treated as an SDM decision."""
        repo = RabRepository()
        orch = RabOrchestrator(jira_client=StubJiraClient(), rab_repo=repo)
        orch.approval_service.create_approval("ORCH-ID3", "Test")
        await orch._request_approval("ORCH-ID3", "Test", ApprovalStep.SDL)

        state = orch.approval_service.get_approval("ORCH-ID3")
        sdl_id = state.sdl_approval_id
        await orch.handle_approval_callback("ORCH-ID3", "approve", approver="SDL", approval_id=sdl_id)
        assert orch.approval_service.get_approval("ORCH-ID3").current_step == ApprovalStep.SDM

        # Replay the same SDL card after the step advanced
        replay = await orch.handle_approval_callback(
            "ORCH-ID3", "approve", approver="SDL", approval_id=sdl_id,
        )
        assert replay["status"] == "error"
        record = await repo.get_record("ORCH-ID3")
        assert record["sdm_approval"] == "requested"
        assert record["sdm_approval"] != "approved"


class TestAzureStatusTracking:
    @pytest.mark.asyncio
    async def test_meeting_callback_populates_azure_status(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JIRA_FIELD_PR_LINK", "customfield_pr")
        monkeypatch.setenv("JIRA_FIELD_PIPELINE_LINK", "customfield_pl")

        class StubIssueJira(StubJiraClient):
            async def get_issue(self, issue_key: str, fields: str | None = None) -> dict:
                data = await super().get_issue(issue_key, fields)
                data["fields"].update({
                    "customfield_pr": "https://dev.azure.com/o/p/_git/r/pullrequest/1",
                    "customfield_pl": "https://dev.azure.com/o/p/_build/results?buildId=5",
                })
                return data

        repo = RabRepository()
        orch = RabOrchestrator(jira_client=StubIssueJira(), rab_repo=repo)
        result = await orch.handle_meeting_callback("AZ-1", needs_meeting=False)
        assert result == "release_ready"

        record = await repo.get_record("AZ-1")
        assert record["status"] == "release_ready"
        # Azure status fields have been removed from the schema

    @pytest.mark.asyncio
    async def test_azure_not_configured_leaves_status_blank(self, monkeypatch: pytest.MonkeyPatch) -> None:
        repo = RabRepository()
        orch = RabOrchestrator(jira_client=StubJiraClient(), rab_repo=repo)
        result = await orch.handle_meeting_callback("AZ-2", needs_meeting=True)
        assert result == "meeting_scheduled"

        record = await repo.get_record("AZ-2")
        assert record["status"] == "meeting_scheduled"
        # Azure status fields have been removed from the schema


class TestFlowStartGuards:
    @pytest.mark.asyncio
    async def test_non_start_event_does_not_start_flow(self) -> None:
        orch = RabOrchestrator(jira_client=StubJiraClient(), rab_repo=RabRepository())
        result = await orch.handle_jira_event("ORCH-G1", "jira:comment_created")
        assert result == "ignored_non_start_event"
        assert await RabRepository().get_record("ORCH-G1") is None

    @pytest.mark.asyncio
    async def test_repeat_start_event_with_active_flow_is_ignored(self) -> None:
        orch = RabOrchestrator(jira_client=StubJiraClient(), rab_repo=RabRepository())
        first = await orch.handle_jira_event("ORCH-G2", "jira:issue_created")
        assert first == "approval_requested_sdl"
        second = await orch.handle_jira_event("ORCH-G2", "jira:issue_created")
        assert second == "already_in_progress"

    @pytest.mark.asyncio
    async def test_start_event_with_db_state_hydrated_is_ignored(self) -> None:
        repo = RabRepository()
        await repo.upsert_record("ORCH-G3", {
            "issue_key": "ORCH-G3", "summary": "Live", "status": "sdl_requested", "sdl_approval": "requested",
        })
        orch = RabOrchestrator(jira_client=StubJiraClient(), rab_repo=repo)
        result = await orch.handle_jira_event("ORCH-G3", "jira:issue_created")
        assert result == "already_in_progress"

    @pytest.mark.asyncio
    async def test_issue_updated_reruns_after_validation_failure(self) -> None:
        """Re-check path: a failed validation leaves no approval state, so an update may restart it."""

        class FlakyValidator:
            def __init__(self) -> None:
                self.calls = 0

            def validate(self, issue_data: dict):
                self.calls += 1
                valid = self.calls > 1
                return type("V", (), {
                    "valid": valid,
                    "detail": "" if valid else "missing fields",
                    "missing_fields": [] if valid else ["summary"],
                })()

            def extract_field_value(self, issue_data: dict, field: str):
                return None

        orch = RabOrchestrator(
            jira_client=StubJiraClient(), rab_repo=RabRepository(), field_validator=FlakyValidator(),
        )
        first = await orch.handle_jira_event("ORCH-G4", "jira:issue_created")
        assert "validation_failed" in first
        second = await orch.handle_jira_event("ORCH-G4", "jira:issue_updated")
        assert second == "approval_requested_sdl"

    @pytest.mark.asyncio
    async def test_none_event_type_is_treated_as_start(self) -> None:
        orch = RabOrchestrator(jira_client=StubJiraClient(), rab_repo=RabRepository())
        result = await orch.handle_jira_event("ORCH-G5", None)
        assert result == "approval_requested_sdl"


class TestDuplicateCallbacks:
    @pytest.mark.asyncio
    async def test_replay_after_full_approval_is_refused(self) -> None:
        repo = RabRepository()
        orch = RabOrchestrator(jira_client=StubJiraClient(), rab_repo=repo)
        orch.approval_service.create_approval("ORCH-3", "Test")
        await orch._request_approval("ORCH-3", "Test", ApprovalStep.SDL)

        await orch.handle_approval_callback("ORCH-3", "approve", approver="SDL")
        await orch.handle_approval_callback("ORCH-3", "approve", approver="SDM")

        dup = await orch.handle_approval_callback("ORCH-3", "reject", approver="SDM", reason="oops")
        assert dup["status"] == "error"
        assert "already" in dup["detail"]

        record = await repo.get_record("ORCH-3")
        assert record["sdm_approval"] == "approved"
        assert record["rejection_reason"] == ""

    @pytest.mark.asyncio
    async def test_duplicate_reject_is_refused(self) -> None:
        repo = RabRepository()
        orch = RabOrchestrator(jira_client=StubJiraClient(), rab_repo=repo)
        orch.approval_service.create_approval("ORCH-4", "Test")
        await orch._request_approval("ORCH-4", "Test", ApprovalStep.SDL)

        first = await orch.handle_approval_callback("ORCH-4", "reject", approver="SDL", reason="no")
        assert first["status"] == "rejected"

        dup = await orch.handle_approval_callback("ORCH-4", "approve", approver="SDL")
        assert dup["status"] == "error"
        assert "already" in dup["detail"]
