"""Tests for the built-in ping monitor and gaming quality index."""

import pytest
from unittest.mock import MagicMock, patch

from app.ping_monitor import (
    PingResult, PingMonitor, ping_target, _parse_ping_output,
    DEFAULT_TARGETS, DEFAULT_INTERVAL, DEFAULT_COUNT,
)


# ── Ping output parsing ──

LINUX_OUTPUT = """\
PING 8.8.8.8 (8.8.8.8) 56(84) bytes of data.
64 bytes from 8.8.8.8: icmp_seq=1 ttl=117 time=12.3 ms
64 bytes from 8.8.8.8: icmp_seq=2 ttl=117 time=11.8 ms
64 bytes from 8.8.8.8: icmp_seq=3 ttl=117 time=14.1 ms
64 bytes from 8.8.8.8: icmp_seq=4 ttl=117 time=12.0 ms
64 bytes from 8.8.8.8: icmp_seq=5 ttl=117 time=11.5 ms

--- 8.8.8.8 ping statistics ---
5 packets transmitted, 5 received, 0% packet loss, time 4006ms
rtt min/avg/max/mdev = 11.500/12.340/14.100/0.893 ms
"""

WINDOWS_OUTPUT = """\
Pinging 8.8.8.8 with 32 bytes of data:
Reply from 8.8.8.8: bytes=32 time=12ms TTL=117
Reply from 8.8.8.8: bytes=32 time=11ms TTL=117
Reply from 8.8.8.8: bytes=32 time=14ms TTL=117
Reply from 8.8.8.8: bytes=32 time=12ms TTL=117
Reply from 8.8.8.8: bytes=32 time=11ms TTL=117

Ping statistics for 8.8.8.8:
    Packets: Sent = 5, Received = 5, Lost = 0 (0% loss),
Approximate round trip times in milli-seconds:
    Minimum = 11ms, Maximum = 14ms, Average = 12ms
"""

WINDOWS_GERMAN_OUTPUT = """\
Ping wird ausgefuehrt fuer 8.8.8.8 mit 32 Bytes Daten:
Antwort von 8.8.8.8: Bytes=32 Zeit=12ms TTL=117

Ping-Statistik fuer 8.8.8.8:
    Pakete: Gesendet = 5, Empfangen = 4, Verloren = 1 (20% Verlust),
Ca. Zeitangaben in Millisek.:
    Minimum = 11ms, Maximum = 14ms, Mittelwert = 12ms
"""

LOSS_OUTPUT = """\
PING 10.0.0.1 (10.0.0.1) 56(84) bytes of data.

--- 10.0.0.1 ping statistics ---
5 packets transmitted, 0 received, 100% packet loss, time 4028ms
"""


class TestParsePingOutput:
    def test_linux_format(self):
        result = _parse_ping_output(LINUX_OUTPUT, "8.8.8.8", 5)
        assert result is not None
        assert result.target == "8.8.8.8"
        assert result.avg_ms == 12.34
        assert result.min_ms == 11.5
        assert result.max_ms == 14.1
        assert result.jitter_ms == 0.893
        assert result.loss_pct == 0.0
        assert result.count == 5

    def test_windows_format(self):
        result = _parse_ping_output(WINDOWS_OUTPUT, "8.8.8.8", 5)
        assert result is not None
        assert result.avg_ms == 12.0
        assert result.min_ms == 11.0
        assert result.max_ms == 14.0
        assert result.jitter_ms == 3.0  # max - min
        assert result.loss_pct == 0.0

    def test_windows_german_format(self):
        result = _parse_ping_output(WINDOWS_GERMAN_OUTPUT, "8.8.8.8", 5)
        assert result is not None
        assert result.avg_ms == 12.0
        assert result.loss_pct == 20.0

    def test_unparseable_output(self):
        result = _parse_ping_output("garbage data", "8.8.8.8", 5)
        assert result is None


# ── PingResult dataclass ──

class TestPingResult:
    def test_fields(self):
        r = PingResult(
            target="1.1.1.1", timestamp="2026-01-01T00:00:00",
            avg_ms=10.0, min_ms=8.0, max_ms=12.0, jitter_ms=2.0,
            loss_pct=0.0, count=5,
        )
        assert r.target == "1.1.1.1"
        assert r.__dict__["avg_ms"] == 10.0


# ── PingMonitor ──

class TestPingMonitor:
    def test_defaults(self):
        pm = PingMonitor()
        assert pm.targets == DEFAULT_TARGETS
        assert pm.interval == DEFAULT_INTERVAL
        assert pm.count == DEFAULT_COUNT

    def test_custom_targets(self):
        pm = PingMonitor(targets=["10.0.0.1"])
        assert pm.targets == ["10.0.0.1"]

    @patch("app.ping_monitor.ping_target")
    def test_run_once(self, mock_ping):
        mock_ping.return_value = PingResult(
            target="8.8.8.8", timestamp="2026-01-01T00:00:00",
            avg_ms=12.0, min_ms=10.0, max_ms=14.0, jitter_ms=2.0,
            loss_pct=0.0, count=5,
        )
        pm = PingMonitor(targets=["8.8.8.8"])
        results = pm.run_once()
        assert len(results) == 1
        assert results[0].avg_ms == 12.0

    @patch("app.ping_monitor.ping_target")
    def test_run_once_stores_results(self, mock_ping):
        storage = MagicMock()
        mock_ping.return_value = PingResult(
            target="1.1.1.1", timestamp="now",
            avg_ms=5.0, min_ms=4.0, max_ms=6.0, jitter_ms=1.0,
            loss_pct=0.0, count=3,
        )
        pm = PingMonitor(storage=storage, targets=["1.1.1.1"])
        pm.run_once()
        storage.save_ping_result.assert_called_once()

    @patch("app.ping_monitor.ping_target")
    def test_run_once_skips_none_results(self, mock_ping):
        mock_ping.return_value = None
        pm = PingMonitor(targets=["10.0.0.99"])
        results = pm.run_once()
        assert results == []

    @patch("app.ping_monitor.ping_target")
    def test_latest_updated(self, mock_ping):
        result = PingResult(
            target="8.8.8.8", timestamp="now",
            avg_ms=10.0, min_ms=8.0, max_ms=12.0, jitter_ms=2.0,
            loss_pct=0.0, count=5,
        )
        mock_ping.return_value = result
        pm = PingMonitor(targets=["8.8.8.8"])
        pm.run_once()
        latest = pm.latest
        assert "8.8.8.8" in latest
        assert latest["8.8.8.8"].avg_ms == 10.0

    def test_start_stop(self):
        pm = PingMonitor(targets=["127.0.0.1"], interval=1)
        pm.start()
        assert pm._thread is not None
        assert pm._thread.is_alive()
        pm.stop()
        assert not pm._thread.is_alive()


# ── Gaming index ──

class TestGamingIndex:
    def test_perfect_conditions(self):
        pm = PingMonitor()
        pm._latest = {
            "8.8.8.8": PingResult("8.8.8.8", "now", avg_ms=10.0, min_ms=8.0,
                                   max_ms=12.0, jitter_ms=2.0, loss_pct=0.0, count=5),
        }
        result = pm.compute_gaming_index()
        assert result["score"] >= 90
        assert result["grade"] == "A"
        assert "latency_score" in result["components"]
        assert "jitter_score" in result["components"]
        assert "loss_score" in result["components"]

    def test_poor_conditions(self):
        pm = PingMonitor()
        pm._latest = {
            "8.8.8.8": PingResult("8.8.8.8", "now", avg_ms=150.0, min_ms=100.0,
                                   max_ms=200.0, jitter_ms=60.0, loss_pct=8.0, count=5),
        }
        result = pm.compute_gaming_index()
        assert result["score"] < 40
        assert result["grade"] == "F"

    def test_moderate_conditions(self):
        pm = PingMonitor()
        pm._latest = {
            "8.8.8.8": PingResult("8.8.8.8", "now", avg_ms=50.0, min_ms=40.0,
                                   max_ms=60.0, jitter_ms=20.0, loss_pct=1.0, count=5),
        }
        result = pm.compute_gaming_index()
        assert 40 <= result["score"] <= 80
        assert result["grade"] in ("C", "D")

    def test_empty_stats(self):
        pm = PingMonitor()
        result = pm.compute_gaming_index()
        assert result["score"] == 0
        assert result["grade"] == "?"

    def test_latency_scoring_boundary(self):
        """20ms → score 100, 100ms → score 0."""
        pm = PingMonitor()
        # 20ms latency, perfect jitter and loss
        pm._latest = {
            "x": PingResult("x", "now", avg_ms=20.0, min_ms=20.0,
                            max_ms=20.0, jitter_ms=0.0, loss_pct=0.0, count=5),
        }
        result = pm.compute_gaming_index()
        assert result["components"]["latency_score"] == 100

    def test_get_stats_in_memory(self):
        """Without storage, stats come from latest dict."""
        pm = PingMonitor()
        pm._latest = {
            "8.8.8.8": PingResult("8.8.8.8", "now", avg_ms=15.0, min_ms=10.0,
                                   max_ms=20.0, jitter_ms=5.0, loss_pct=0.5, count=5),
            "1.1.1.1": PingResult("1.1.1.1", "now", avg_ms=25.0, min_ms=20.0,
                                   max_ms=30.0, jitter_ms=5.0, loss_pct=0.5, count=5),
        }
        stats = pm.get_stats()
        assert stats["avg_ms"] == 20.0  # (15+25)/2
        assert stats["targets"] == 2

    def test_get_stats_empty(self):
        pm = PingMonitor()
        assert pm.get_stats() == {}
