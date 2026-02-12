"""Built-in ping/latency monitor for DOCSight.

Runs periodic ICMP or TCP pings to configurable targets and stores results
for correlation with DOCSIS error data. Also computes a gaming/real-time
quality index based on jitter, packet loss bursts, and stability.
"""

import logging
import platform
import re
import subprocess
import threading
import time
from dataclasses import dataclass

log = logging.getLogger("docsis.ping")

# Defaults
DEFAULT_TARGETS = ["8.8.8.8", "1.1.1.1"]
DEFAULT_INTERVAL = 60  # seconds between ping rounds
DEFAULT_COUNT = 5       # pings per target per round


@dataclass
class PingResult:
    """Result of pinging a single target."""
    target: str
    timestamp: str
    avg_ms: float
    min_ms: float
    max_ms: float
    jitter_ms: float
    loss_pct: float
    count: int


def _parse_ping_output(output: str, target: str, count: int) -> PingResult | None:
    """Parse system ping command output (Linux/macOS/Windows)."""
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")

    # Try Linux/macOS format first
    rtt_match = re.search(
        r"rtt min/avg/max/mdev = ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)",
        output,
    )
    if rtt_match:
        min_ms = float(rtt_match.group(1))
        avg_ms = float(rtt_match.group(2))
        max_ms = float(rtt_match.group(3))
        jitter_ms = float(rtt_match.group(4))
    else:
        # Windows format
        rtt_match = re.search(
            r"Minimum = (\d+)ms, Maximum = (\d+)ms, Average = (\d+)ms",
            output,
        )
        if not rtt_match:
            # Try German Windows
            rtt_match = re.search(
                r"Minimum = (\d+)ms, Maximum = (\d+)ms, Mittelwert = (\d+)ms",
                output,
            )
        if rtt_match:
            min_ms = float(rtt_match.group(1))
            max_ms = float(rtt_match.group(2))
            avg_ms = float(rtt_match.group(3))
            jitter_ms = max_ms - min_ms
        else:
            return None

    # Parse loss
    loss_match = re.search(r"(\d+(?:\.\d+)?)% (?:packet )?loss", output, re.IGNORECASE)
    if not loss_match:
        loss_match = re.search(r"(\d+)% Verlust", output)
    loss_pct = float(loss_match.group(1)) if loss_match else 0.0

    return PingResult(
        target=target,
        timestamp=ts,
        avg_ms=avg_ms,
        min_ms=min_ms,
        max_ms=max_ms,
        jitter_ms=jitter_ms,
        loss_pct=loss_pct,
        count=count,
    )


def ping_target(target: str, count: int = DEFAULT_COUNT, timeout: int = 5) -> PingResult | None:
    """Ping a target and return parsed result."""
    system = platform.system().lower()
    try:
        if system == "windows":
            cmd = ["ping", "-n", str(count), "-w", str(timeout * 1000), target]
        else:
            cmd = ["ping", "-c", str(count), "-W", str(timeout), target]

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=count * timeout + 10,
        )
        return _parse_ping_output(result.stdout, target, count)
    except subprocess.TimeoutExpired:
        log.warning("Ping to %s timed out", target)
        return PingResult(
            target=target,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
            avg_ms=0, min_ms=0, max_ms=0, jitter_ms=0,
            loss_pct=100.0, count=count,
        )
    except Exception as e:
        log.error("Ping to %s failed: %s", target, e)
        return None


class PingMonitor:
    """Background ping monitor that runs periodic pings to configured targets."""

    def __init__(self, storage=None, targets=None, interval=DEFAULT_INTERVAL,
                 count=DEFAULT_COUNT):
        self.storage = storage
        self.targets = targets or DEFAULT_TARGETS
        self.interval = interval
        self.count = count
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._latest: dict[str, PingResult] = {}
        self._lock = threading.Lock()

    @property
    def latest(self) -> dict[str, PingResult]:
        """Return latest ping results per target."""
        with self._lock:
            return dict(self._latest)

    def start(self):
        """Start the background ping loop."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        log.info("Ping monitor started (targets=%s, interval=%ds)", self.targets, self.interval)

    def stop(self):
        """Stop the background ping loop."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=30)
        log.info("Ping monitor stopped")

    def run_once(self) -> list[PingResult]:
        """Run one round of pings immediately. Returns results."""
        results = []
        for target in self.targets:
            result = ping_target(target, self.count)
            if result:
                results.append(result)
                with self._lock:
                    self._latest[target] = result
                if self.storage:
                    self.storage.save_ping_result(result.__dict__)
        return results

    def _loop(self):
        """Background ping loop."""
        while not self._stop_event.is_set():
            try:
                self.run_once()
            except Exception as e:
                log.error("Ping monitor error: %s", e)

            for _ in range(self.interval):
                if self._stop_event.is_set():
                    break
                time.sleep(1)

    def get_stats(self, hours: int = 24) -> dict:
        """Get aggregated ping stats for all targets over the last N hours."""
        if not self.storage:
            # Return from in-memory latest
            results = list(self._latest.values())
            if not results:
                return {}
            avg_ms = sum(r.avg_ms for r in results) / len(results)
            avg_loss = sum(r.loss_pct for r in results) / len(results)
            avg_jitter = sum(r.jitter_ms for r in results) / len(results)
            return {
                "avg_ms": round(avg_ms, 1),
                "loss_pct": round(avg_loss, 1),
                "jitter_ms": round(avg_jitter, 1),
                "targets": len(results),
            }
        return self.storage.get_ping_stats(hours)

    def compute_gaming_index(self, hours: int = 1) -> dict:
        """Compute a gaming/real-time quality index (0-100).

        Based on:
            - Latency (40% weight): < 20ms = 100, > 100ms = 0
            - Jitter (30% weight): < 5ms = 100, > 50ms = 0
            - Packet loss (30% weight): 0% = 100, > 5% = 0

        Returns dict with score, grade (A-F), and components.
        """
        stats = self.get_stats(hours)
        if not stats:
            return {"score": 0, "grade": "?", "components": {}}

        avg_ms = stats.get("avg_ms", 0)
        jitter = stats.get("jitter_ms", 0)
        loss = stats.get("loss_pct", 0)

        # Latency score
        if avg_ms <= 20:
            lat_score = 100
        elif avg_ms >= 100:
            lat_score = 0
        else:
            lat_score = 100 - ((avg_ms - 20) / 80) * 100

        # Jitter score
        if jitter <= 5:
            jit_score = 100
        elif jitter >= 50:
            jit_score = 0
        else:
            jit_score = 100 - ((jitter - 5) / 45) * 100

        # Packet loss score
        if loss <= 0:
            loss_score = 100
        elif loss >= 5:
            loss_score = 0
        else:
            loss_score = 100 - (loss / 5) * 100

        score = round(0.4 * lat_score + 0.3 * jit_score + 0.3 * loss_score, 1)

        if score >= 90:
            grade = "A"
        elif score >= 75:
            grade = "B"
        elif score >= 60:
            grade = "C"
        elif score >= 40:
            grade = "D"
        else:
            grade = "F"

        return {
            "score": score,
            "grade": grade,
            "components": {
                "latency_score": round(lat_score, 1),
                "jitter_score": round(jit_score, 1),
                "loss_score": round(loss_score, 1),
                "avg_ms": avg_ms,
                "jitter_ms": jitter,
                "loss_pct": loss,
            },
        }
