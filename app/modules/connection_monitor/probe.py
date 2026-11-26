"""Probe engine for Connection Monitor - ICMP and TCP latency probing."""

import logging
import os
import socket
import struct
import subprocess
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

PROBE_TIMEOUT_S = 2.0
ICMP_UNAVAILABLE_REASON = "ICMP probing is unavailable"
ICMP_HELPER_PATH = os.environ.get(
    "DOCSIGHT_ICMP_HELPER", "/usr/local/bin/docsight-icmp-helper"
)
# family -> (protocol, echo request type, echo reply type, ICMP header offset).
# IPv4 raw sockets deliver the 20-byte IP header, IPv6 raw sockets do not.
_RAW_ICMP = {
    socket.AF_INET: (socket.IPPROTO_ICMP, 8, 0, 20),
    socket.AF_INET6: (socket.IPPROTO_ICMPV6, 128, 129, 0),
}


@dataclass
class ProbeResult:
    """Result of a single probe attempt."""

    latency_ms: float | None  # None on timeout
    timeout: bool
    method: str  # "icmp" or "tcp"


def timeout_result(method: str) -> ProbeResult:
    """A probe that got no answer."""
    return ProbeResult(latency_ms=None, timeout=True, method=method)


def _resolve_all(
    host: str, port: int | None, sock_type: int
) -> list[tuple[int, tuple]]:
    """Resolve host with AF_UNSPEC, returning every usable (family, sockaddr).

    Raw sockets have no service, and glibc returns ``EAI_SERVICE`` when
    ``port`` is numeric for ``SOCK_RAW``, so raw callers must pass ``None``.
    """
    service: int | None = None if sock_type == socket.SOCK_RAW else port
    try:
        infos = socket.getaddrinfo(host, service, socket.AF_UNSPEC, sock_type)
    except socket.gaierror:
        return []
    return [
        (info[0], info[4])
        for info in infos
        if info[0] in (socket.AF_INET, socket.AF_INET6)
    ]


class ProbeEngine:
    """Probes targets via ICMP or TCP with auto-detection."""

    def __init__(self, method: str = "auto"):
        self._fallback_reason: str | None = None
        self._helper_path = ICMP_HELPER_PATH
        self._helper_available = (
            os.path.isfile(self._helper_path) and os.access(self._helper_path, os.X_OK)
        )
        if method == "auto":
            self.detected_method = self._detect_method()
        elif method in ("icmp", "tcp"):
            self.detected_method = method
        else:
            raise ValueError(f"Unknown probe method: {method}")
        self._seq = 0

    def _detect_method(self) -> str:
        """Try the ICMP helper and raw socket before falling back to TCP."""
        if self._helper_check():
            logger.info("ICMP helper available - using ICMP probing")
            return "icmp"
        try:
            with socket.socket(
                socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP
            ):
                pass
            logger.info("ICMP raw socket available - using ICMP probing")
            return "icmp"
        except OSError:
            self._fallback_reason = ICMP_UNAVAILABLE_REASON
            logger.warning("ICMP probing is unavailable - falling back to TCP")
            return "tcp"

    def capability_info(self) -> dict[str, str]:
        """Return probe method info for the UI."""
        info = {"method": self.detected_method}
        if self._fallback_reason is not None:
            info["reason"] = self._fallback_reason
            info["hint"] = (
                "Add cap_add: [NET_RAW] to your Docker Compose file "
                "for ICMP probing (more accurate)."
            )
        return info

    def probe(self, host: str, tcp_port: int = 443) -> ProbeResult:
        """Run a single probe against the target."""
        if self.detected_method == "icmp":
            return self._icmp_probe(host)
        return self._tcp_probe(host, tcp_port)

    def _tcp_probe(self, host: str, port: int) -> ProbeResult:
        """Measure TCP handshake latency, iterating over resolved addresses."""
        addresses = _resolve_all(host, port, socket.SOCK_STREAM)
        if not addresses:
            return timeout_result("tcp")
        for family, sockaddr in addresses:
            try:
                sock = socket.socket(family, socket.SOCK_STREAM)
            except OSError:
                continue
            try:
                sock.settimeout(PROBE_TIMEOUT_S)
                start = time.monotonic()
                result_code = sock.connect_ex(sockaddr)
                elapsed = (time.monotonic() - start) * 1000
                if result_code == 0:
                    return ProbeResult(
                        latency_ms=round(elapsed, 2),
                        timeout=False,
                        method="tcp",
                    )
            except OSError:
                pass
            finally:
                sock.close()
        return timeout_result("tcp")

    def _icmp_probe(self, host: str) -> ProbeResult:
        """Send ICMP/ICMPv6 echo request and measure round-trip time.

        Iterates every resolved (family, sockaddr) so a dual-stack host is not
        short-circuited to a timeout when the first usable family is broken —
        e.g. IPv6 socket unsupported, IPv6 route missing, or sendto hitting
        ENETUNREACH. Mirrors :meth:`_tcp_probe`.
        """
        helper_result = self._icmp_probe_with_helper(host)
        if helper_result is not None:
            return helper_result

        addresses = _resolve_all(host, None, socket.SOCK_RAW)
        if not addresses:
            return timeout_result("icmp")

        for family, sockaddr in addresses:
            result = self._icmp_raw(family, sockaddr)
            if not result.timeout:
                return result
        return timeout_result("icmp")

    def _icmp_raw(self, family: int, sockaddr: tuple) -> ProbeResult:
        """Raw-socket ICMP/ICMPv6 echo. Requires CAP_NET_RAW or root."""
        proto, request, reply, offset = _RAW_ICMP[family]
        try:
            sock = socket.socket(family, socket.SOCK_RAW, proto)
            with sock:
                sock.settimeout(PROBE_TIMEOUT_S)
                self._seq = (self._seq + 1) & 0xFFFF
                ident = os.getpid() & 0xFFFF
                packet = self._build_icmp_packet(seq=self._seq, ident=ident, type_=request)
                start = time.monotonic()
                sock.sendto(packet, (sockaddr[0], 0) if family == socket.AF_INET else sockaddr)
                while (remaining := PROBE_TIMEOUT_S - (time.monotonic() - start)) > 0:
                    sock.settimeout(remaining)
                    data, _ = sock.recvfrom(1024)
                    if len(data) < offset + 8:
                        continue
                    icmp_type, _, _, pkt_id, pkt_seq = struct.unpack(
                        "!BBHHH", data[offset:offset + 8]
                    )
                    if icmp_type == reply and pkt_id == ident and pkt_seq == self._seq:
                        elapsed = (time.monotonic() - start) * 1000
                        return ProbeResult(
                            latency_ms=round(elapsed, 2),
                            timeout=False,
                            method="icmp",
                        )
        except OSError:
            pass
        return timeout_result("icmp")

    def _helper_check(self) -> bool:
        """Return whether the configured helper is usable."""
        if not self._helper_available:
            return False
        try:
            proc = subprocess.run(
                [self._helper_path, "--check"],
                capture_output=True,
                text=True,
                timeout=PROBE_TIMEOUT_S + 1,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return proc.returncode == 0

    def _icmp_probe_with_helper(self, host: str) -> ProbeResult | None:
        """Run a single ICMP probe via the dedicated helper when present."""
        if not self._helper_available:
            return None
        try:
            proc = subprocess.run(
                [self._helper_path, host, str(int(PROBE_TIMEOUT_S * 1000))],
                capture_output=True,
                text=True,
                timeout=PROBE_TIMEOUT_S + 1,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            logger.debug("ICMP helper execution failed")
            return None

        output = (proc.stdout or "").strip()
        if proc.returncode == 0:
            try:
                return ProbeResult(
                    latency_ms=round(float(output), 2),
                    timeout=False,
                    method="icmp",
                )
            except ValueError:
                logger.debug("ICMP helper returned invalid latency")
                return None
        if proc.returncode == 1:
            return timeout_result("icmp")

        logger.debug("ICMP helper probe failed")
        return None

    @staticmethod
    def _build_icmp_packet(seq: int, ident: int, type_: int = 8) -> bytes:
        """Build an ICMP/ICMPv6 echo request packet.

        ICMPv4 requires a software checksum; the Linux kernel writes the
        ICMPv6 checksum on AF_INET6 raw sockets, so a zero checksum is fine.
        """
        header = struct.pack("!BBHHH", type_, 0, 0, ident, seq)
        payload = b"\x00" * 32
        if type_ == 8:
            checksum = ProbeEngine._icmp_checksum(header + payload)
            header = struct.pack("!BBHHH", type_, 0, checksum, ident, seq)
        return header + payload

    @staticmethod
    def _icmp_checksum(data: bytes) -> int:
        """Compute ICMP checksum per RFC 1071."""
        if len(data) % 2:
            data += b"\x00"
        total = 0
        for i in range(0, len(data), 2):
            total += (data[i] << 8) + data[i + 1]
        total = (total >> 16) + (total & 0xFFFF)
        total += total >> 16
        return ~total & 0xFFFF
