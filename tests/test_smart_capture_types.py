"""Tests for Smart Capture types."""

import pytest

from app.smart_capture.types import ExecutionStatus, Trigger


class TestExecutionStatus:
    def test_values(self):
        assert ExecutionStatus.PENDING == "pending"
        assert ExecutionStatus.FIRED == "fired"
        assert ExecutionStatus.COMPLETED == "completed"
        assert ExecutionStatus.SUPPRESSED == "suppressed"
        assert ExecutionStatus.EXPIRED == "expired"


class TestTriggerMatches:
    def test_matches_event_type(self):
        trigger = Trigger(event_type="modulation_change", action_type="capture")
        event = {"event_type": "modulation_change", "severity": "warning",
                 "timestamp": "2026-03-15T10:00:00Z", "message": "test"}
        assert trigger.matches(event) is True

    def test_rejects_wrong_event_type(self):
        trigger = Trigger(event_type="modulation_change", action_type="capture")
        event = {"event_type": "power_change", "severity": "warning",
                 "timestamp": "2026-03-15T10:00:00Z", "message": "test"}
        assert trigger.matches(event) is False

    def test_min_severity_filters_low(self):
        trigger = Trigger(event_type="modulation_change", action_type="capture",
                          min_severity="warning")
        info_event = {"event_type": "modulation_change", "severity": "info",
                      "timestamp": "2026-03-15T10:00:00Z", "message": "test"}
        assert trigger.matches(info_event) is False

    def test_min_severity_passes_equal(self):
        trigger = Trigger(event_type="modulation_change", action_type="capture",
                          min_severity="warning")
        event = {"event_type": "modulation_change", "severity": "warning",
                 "timestamp": "2026-03-15T10:00:00Z", "message": "test"}
        assert trigger.matches(event) is True

    def test_min_severity_passes_higher(self):
        trigger = Trigger(event_type="modulation_change", action_type="capture",
                          min_severity="warning")
        event = {"event_type": "modulation_change", "severity": "critical",
                 "timestamp": "2026-03-15T10:00:00Z", "message": "test"}
        assert trigger.matches(event) is True

    def test_require_details_matches(self):
        trigger = Trigger(event_type="modulation_change", action_type="capture",
                          require_details={"direction": "downgrade"})
        event = {"event_type": "modulation_change", "severity": "warning",
                 "timestamp": "2026-03-15T10:00:00Z", "message": "test",
                 "details": {"direction": "downgrade", "changes": []}}
        assert trigger.matches(event) is True

    def test_require_details_rejects_mismatch(self):
        trigger = Trigger(event_type="modulation_change", action_type="capture",
                          require_details={"direction": "downgrade"})
        event = {"event_type": "modulation_change", "severity": "info",
                 "timestamp": "2026-03-15T10:00:00Z", "message": "test",
                 "details": {"direction": "upgrade", "changes": []}}
        assert trigger.matches(event) is False

    def test_require_details_rejects_missing_details(self):
        trigger = Trigger(event_type="modulation_change", action_type="capture",
                          require_details={"direction": "downgrade"})
        event = {"event_type": "modulation_change", "severity": "warning",
                 "timestamp": "2026-03-15T10:00:00Z", "message": "test"}
        assert trigger.matches(event) is False

    def test_no_severity_filter_accepts_all(self):
        trigger = Trigger(event_type="error_spike", action_type="capture")
        for sev in ("info", "warning", "critical"):
            event = {"event_type": "error_spike", "severity": sev,
                     "timestamp": "2026-03-15T10:00:00Z", "message": "test"}
            assert trigger.matches(event) is True
