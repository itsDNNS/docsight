"""Tests for the Connection Monitor probe engine."""

import socket
from unittest.mock import patch, MagicMock
import pytest

from app.modules.connection_monitor.probe import ProbeEngine, ProbeResult


class TestProbeResult:
    def test_success_result(self):
        r = ProbeResult(latency_ms=12.5, timeout=False, method="icmp")
        assert r.latency_ms == 12.5
        assert r.timeout is False
        assert r.method == "icmp"

    def test_timeout_result(self):
        r = ProbeResult(latency_ms=None, timeout=True, method="tcp")
        assert r.latency_ms is None
        assert r.timeout is True


class TestProbeEngineAutoDetection:
    def test_auto_selects_icmp_when_raw_socket_available(self):
        mock_sock = MagicMock()
        with patch("app.modules.connection_monitor.probe.socket.socket", return_value=mock_sock):
            engine = ProbeEngine(method="auto")
            assert engine.detected_method == "icmp"

    def test_auto_falls_back_to_tcp_on_permission_error(self):
        with patch("app.modules.connection_monitor.probe.socket.socket", side_effect=PermissionError):
            engine = ProbeEngine(method="auto")
            assert engine.detected_method == "tcp"

    def test_auto_falls_back_to_tcp_on_os_error(self):
        with patch("app.modules.connection_monitor.probe.socket.socket", side_effect=OSError):
            engine = ProbeEngine(method="auto")
            assert engine.detected_method == "tcp"

    def test_explicit_icmp(self):
        engine = ProbeEngine(method="icmp")
        assert engine.detected_method == "icmp"

    def test_explicit_tcp(self):
        engine = ProbeEngine(method="tcp")
        assert engine.detected_method == "tcp"

    def test_capability_info(self):
        with patch("app.modules.connection_monitor.probe.socket.socket", side_effect=PermissionError):
            engine = ProbeEngine(method="auto")
            info = engine.capability_info()
            assert info["method"] == "tcp"
            assert "reason" in info


class TestTCPProbe:
    def test_tcp_success(self):
        engine = ProbeEngine(method="tcp")
        with patch("app.modules.connection_monitor.probe.socket.socket") as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            mock_instance.connect_ex.return_value = 0
            result = engine.probe("1.1.1.1", tcp_port=443)
            assert result.timeout is False
            assert result.method == "tcp"
            assert result.latency_ms is not None
            assert result.latency_ms >= 0

    def test_tcp_timeout(self):
        engine = ProbeEngine(method="tcp")
        with patch("app.modules.connection_monitor.probe.socket.socket") as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            mock_instance.connect_ex.side_effect = socket.timeout
            result = engine.probe("1.1.1.1", tcp_port=443)
            assert result.timeout is True
            assert result.latency_ms is None
            assert result.method == "tcp"

    def test_tcp_connection_refused(self):
        engine = ProbeEngine(method="tcp")
        with patch("app.modules.connection_monitor.probe.socket.socket") as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            mock_instance.connect_ex.return_value = 111  # ECONNREFUSED
            result = engine.probe("1.1.1.1", tcp_port=443)
            assert result.timeout is True
            assert result.latency_ms is None


class TestICMPProbe:
    def test_icmp_success(self):
        engine = ProbeEngine(method="icmp")
        with patch.object(engine, "_icmp_probe") as mock_icmp:
            mock_icmp.return_value = ProbeResult(
                latency_ms=5.2, timeout=False, method="icmp"
            )
            result = engine.probe("1.1.1.1")
            assert result.timeout is False
            assert result.latency_ms == 5.2
            assert result.method == "icmp"

    def test_icmp_timeout(self):
        engine = ProbeEngine(method="icmp")
        with patch.object(engine, "_icmp_probe") as mock_icmp:
            mock_icmp.return_value = ProbeResult(
                latency_ms=None, timeout=True, method="icmp"
            )
            result = engine.probe("1.1.1.1")
            assert result.timeout is True
            assert result.latency_ms is None
