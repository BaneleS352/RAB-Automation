"""Tests for the ApprovalService state machine."""

import pytest
from app.services.approval_service import ApprovalService, ApprovalStep, ApprovalStatus


class TestApprovalService:
    def setup_method(self):
        self.service = ApprovalService()
        self.service.reset()

    def test_create_approval(self):
        state = self.service.create_approval("TEST-1", "Test release")
        assert state.issue_key == "TEST-1"
        assert state.current_step == ApprovalStep.SDL
        assert state.sdl_status == ApprovalStatus.PENDING

    def test_get_approval_returns_none_for_unknown(self):
        assert self.service.get_approval("UNKNOWN") is None

    def test_get_current_approver_sdl(self):
        self.service.create_approval("TEST-1", "Test")
        assert self.service.get_current_approver("TEST-1") == "SDL"

    def test_sdl_approve_moves_to_sdm(self):
        self.service.create_approval("TEST-1", "Test")
        result = self.service.process_response("TEST-1", "approve")
        assert result["decision"] == "approved"
        assert result["next_step"] == "SDM"
        assert self.service.get_current_approver("TEST-1") == "SDM"

    def test_sdm_approve_completes_flow(self):
        self.service.create_approval("TEST-1", "Test")
        self.service.process_response("TEST-1", "approve")
        result = self.service.process_response("TEST-1", "approve")
        assert result["decision"] == "approved"
        assert result["next_step"] is None
        assert self.service.is_fully_approved("TEST-1") is True

    def test_sdl_reject_stops_flow(self):
        self.service.create_approval("TEST-1", "Test")
        result = self.service.process_response("TEST-1", "reject", "Missing info")
        assert result["decision"] == "rejected"
        assert result["rejected_by"] == "SDL"
        assert self.service.is_rejected("TEST-1") is True
        assert self.service.is_fully_approved("TEST-1") is False

    def test_sdm_reject_after_sdl_approve(self):
        self.service.create_approval("TEST-1", "Test")
        self.service.process_response("TEST-1", "approve")
        result = self.service.process_response("TEST-1", "reject", "Not ready")
        assert result["decision"] == "rejected"
        assert result["rejected_by"] == "SDM"

    def test_record_approval_id(self):
        self.service.create_approval("TEST-1", "Test")
        self.service.record_approval_id("TEST-1", "sdl-abc")
        state = self.service.get_approval("TEST-1")
        assert state.sdl_approval_id == "sdl-abc"

        self.service.process_response("TEST-1", "approve")
        self.service.record_approval_id("TEST-1", "sdm-xyz")
        assert state.sdm_approval_id == "sdm-xyz"
