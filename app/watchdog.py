"""Watchdog module for DOCSight – monitors modulation changes, power drift,
upstream channel count, and ingress/return path scoring.

Watches for:
    - Modulation drops per channel (e.g. 256QAM → 16QAM)
    - Power level drift (relative change over time window)
    - Upstream channel count drops
    - Ingress/return path composite score

All events are stored in the database and can trigger notifications.
"""

import logging
import time
from dataclasses import dataclass, field, asdict

log = logging.getLogger("docsis.watchdog")

# QAM order for modulation comparisons (higher = better)
QAM_ORDER = {
    "4096QAM": 12,
    "2048QAM": 11,
    "1024QAM": 10,
    "512QAM": 9,
    "256QAM": 8,
    "128QAM": 7,
    "64QAM": 6,
    "32QAM": 5,
    "16QAM": 4,
    "8QAM": 3,
    "QPSK": 2,
    "BPSK": 1,
}

# Ingress/Return Path scoring weights
INGRESS_WEIGHTS = {
    "us_power": 0.4,       # upstream power level
    "us_modulation": 0.3,  # upstream modulation quality
    "us_channel_count": 0.3,  # channel count relative to baseline
}


@dataclass
class WatchdogEvent:
    """Represents a single watchdog event."""
    timestamp: str
    event_type: str  # modulation_drop, power_drift, channel_count_drop, ingress_warning
    channel_id: int | None
    direction: str | None   # "ds" or "us"
    message: str
    severity: str  # "info", "warning", "critical"
    details: dict = field(default_factory=dict)


class Watchdog:
    """Track signal changes and generate alert events."""

    def __init__(self, storage=None, notifier=None):
        self.storage = storage
        self.notifier = notifier

        # State tracking
        self._prev_modulations: dict[str, str] = {}  # "ds_3" -> "256QAM"
        self._prev_us_count: int | None = None
        self._prev_ds_count: int | None = None

        # Power drift tracking: key -> list of (timestamp, value)
        self._power_history: dict[str, list[tuple[float, float]]] = {}
        self._drift_window_seconds = 86400  # 24 hours
        self._drift_threshold_db = 3.0  # alert on +/- 3 dB change in window

        # Baseline upstream channel count (set from first observation)
        self._us_baseline_count: int | None = None

    def check(self, analysis: dict) -> list[WatchdogEvent]:
        """Run all watchdog checks on a new analysis result.

        Returns list of events (may be empty).
        """
        events = []
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        now_ts = time.time()

        ds_channels = analysis.get("ds_channels", [])
        us_channels = analysis.get("us_channels", [])

        # --- Modulation Watchdog ---
        events.extend(self._check_modulations(ds_channels, us_channels, now))

        # --- Upstream Channel Count ---
        events.extend(self._check_channel_count(us_channels, now))

        # --- Power Level Drift ---
        events.extend(self._check_power_drift(analysis, now, now_ts))

        # --- Notify ---
        for event in events:
            if self.notifier and self.notifier.is_configured():
                self.notifier.send(
                    title=event.message,
                    message=f"Type: {event.event_type}\nSeverity: {event.severity}",
                    level=event.severity,
                    dedup_key=f"{event.event_type}_{event.channel_id}_{event.direction}",
                )

            # Store event
            if self.storage:
                self.storage.save_watchdog_event(asdict(event))

        return events

    def _check_modulations(self, ds_channels, us_channels, now) -> list[WatchdogEvent]:
        """Detect QAM modulation drops per channel."""
        events = []

        for ch in ds_channels:
            key = f"ds_{ch['channel_id']}"
            mod = ch.get("modulation", "")
            prev = self._prev_modulations.get(key)
            if prev and mod and prev != mod:
                prev_rank = QAM_ORDER.get(prev, 0)
                curr_rank = QAM_ORDER.get(mod, 0)
                if curr_rank < prev_rank:
                    events.append(WatchdogEvent(
                        timestamp=now,
                        event_type="modulation_drop",
                        channel_id=ch["channel_id"],
                        direction="ds",
                        message=f"DS CH{ch['channel_id']} modulation dropped: {prev} → {mod}",
                        severity="warning",
                        details={"previous": prev, "current": mod},
                    ))
            if mod:
                self._prev_modulations[key] = mod

        for ch in us_channels:
            key = f"us_{ch['channel_id']}"
            mod = ch.get("modulation", "")
            prev = self._prev_modulations.get(key)
            if prev and mod and prev != mod:
                prev_rank = QAM_ORDER.get(prev, 0)
                curr_rank = QAM_ORDER.get(mod, 0)
                if curr_rank < prev_rank:
                    events.append(WatchdogEvent(
                        timestamp=now,
                        event_type="modulation_drop",
                        channel_id=ch["channel_id"],
                        direction="us",
                        message=f"US CH{ch['channel_id']} modulation dropped: {prev} → {mod}",
                        severity="warning",
                        details={"previous": prev, "current": mod},
                    ))
            if mod:
                self._prev_modulations[key] = mod

        return events

    def _check_channel_count(self, us_channels, now) -> list[WatchdogEvent]:
        """Alert when upstream channel count drops."""
        events = []
        count = len(us_channels)

        if self._us_baseline_count is None:
            self._us_baseline_count = count
            self._prev_us_count = count
            return events

        if self._prev_us_count is not None and count < self._prev_us_count:
            severity = "critical" if count <= 1 else "warning"
            events.append(WatchdogEvent(
                timestamp=now,
                event_type="channel_count_drop",
                channel_id=None,
                direction="us",
                message=f"Upstream channels dropped: {self._prev_us_count} → {count}",
                severity=severity,
                details={
                    "previous": self._prev_us_count,
                    "current": count,
                    "baseline": self._us_baseline_count,
                },
            ))

        self._prev_us_count = count
        return events

    def _check_power_drift(self, analysis, now, now_ts) -> list[WatchdogEvent]:
        """Detect power level drift over the configured window."""
        events = []
        summary = analysis.get("summary", {})

        tracked_metrics = {
            "ds_power_avg": ("ds", "DS Power Avg"),
            "us_power_avg": ("us", "US Power Avg"),
        }

        for metric, (direction, label) in tracked_metrics.items():
            value = summary.get(metric)
            if value is None:
                continue

            if metric not in self._power_history:
                self._power_history[metric] = []

            history = self._power_history[metric]
            history.append((now_ts, value))

            # Prune old entries
            cutoff = now_ts - self._drift_window_seconds
            self._power_history[metric] = [
                (t, v) for t, v in history if t >= cutoff
            ]
            history = self._power_history[metric]

            if len(history) < 2:
                continue

            oldest_val = history[0][1]
            drift = value - oldest_val

            if abs(drift) >= self._drift_threshold_db:
                direction_str = "increased" if drift > 0 else "decreased"
                events.append(WatchdogEvent(
                    timestamp=now,
                    event_type="power_drift",
                    channel_id=None,
                    direction=direction,
                    message=f"{label} {direction_str} by {abs(drift):.1f} dB in {self._drift_window_seconds // 3600}h",
                    severity="warning",
                    details={
                        "metric": metric,
                        "drift_db": round(drift, 1),
                        "window_hours": self._drift_window_seconds // 3600,
                        "from_value": oldest_val,
                        "to_value": value,
                    },
                ))

        return events

    def compute_ingress_score(self, analysis: dict) -> dict:
        """Compute a composite ingress/return path score (0-100, lower = worse).

        Returns dict with score, components, and health label.
        """
        us_channels = analysis.get("us_channels", [])
        if not us_channels:
            return {"score": 100, "health": "good", "components": {}}

        # --- US Power component (0-100) ---
        us_powers = [ch["power"] for ch in us_channels]
        max_power = max(us_powers)
        if max_power <= 49:
            power_score = 100
        elif max_power <= 54:
            power_score = 100 - ((max_power - 49) / 5) * 50  # 50-100
        else:
            power_score = max(0, 50 - (max_power - 54) * 10)  # rapid decay above 54

        # --- US Modulation component (0-100) ---
        mod_scores = []
        for ch in us_channels:
            mod = ch.get("modulation", "")
            rank = QAM_ORDER.get(mod, 0)
            # Normalize: 64QAM+ = 100, QPSK = 30, BPSK = 10
            mod_scores.append(min(100, rank * 15))
        modulation_score = sum(mod_scores) / len(mod_scores) if mod_scores else 100

        # --- Channel count component (0-100) ---
        current_count = len(us_channels)
        baseline = self._us_baseline_count or current_count
        if baseline > 0:
            count_ratio = current_count / baseline
            count_score = min(100, count_ratio * 100)
        else:
            count_score = 100

        # --- Weighted composite ---
        score = (
            INGRESS_WEIGHTS["us_power"] * power_score +
            INGRESS_WEIGHTS["us_modulation"] * modulation_score +
            INGRESS_WEIGHTS["us_channel_count"] * count_score
        )
        score = round(max(0, min(100, score)), 1)

        if score >= 80:
            health = "good"
        elif score >= 50:
            health = "marginal"
        else:
            health = "poor"

        return {
            "score": score,
            "health": health,
            "components": {
                "power_score": round(power_score, 1),
                "modulation_score": round(modulation_score, 1),
                "channel_count_score": round(count_score, 1),
            },
        }

    def get_adaptive_poll_interval(self, analysis: dict, base_interval: int) -> int:
        """Calculate adaptive poll interval based on error rates and health.

        Returns adjusted interval in seconds (may be lower than base_interval
        when issues are detected, never higher).
        """
        summary = analysis.get("summary", {})
        health = summary.get("health", "good")
        uncorr_errors = summary.get("ds_uncorrectable_errors", 0)

        if health == "poor" or uncorr_errors > 50000:
            # High-resolution: every 30 seconds
            return max(30, base_interval // 30)
        elif health == "marginal" or uncorr_errors > 10000:
            # Medium-resolution: every 60 seconds
            return max(60, base_interval // 15)

        # For watchdog events in the last check
        if self._prev_us_count is not None and len(analysis.get("us_channels", [])) < self._prev_us_count:
            return max(30, base_interval // 30)

        return base_interval
