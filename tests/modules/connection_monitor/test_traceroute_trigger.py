"""Tests for TracerouteTrigger event-driven traceroute execution."""

import time
from unittest.mock import MagicMock, patch

import pytest

from app.modules.connection_monitor.traceroute_probe import TracerouteHop, TracerouteResult
from app.modules.connection_monitor.traceroute_trigger import TracerouteTrigger

MODULE = "app.modules.connection_monitor.traceroute_trigger"


def _make_probe_result(hop_count=3, reached=True):
    """Build a TracerouteResult with N hops."""
    hops = [
        TracerouteHop(
            hop_index=i,
            hop_ip=f"10.0.0.{i}",
            hop_host=f"hop-{i}.example.com",
            latency_ms=1.5 * (i + 1),
            probes_responded=3,
        )
        for i in range(hop_count)
    ]
    return TracerouteResult(hops=hops, reached_target=reached, route_fingerprint="abc123")


def _outage_event(target_id=1):
    return {
        "timestamp": "2026-03-17T04:05:48Z",
        "severity": "critical",
        "event_type": "cm_target_unreachable",
        "message": f"Target {target_id} unreachable",
        "details": {"target_id": target_id},
    }


def _loss_event(target_id=1):
    return {
        "timestamp": "2026-03-17T04:05:48Z",
        "severity": "warning",
        "event_type": "cm_packet_loss_warning",
        "message": f"Target {target_id}: 5.0% packet loss",
        "details": {"target_id": target_id, "packet_loss_pct": 5.0},
    }


@pytest.fixture
def probe():
    mock = MagicMock()
    mock.run.return_value = _make_probe_result()
    return mock


@pytest.fixture
def storage():
    mock = MagicMock()
    mock.get_target.return_value = {"id": 1, "host": "1.1.1.1", "name": "Test", "enabled": True}
    return mock


@pytest.fixture
def trigger(probe, storage):
    return TracerouteTrigger(probe=probe, storage=storage)


class TestEventFiltering:
    def test_ignores_irrelevant_events(self, trigger, probe):
        """Events with event_type != outage/loss are ignored."""
        trigger.on_event({
            "timestamp": "2026-03-17T04:05:48Z",
            "severity": "info",
            "event_type": "cm_target_recovered",
            "message": "Target recovered",
            "details": {"target_id": 1},
        })
        probe.run.assert_not_called()

    def test_triggers_on_outage(self, trigger, probe):
        """cm_target_unreachable triggers traceroute."""
        trigger.on_event(_outage_event())
        trigger._executor.shutdown(wait=True)
        probe.run.assert_called_once_with("1.1.1.1")

    def test_triggers_on_packet_loss(self, trigger, probe):
        """cm_packet_loss_warning triggers traceroute."""
        trigger.on_event(_loss_event())
        trigger._executor.shutdown(wait=True)
        probe.run.assert_called_once_with("1.1.1.1")


class TestCooldown:
    def test_cooldown_prevents_rapid_traces(self, trigger, probe):
        """Second event within 5 min is blocked."""
        trigger.on_event(_outage_event())
        trigger._executor.shutdown(wait=True)
        assert probe.run.call_count == 1

        # Second event — should be blocked by cooldown
        trigger._executor = __import__("concurrent.futures", fromlist=["ThreadPoolExecutor"]).ThreadPoolExecutor(max_workers=1)
        trigger.on_event(_outage_event())
        trigger._executor.shutdown(wait=True)
        assert probe.run.call_count == 1

    def test_cooldown_per_target(self, trigger, probe, storage):
        """Different targets have independent cooldowns."""
        storage.get_target.side_effect = lambda tid: {
            1: {"id": 1, "host": "1.1.1.1", "name": "T1", "enabled": True},
            2: {"id": 2, "host": "8.8.8.8", "name": "T2", "enabled": True},
        }.get(tid)

        trigger.on_event(_outage_event(target_id=1))
        trigger._executor.shutdown(wait=True)
        assert probe.run.call_count == 1

        trigger._executor = __import__("concurrent.futures", fromlist=["ThreadPoolExecutor"]).ThreadPoolExecutor(max_workers=1)
        trigger.on_event(_outage_event(target_id=2))
        trigger._executor.shutdown(wait=True)
        assert probe.run.call_count == 2

    def test_cooldown_resets_after_period(self, trigger, probe):
        """Event after 5+ min is allowed."""
        trigger.on_event(_outage_event())
        trigger._executor.shutdown(wait=True)
        assert probe.run.call_count == 1

        # Simulate cooldown expiry by backdating _last_trace
        trigger._last_trace[1] = time.time() - 301
        trigger._executor = __import__("concurrent.futures", fromlist=["ThreadPoolExecutor"]).ThreadPoolExecutor(max_workers=1)
        trigger.on_event(_outage_event())
        trigger._executor.shutdown(wait=True)
        assert probe.run.call_count == 2


class TestEdgeCases:
    def test_deleted_target_handled(self, trigger, probe, storage):
        """storage.get_target returns None, no crash."""
        storage.get_target.return_value = None
        trigger.on_event(_outage_event())
        trigger._executor.shutdown(wait=True)
        probe.run.assert_not_called()

    def test_shutdown_stops_executor(self, trigger):
        """executor.shutdown called."""
        with patch.object(trigger._executor, "shutdown") as mock_shutdown:
            trigger.shutdown()
            mock_shutdown.assert_called_once_with(wait=False)


class TestStorageIntegration:
    def test_saves_trace_to_storage(self, trigger, probe, storage):
        """Verify save_trace called with correct args."""
        trigger.on_event(_outage_event())
        trigger._executor.shutdown(wait=True)

        storage.save_trace.assert_called_once()
        call_kwargs = storage.save_trace.call_args[1]
        assert call_kwargs["target_id"] == 1
        assert call_kwargs["trigger_reason"] == "outage"
        assert call_kwargs["route_fingerprint"] == "abc123"
        assert call_kwargs["reached_target"] is True
        assert len(call_kwargs["hops"]) == 3
        assert call_kwargs["hops"][0]["hop_ip"] == "10.0.0.0"
        assert call_kwargs["hops"][0]["hop_host"] == "hop-0.example.com"

    def test_saves_packet_loss_reason(self, trigger, probe, storage):
        """Packet loss event saves reason as 'packet_loss'."""
        trigger.on_event(_loss_event())
        trigger._executor.shutdown(wait=True)

        call_kwargs = storage.save_trace.call_args[1]
        assert call_kwargs["trigger_reason"] == "packet_loss"
