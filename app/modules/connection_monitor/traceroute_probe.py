from dataclasses import dataclass
import hashlib
import logging
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

log = logging.getLogger("docsis.traceroute")

HELPER_PATH = "/usr/local/bin/docsight-traceroute-helper"

@dataclass
class TracerouteHop:
    hop_index: int
    hop_ip: str | None
    hop_host: str | None
    latency_ms: float | None
    probes_responded: int

@dataclass
class TracerouteResult:
    hops: list[TracerouteHop]
    reached_target: bool
    route_fingerprint: str

class TracerouteProbe:
    TOTAL_TIMEOUT_S = 30
    DNS_TIMEOUT_S = 3.0

    def check(self) -> bool:
        try:
            r = subprocess.run([HELPER_PATH, "--check"], capture_output=True, timeout=5)
            return r.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def run(self, host: str, max_hops: int = 30, timeout_ms: int = 2000) -> TracerouteResult:
        try:
            result = subprocess.run(
                [HELPER_PATH, host, str(max_hops), str(timeout_ms)],
                capture_output=True, text=True, timeout=self.TOTAL_TIMEOUT_S,
            )
            stdout = result.stdout
            reached = result.returncode == 0
        except subprocess.TimeoutExpired as e:
            stdout = e.stdout or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")
            reached = False
            log.warning("Traceroute to %s timed out after %ds", host, self.TOTAL_TIMEOUT_S)
        except FileNotFoundError:
            log.error("Traceroute helper not found at %s", HELPER_PATH)
            return TracerouteResult(hops=[], reached_target=False, route_fingerprint="")
        except Exception as e:
            log.error("Traceroute failed: %s", e)
            return TracerouteResult(hops=[], reached_target=False, route_fingerprint="")

        hops = self._parse_output(stdout)
        hops = self._resolve_dns(hops)
        fingerprint = self._compute_fingerprint(hops)
        return TracerouteResult(hops=hops, reached_target=reached, route_fingerprint=fingerprint)

    def _parse_output(self, stdout: str) -> list[TracerouteHop]:
        hops = []
        for line in stdout.strip().splitlines():
            parts = line.split("\t")
            if len(parts) < 4:
                continue
            hop_index = int(parts[0])
            hop_ip = None if parts[1] == "*" else parts[1]
            latency_ms = None if parts[2] == "-1" else float(parts[2])
            probes_responded = int(parts[3])
            hops.append(TracerouteHop(
                hop_index=hop_index, hop_ip=hop_ip, hop_host=None,
                latency_ms=latency_ms, probes_responded=probes_responded,
            ))
        return hops

    def _resolve_dns(self, hops: list[TracerouteHop]) -> list[TracerouteHop]:
        ips_to_resolve = {h.hop_ip for h in hops if h.hop_ip}
        if not ips_to_resolve:
            return hops
        dns_map: dict[str, str | None] = {}
        def _lookup(ip: str) -> tuple[str, str | None]:
            try:
                host, _, _ = socket.gethostbyaddr(ip)
                return ip, host
            except (socket.herror, socket.gaierror, OSError):
                return ip, None
        pool = ThreadPoolExecutor(max_workers=min(len(ips_to_resolve), 16))
        futures = {pool.submit(_lookup, ip): ip for ip in ips_to_resolve}
        try:
            for future in as_completed(futures, timeout=self.DNS_TIMEOUT_S):
                try:
                    ip, host = future.result(timeout=0.1)
                    dns_map[ip] = host
                except Exception:
                    dns_map[futures[future]] = None
        except TimeoutError:
            pass
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        for h in hops:
            if h.hop_ip:
                h.hop_host = dns_map.get(h.hop_ip)
        return hops

    @staticmethod
    def _compute_fingerprint(hops: list[TracerouteHop]) -> str:
        parts = [h.hop_ip if h.hop_ip else "*" for h in hops]
        return hashlib.sha256("|".join(parts).encode()).hexdigest()
