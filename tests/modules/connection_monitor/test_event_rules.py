"""Tests for Connection Monitor event rules."""

import time
import pytest

from app.modules.connection_monitor.event_rules import ConnectionEventRules


@pytest.fixture
def rules():
    return ConnectionEventRules(outage_threshold=5, loss_warning_pct=2.0)


class TestOutageDetection:
    def test_no_event_below_threshold(self, rules):
        for _ in range(4):
            events = rules.check_probe_result(target_id=1, timeout=True)
        assert events == []

    def test_outage_event_at_threshold(self, rules):
        for _ in range(4):
            rules.check_probe_result(target_id=1, timeout=True)
        events = rules.check_probe_result(target_id=1, timeout=True)
        assert len(events) == 1
        assert events[0]["event_type"] == "cm_target_unreachable"
        assert events[0]["severity"] == "critical"

    def test_no_duplicate_outage_events(self, rules):
        for _ in range(5):
            rules.check_probe_result(target_id=1, timeout=True)
        # Further timeouts should not produce more events
        events = rules.check_probe_result(target_id=1, timeout=True)
        assert events == []

    def test_recovery_event(self, rules):
        for _ in range(5):
            rules.check_probe_result(target_id=1, timeout=True)
        events = rules.check_probe_result(target_id=1, timeout=False)
        assert len(events) == 1
        assert events[0]["event_type"] == "cm_target_recovered"
        assert events[0]["severity"] == "info"

    def test_no_recovery_without_prior_outage(self, rules):
        events = rules.check_probe_result(target_id=1, timeout=False)
        assert events == []

    def test_independent_targets(self, rules):
        for _ in range(5):
            rules.check_probe_result(target_id=1, timeout=True)
        # Target 2 should be independent
        events = rules.check_probe_result(target_id=2, timeout=False)
        assert events == []


class TestPacketLoss:
    def test_loss_warning(self, rules):
        events = rules.check_window_stats(
            target_id=1, packet_loss_pct=5.0, window_seconds=60,
        )
        assert len(events) == 1
        assert events[0]["event_type"] == "cm_packet_loss_warning"
        assert events[0]["severity"] == "warning"

    def test_no_warning_below_threshold(self, rules):
        events = rules.check_window_stats(
            target_id=1, packet_loss_pct=1.0, window_seconds=60,
        )
        assert events == []

    def test_loss_warning_cooldown(self, rules):
        rules.check_window_stats(target_id=1, packet_loss_pct=5.0, window_seconds=60)
        events = rules.check_window_stats(
            target_id=1, packet_loss_pct=5.0, window_seconds=60,
        )
        assert events == []  # Cooldown prevents duplicate
