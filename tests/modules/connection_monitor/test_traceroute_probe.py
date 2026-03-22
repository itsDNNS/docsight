"""Tests for the TracerouteProbe wrapper."""

import hashlib
import subprocess
from unittest.mock import patch, MagicMock

import pytest

from app.modules.connection_monitor.traceroute_probe import (
    TracerouteProbe,
    TracerouteHop,
    TracerouteResult,
    HELPER_PATH,
)

MODULE = "app.modules.connection_monitor.traceroute_probe"


class TestParseOutput:
    def test_parse_successful_trace(self):
        """Normal output with 3 hops reaching target."""
        stdout = (
            "1\t192.168.1.1\t1.23\t3\n"
            "2\t10.0.0.1\t5.67\t3\n"
            "3\t8.8.8.8\t12.34\t3\n"
        )
        completed = subprocess.CompletedProcess(
            args=[HELPER_PATH, "8.8.8.8", "30", "2000"],
            returncode=0,
            stdout=stdout,
            stderr="",
        )
        probe = TracerouteProbe()
        with patch(f"{MODULE}.subprocess.run", return_value=completed), \
             patch(f"{MODULE}.socket.gethostbyaddr", side_effect=OSError):
            result = probe.run("8.8.8.8")

        assert result.reached_target is True
        assert len(result.hops) == 3
        assert result.hops[0].hop_index == 1
        assert result.hops[0].hop_ip == "192.168.1.1"
        assert result.hops[0].latency_ms == 1.23
        assert result.hops[0].probes_responded == 3
        assert result.hops[2].hop_ip == "8.8.8.8"
        assert result.hops[2].latency_ms == 12.34

    def test_parse_timeout_hops(self):
        """Output with * timeout hops mixed in."""
        stdout = (
            "1\t192.168.1.1\t1.23\t3\n"
            "2\t*\t-1\t0\n"
            "3\t8.8.8.8\t12.34\t3\n"
        )
        completed = subprocess.CompletedProcess(
            args=[HELPER_PATH, "8.8.8.8", "30", "2000"],
            returncode=0,
            stdout=stdout,
            stderr="",
        )
        probe = TracerouteProbe()
        with patch(f"{MODULE}.subprocess.run", return_value=completed), \
             patch(f"{MODULE}.socket.gethostbyaddr", side_effect=OSError):
            result = probe.run("8.8.8.8")

        assert result.reached_target is True
        assert len(result.hops) == 3
        assert result.hops[1].hop_ip is None
        assert result.hops[1].latency_ms is None
        assert result.hops[1].probes_responded == 0

    def test_parse_partial_probes(self):
        """Hops with probes_responded < 3."""
        stdout = (
            "1\t192.168.1.1\t2.50\t2\n"
            "2\t10.0.0.1\t8.00\t1\n"
            "3\t8.8.8.8\t15.00\t3\n"
        )
        completed = subprocess.CompletedProcess(
            args=[HELPER_PATH, "8.8.8.8", "30", "2000"],
            returncode=0,
            stdout=stdout,
            stderr="",
        )
        probe = TracerouteProbe()
        with patch(f"{MODULE}.subprocess.run", return_value=completed), \
             patch(f"{MODULE}.socket.gethostbyaddr", side_effect=OSError):
            result = probe.run("8.8.8.8")

        assert result.reached_target is True
        assert result.hops[0].probes_responded == 2
        assert result.hops[1].probes_responded == 1
        assert result.hops[2].probes_responded == 3


class TestErrorHandling:
    def test_target_not_reached(self):
        """Max hops exceeded, exit code 1."""
        stdout = (
            "1\t192.168.1.1\t1.23\t3\n"
            "2\t10.0.0.1\t5.67\t3\n"
            "3\t*\t-1\t0\n"
        )
        completed = subprocess.CompletedProcess(
            args=[HELPER_PATH, "8.8.8.8", "30", "2000"],
            returncode=1,
            stdout=stdout,
            stderr="",
        )
        probe = TracerouteProbe()
        with patch(f"{MODULE}.subprocess.run", return_value=completed), \
             patch(f"{MODULE}.socket.gethostbyaddr", side_effect=OSError):
            result = probe.run("8.8.8.8")

        assert result.reached_target is False
        assert len(result.hops) == 3

    def test_helper_error(self):
        """Exit code 2 with no parseable output returns empty result."""
        completed = subprocess.CompletedProcess(
            args=[HELPER_PATH, "8.8.8.8", "30", "2000"],
            returncode=2,
            stdout="",
            stderr="fatal error\n",
        )
        probe = TracerouteProbe()
        with patch(f"{MODULE}.subprocess.run", return_value=completed):
            result = probe.run("8.8.8.8")

        assert result.reached_target is False
        assert result.hops == []
        assert result.route_fingerprint != ""  # SHA256 of empty parts list

    def test_helper_not_found(self):
        """FileNotFoundError returns empty result."""
        probe = TracerouteProbe()
        with patch(f"{MODULE}.subprocess.run", side_effect=FileNotFoundError):
            result = probe.run("8.8.8.8")

        assert result.reached_target is False
        assert result.hops == []
        assert result.route_fingerprint == ""

    def test_timeout_partial_results(self):
        """subprocess.TimeoutExpired with partial stdout."""
        partial_stdout = (
            "1\t192.168.1.1\t1.23\t3\n"
            "2\t10.0.0.1\t5.67\t3\n"
        )
        exc = subprocess.TimeoutExpired(
            cmd=[HELPER_PATH, "8.8.8.8", "30", "2000"],
            timeout=30,
        )
        exc.stdout = partial_stdout
        probe = TracerouteProbe()
        with patch(f"{MODULE}.subprocess.run", side_effect=exc), \
             patch(f"{MODULE}.socket.gethostbyaddr", side_effect=OSError):
            result = probe.run("8.8.8.8")

        assert result.reached_target is False
        assert len(result.hops) == 2
        assert result.hops[0].hop_ip == "192.168.1.1"
        assert result.hops[1].hop_ip == "10.0.0.1"


class TestRouteFingerprint:
    def test_route_fingerprint(self):
        """Verify SHA256 with * sentinel for timeout hops."""
        stdout = (
            "1\t192.168.1.1\t1.23\t3\n"
            "2\t*\t-1\t0\n"
            "3\t8.8.8.8\t12.34\t3\n"
        )
        completed = subprocess.CompletedProcess(
            args=[HELPER_PATH, "8.8.8.8", "30", "2000"],
            returncode=0,
            stdout=stdout,
            stderr="",
        )
        expected = hashlib.sha256("192.168.1.1|*|8.8.8.8".encode()).hexdigest()
        probe = TracerouteProbe()
        with patch(f"{MODULE}.subprocess.run", return_value=completed), \
             patch(f"{MODULE}.socket.gethostbyaddr", side_effect=OSError):
            result = probe.run("8.8.8.8")

        assert result.route_fingerprint == expected


class TestReverseDNS:
    def test_reverse_dns_parallel(self):
        """Mock socket.gethostbyaddr, verify parallel execution."""
        stdout = (
            "1\t192.168.1.1\t1.23\t3\n"
            "2\t10.0.0.1\t5.67\t3\n"
            "3\t8.8.8.8\t12.34\t3\n"
        )
        completed = subprocess.CompletedProcess(
            args=[HELPER_PATH, "8.8.8.8", "30", "2000"],
            returncode=0,
            stdout=stdout,
            stderr="",
        )

        def fake_gethostbyaddr(ip: str):
            dns_map = {
                "192.168.1.1": ("gateway.local", [], ["192.168.1.1"]),
                "10.0.0.1": ("router.isp.net", [], ["10.0.0.1"]),
                "8.8.8.8": ("dns.google", [], ["8.8.8.8"]),
            }
            if ip in dns_map:
                return dns_map[ip]
            raise OSError("not found")

        probe = TracerouteProbe()
        with patch(f"{MODULE}.subprocess.run", return_value=completed), \
             patch(f"{MODULE}.socket.gethostbyaddr", side_effect=fake_gethostbyaddr):
            result = probe.run("8.8.8.8")

        assert result.hops[0].hop_host == "gateway.local"
        assert result.hops[1].hop_host == "router.isp.net"
        assert result.hops[2].hop_host == "dns.google"

    def test_reverse_dns_timeout(self):
        """DNS lookup times out, hop_host is None."""
        stdout = (
            "1\t192.168.1.1\t1.23\t3\n"
            "2\t10.0.0.1\t5.67\t3\n"
        )
        completed = subprocess.CompletedProcess(
            args=[HELPER_PATH, "8.8.8.8", "30", "2000"],
            returncode=0,
            stdout=stdout,
            stderr="",
        )
        probe = TracerouteProbe()
        with patch(f"{MODULE}.subprocess.run", return_value=completed), \
             patch(f"{MODULE}.socket.gethostbyaddr", side_effect=OSError("timeout")):
            result = probe.run("8.8.8.8")

        assert result.hops[0].hop_host is None
        assert result.hops[1].hop_host is None
