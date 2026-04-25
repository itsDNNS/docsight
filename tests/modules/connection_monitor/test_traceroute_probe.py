"""Tests for the TracerouteProbe wrapper."""

import hashlib
import subprocess
from pathlib import Path
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


class TestIPv6Support:
    """Issue #363 — traceroute must accept IPv6 hop output and IPv6 targets."""

    def test_parse_ipv6_hops(self):
        """IPv6 textual addresses in hop lines must round-trip through the parser."""
        stdout = (
            "1\t2001:db8::1\t1.23\t3\n"
            "2\t*\t-1\t0\n"
            "3\t2606:4700:4700::1111\t12.34\t3\n"
        )
        completed = subprocess.CompletedProcess(
            args=[HELPER_PATH, "2606:4700:4700::1111", "30", "2000"],
            returncode=0,
            stdout=stdout,
            stderr="",
        )
        probe = TracerouteProbe()
        with patch(f"{MODULE}.subprocess.run", return_value=completed), \
             patch(f"{MODULE}.socket.gethostbyaddr", side_effect=OSError):
            result = probe.run("2606:4700:4700::1111")

        assert result.reached_target is True
        assert len(result.hops) == 3
        assert result.hops[0].hop_ip == "2001:db8::1"
        assert result.hops[0].latency_ms == 1.23
        assert result.hops[1].hop_ip is None
        assert result.hops[2].hop_ip == "2606:4700:4700::1111"
        assert result.hops[2].latency_ms == 12.34

    def test_route_fingerprint_with_ipv6(self):
        """SHA256 fingerprint includes IPv6 textual addresses unchanged."""
        stdout = (
            "1\t2001:db8::1\t1.23\t3\n"
            "2\t*\t-1\t0\n"
            "3\t2606:4700:4700::1111\t12.34\t3\n"
        )
        completed = subprocess.CompletedProcess(
            args=[HELPER_PATH, "2606:4700:4700::1111", "30", "2000"],
            returncode=0,
            stdout=stdout,
            stderr="",
        )
        expected = hashlib.sha256(
            "2001:db8::1|*|2606:4700:4700::1111".encode()
        ).hexdigest()
        probe = TracerouteProbe()
        with patch(f"{MODULE}.subprocess.run", return_value=completed), \
             patch(f"{MODULE}.socket.gethostbyaddr", side_effect=OSError):
            result = probe.run("2606:4700:4700::1111")

        assert result.route_fingerprint == expected

    def test_passes_ipv6_literal_to_helper_unchanged(self):
        """The helper must receive the IPv6 literal verbatim as argv[1]."""
        completed = subprocess.CompletedProcess(
            args=[HELPER_PATH, "2606:4700:4700::1111", "30", "2000"],
            returncode=0,
            stdout="1\t2606:4700:4700::1111\t5.00\t3\n",
            stderr="",
        )
        probe = TracerouteProbe()
        with patch(f"{MODULE}.subprocess.run", return_value=completed) as mock_run, \
             patch(f"{MODULE}.socket.gethostbyaddr", side_effect=OSError):
            probe.run("2606:4700:4700::1111")
        invoked = mock_run.call_args.args[0]
        assert invoked[0] == HELPER_PATH
        assert invoked[1] == "2606:4700:4700::1111"


def _strip_c_comments(src: str) -> str:
    """Remove C block and line comments from `src`.

    Structural order assertions on C source must look at code only — words
    inside comments would otherwise satisfy the regex and mask reordering
    bugs (or, as here, falsely report them).
    """
    import re

    # Block comments are stripped first so that "//" inside a /* ... */
    # cannot be mistaken for a line comment, and "/*" inside a // line
    # cannot swallow code on the next line.
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.DOTALL)
    src = re.sub(r"//[^\n]*", " ", src)
    return src


class TestHelperSource:
    """Issue #363 regression coverage: structural assertions on the C source.

    The C helper requires raw-socket privileges, so we cannot exercise it
    end-to-end in CI. These tests catch the IPv4-only regression structurally
    (mirroring the icmp_probe_helper.c gates in test_probe.py) and prove the
    helper still compiles cleanly with strict warnings."""

    HELPER_SRC = (
        Path(__file__).resolve().parents[3] / "tools" / "traceroute_helper.c"
    )

    def test_helper_source_handles_ipv6(self):
        """Source must reference the AF_INET6 / ICMPv6 surface, not just IPv4."""
        src = self.HELPER_SRC.read_text()
        assert "AF_UNSPEC" in src, "helper must resolve with AF_UNSPEC, not AF_INET"
        assert "AF_INET6" in src, "helper must open AF_INET6 sockets"
        assert "IPPROTO_ICMPV6" in src, "helper must speak IPPROTO_ICMPV6"
        assert "IPV6_UNICAST_HOPS" in src, (
            "helper must set the IPv6 hop limit (IPV6_UNICAST_HOPS), "
            "not only the IPv4 IP_TTL"
        )
        assert "INET6_ADDRSTRLEN" in src, (
            "helper must size address buffers for IPv6 (INET6_ADDRSTRLEN), "
            "not the IPv4-only INET_ADDRSTRLEN"
        )
        assert (
            "ICMP6_ECHO_REQUEST" in src or "128" in src
        ), "helper must send ICMPv6 echo request (type 128)"
        assert (
            "ICMP6_ECHO_REPLY" in src or "129" in src
        ), "helper must parse ICMPv6 echo reply (type 129)"
        assert "ICMP6_TIME_EXCEEDED" in src, (
            "helper must classify ICMPv6 Time Exceeded for hop discovery"
        )
        assert "inet_ntop(AF_INET6" in src, (
            "helper must format IPv6 hop addresses with inet_ntop(AF_INET6, ...)"
        )

    def test_helper_source_keeps_ipv4_path(self):
        """IPv4 behavior must be preserved alongside the new IPv6 path."""
        src = self.HELPER_SRC.read_text()
        assert "IPPROTO_ICMP" in src
        assert "IP_TTL" in src
        assert "ICMP_ECHO" in src
        assert "ICMP_TIME_EXCEEDED" in src
        assert "inet_ntop(AF_INET" in src

    def test_helper_compiles_with_strict_warnings(self, tmp_path):
        """Helper builds cleanly with -O2 -Wall -Werror."""
        binary = tmp_path / "docsight-traceroute-helper"
        compile_result = subprocess.run(
            ["gcc", "-O2", "-Wall", "-Werror",
             "-o", str(binary), str(self.HELPER_SRC)],
            capture_output=True,
            text=True,
        )
        assert compile_result.returncode == 0, compile_result.stderr
        assert binary.exists()

    def test_helper_drops_privileges_before_resolution(self):
        """Regression: NSS/DNS must run only after seteuid(getuid()).

        The setuid helper model requires raw-socket creation while euid
        is elevated, then an immediate privilege drop, and only then DNS
        resolution. A previous IPv6 patch reordered resolve_host() to
        run before the socket+seteuid sequence, which would invoke NSS
        modules as root. Inside main(), this test asserts the textual
        order open_icmp_socket(...) -> seteuid(...) -> resolve_host(...).
        """
        import re

        src = _strip_c_comments(self.HELPER_SRC.read_text())

        main_match = re.search(r"\bint\s+main\s*\(", src)
        assert main_match, "helper must define main()"
        main_body = src[main_match.start():]

        open_socket_calls = [
            m.start() for m in re.finditer(r"\bopen_icmp_socket\s*\(", main_body)
        ]
        seteuid_calls = [
            m.start()
            for m in re.finditer(r"\bseteuid\s*\(\s*getuid\s*\(", main_body)
        ]
        resolve_calls = [
            m.start() for m in re.finditer(r"\bresolve_host\s*\(", main_body)
        ]

        assert open_socket_calls, "main() must open raw sockets"
        assert seteuid_calls, (
            "main() must drop privileges with seteuid(getuid())"
        )
        assert resolve_calls, "main() must resolve the host"

        earliest_open = min(open_socket_calls)
        earliest_seteuid = min(seteuid_calls)
        earliest_resolve = min(resolve_calls)

        assert earliest_open < earliest_seteuid, (
            "Raw sockets must be opened BEFORE seteuid(getuid()); they "
            "require elevated privileges to create."
        )
        assert earliest_seteuid < earliest_resolve, (
            "seteuid(getuid()) must run BEFORE resolve_host(); NSS/DNS "
            "code in a setuid helper must execute only after the "
            "privilege drop."
        )

    def test_helper_opens_both_families_before_dropping_privileges(self):
        """Both AF_INET and AF_INET6 raw sockets must be opened up front.

        Because the resolver runs after the privilege drop, the family
        the resolver will choose is not known while euid is still
        elevated. The helper therefore must open both family sockets
        before seteuid(getuid()), and select between them after
        resolve_host() returns.
        """
        import re

        src = _strip_c_comments(self.HELPER_SRC.read_text())

        main_match = re.search(r"\bint\s+main\s*\(", src)
        assert main_match, "helper must define main()"
        main_body = src[main_match.start():]

        seteuid_match = re.search(
            r"\bseteuid\s*\(\s*getuid\s*\(", main_body
        )
        assert seteuid_match, "main() must drop privileges"
        before_drop = main_body[: seteuid_match.start()]

        assert re.search(r"open_icmp_socket\s*\(\s*AF_INET\s*\)", before_drop), (
            "main() must open the AF_INET raw socket before "
            "seteuid(getuid())"
        )
        assert re.search(r"open_icmp_socket\s*\(\s*AF_INET6\s*\)", before_drop), (
            "main() must open the AF_INET6 raw socket before "
            "seteuid(getuid())"
        )
