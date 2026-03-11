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
ICMP_HELPER_PATH = os.environ.get(
    "DOCSIGHT_ICMP_HELPER", "/usr/local/bin/docsight-icmp-helper"
)


@dataclass
class ProbeResult:
    """Result of a single probe attempt."""

    latency_ms: float | None  # None on timeout
    timeout: bool
    method: str  # "icmp" or "tcp"


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
        """Try ICMP raw socket; fall back to TCP if not permitted."""
        helper_reason = self._helper_check()
        if helper_reason is None:
            logger.info("ICMP helper available - using ICMP probing")
            return "icmp"
        try:
            with socket.socket(
                socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP
            ):
                pass
            logger.info("ICMP raw socket available - using ICMP probing")
            return "icmp"
        except (PermissionError, OSError) as exc:
            self._fallback_reason = helper_reason or str(exc)
            logger.warning(
                "ICMP raw socket not available (%s) - falling back to TCP",
                self._fallback_reason,
            )
            return "tcp"

    def capability_info(self) -> dict:
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
        """Measure TCP handshake latency."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(PROBE_TIMEOUT_S)
        try:
            start = time.monotonic()
            result_code = sock.connect_ex((host, port))
            elapsed = (time.monotonic() - start) * 1000
            if result_code == 0:
                return ProbeResult(
                    latency_ms=round(elapsed, 2), timeout=False, method="tcp"
                )
            return ProbeResult(latency_ms=None, timeout=True, method="tcp")
        except (socket.timeout, OSError):
            return ProbeResult(latency_ms=None, timeout=True, method="tcp")
        finally:
            sock.close()

    def _icmp_probe(self, host: str) -> ProbeResult:
        """Send ICMP echo request and measure round-trip time."""
        helper_result = self._icmp_probe_with_helper(host)
        if helper_result is not None:
            return helper_result

        try:
            dest = socket.gethostbyname(host)
        except socket.gaierror:
            return ProbeResult(latency_ms=None, timeout=True, method="icmp")

        sock = socket.socket(
            socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP
        )
        sock.settimeout(PROBE_TIMEOUT_S)
        try:
            self._seq = (self._seq + 1) & 0xFFFF
            packet = self._build_icmp_packet(
                seq=self._seq, ident=os.getpid() & 0xFFFF
            )
            start = time.monotonic()
            sock.sendto(packet, (dest, 0))
            while True:
                remaining = PROBE_TIMEOUT_S - (time.monotonic() - start)
                if remaining <= 0:
                    return ProbeResult(
                        latency_ms=None, timeout=True, method="icmp"
                    )
                sock.settimeout(remaining)
                data, _ = sock.recvfrom(1024)
                # Skip IP header (20 bytes), check ICMP type=0 (echo reply)
                icmp_header = data[20:28]
                icmp_type, _, _, pkt_id, pkt_seq = struct.unpack(
                    "!BBHHH", icmp_header
                )
                if (
                    icmp_type == 0
                    and pkt_id == (os.getpid() & 0xFFFF)
                    and pkt_seq == self._seq
                ):
                    elapsed = (time.monotonic() - start) * 1000
                    return ProbeResult(
                        latency_ms=round(elapsed, 2),
                        timeout=False,
                        method="icmp",
                    )
        except (socket.timeout, OSError):
            return ProbeResult(latency_ms=None, timeout=True, method="icmp")
        finally:
            sock.close()

    def _helper_check(self) -> str | None | bool:
        """Return None when helper is usable, otherwise reason/False."""
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
        except (OSError, subprocess.SubprocessError) as exc:
            return str(exc)
        if proc.returncode == 0:
            return None
        return (proc.stderr or proc.stdout or "helper check failed").strip()

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
        except (OSError, subprocess.SubprocessError) as exc:
            logger.debug("ICMP helper execution failed for %s: %s", host, exc)
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
                logger.debug("ICMP helper returned invalid latency for %s: %r", host, output)
                return None
        if proc.returncode == 1:
            return ProbeResult(latency_ms=None, timeout=True, method="icmp")

        logger.debug(
            "ICMP helper failed for %s: %s",
            host,
            (proc.stderr or output or f"exit {proc.returncode}").strip(),
        )
        return None

    @staticmethod
    def _build_icmp_packet(seq: int, ident: int) -> bytes:
        """Build ICMP echo request packet with checksum."""
        # Type 8 = echo request, code 0
        header = struct.pack("!BBHHH", 8, 0, 0, ident, seq)
        payload = b"\x00" * 32
        checksum = ProbeEngine._icmp_checksum(header + payload)
        header = struct.pack("!BBHHH", 8, 0, checksum, ident, seq)
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
