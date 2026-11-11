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


class TestTargetIdentity:
    """Events name the target as it was when they happened (#1106).

    Target IDs are stable database keys that are never reused, so after a
    delete the next target gets a higher ID than the number of live targets.
    An event must therefore carry the target's label and address itself.
    """

    def _events(self, rules, **identity):
        for _ in range(5):
            unreachable = rules.check_probe_result(target_id=3, timeout=True, **identity)
        recovered = rules.check_probe_result(target_id=3, timeout=False, **identity)
        loss = rules.check_window_stats(
            target_id=3, packet_loss_pct=4.5, window_seconds=60, **identity,
        )
        return unreachable + recovered + loss

    def test_all_event_types_snapshot_label_and_host(self, rules):
        events = self._events(rules, target_label="Cloudflare DNS", target_host="1.1.1.1")
        assert [e["event_type"] for e in events] == [
            "cm_target_unreachable", "cm_target_recovered", "cm_packet_loss_warning",
        ]
        for event in events:
            assert event["details"]["target_id"] == 3
            assert event["details"]["target_label"] == "Cloudflare DNS"
            assert event["details"]["target_host"] == "1.1.1.1"
            assert "Cloudflare DNS (1.1.1.1)" in event["message"]
            assert "Target 3" not in event["message"]

    def test_messages_keep_their_english_wording(self, rules):
        unreachable, recovered, loss = self._events(
            rules, target_label="Cloudflare DNS", target_host="1.1.1.1",
        )
        assert unreachable["message"] == "Target Cloudflare DNS (1.1.1.1) unreachable (5 consecutive timeouts)"
        assert recovered["message"] == "Target Cloudflare DNS (1.1.1.1) recovered after 5 timeouts"
        assert loss["message"] == "Target Cloudflare DNS (1.1.1.1): 4.5% packet loss over 60s"

    @pytest.mark.parametrize("label, host, name", [
        ("", "1.1.1.1", "1.1.1.1"),
        ("1.1.1.1", "1.1.1.1", "1.1.1.1"),
        ("  Router  ", " 192.168.0.1 ", "Router (192.168.0.1)"),
        ("Gateway", "", "Gateway"),
        ("", "", "ID 3"),
        (None, None, "ID 3"),
    ])
    def test_partial_identity_names_the_target_sensibly(self, rules, label, host, name):
        events = self._events(rules, target_label=label, target_host=host)
        assert events[0]["message"] == f"Target {name} unreachable (5 consecutive timeouts)"
        assert events[2]["message"] == f"Target {name}: 4.5% packet loss over 60s"
        for event in events:
            assert event["details"]["target_label"] == (label or "").strip()
            assert event["details"]["target_host"] == (host or "").strip()
