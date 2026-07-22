"""Detect significant signal changes between consecutive DOCSIS snapshots."""

from __future__ import annotations

import logging
import math
import threading

from app.analyzer import _get_snr_thresholds as _snr_thresholds

from .docsis_utils import channel_type_label as _shared_channel_type_label, qam_rank as _qam_rank
from .types import AnalysisResult, EventDict
from .tz import utc_now

log = logging.getLogger("docsis.events")

# Thresholds for event detection
POWER_SHIFT_THRESHOLD = 2.0  # dBmV shift to trigger power_change
UNCORR_SPIKE_THRESHOLD = 1000

# Restart detection thresholds
RESTART_CHANNEL_THRESHOLD = 0.8    # 80% of valid channels must be declining
RESTART_MIN_OVERLAP = 4            # Minimum overlapping channels for fair comparison
RESTART_MIN_CONTINUITY = 0.5       # Minimum overlap ratio (vs either snapshot)

# A drop of this many levels or more counts as critical (e.g. 256QAM → 16QAM = 4 levels)
QAM_CRITICAL_DROP = 3


def _normalize_channel_id(value):
    """Return a canonical key for matching channel IDs across snapshots.

    Numeric strings and ints collapse to the same key so ``"11"`` matches ``11``.
    Integer-valued floats such as ``"11.0"`` also collapse to the int key so
    they match ``11`` / ``"11"``; non-integer floats keep a distinct float key.
    Returns ``None`` for missing or empty IDs so they are skipped rather than
    folded together.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return ("int", int(s))
    except (TypeError, ValueError):
        pass
    try:
        f = float(s)
    except (TypeError, ValueError):
        return ("str", s)
    if f.is_integer():
        return ("int", int(f))
    return ("float", f)


def _coerce_float(value):
    """Coerce a value to float; return None if not convertible or non-finite."""
    if value is None or isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return f


def _channel_type_label(direction: str, channel: dict, fallback: dict | None = None) -> str:
    """Return a concise DOCSIS channel type label for event details."""
    return _shared_channel_type_label(direction, channel, fallback)  # type: ignore[arg-type]


class EventDetector:
    """Compare consecutive analyses and emit event dicts."""

    def __init__(self, hysteresis=0, baseline: AnalysisResult | None = None):
        self._prev = None
        self._prev_snapshot_id = None
        self._lock = threading.Lock()
        self._hysteresis = max(0, int(hysteresis or 0))
        self._confirmed_health = None
        self._pending_health = None
        self._pending_count = 0
        self.seed(baseline)

    def seed(self, analysis: AnalysisResult | None, snapshot_id: int | None = None) -> None:
        """Seed the detector with a persisted baseline snapshot after restart."""
        if not analysis:
            return
        if snapshot_id is None:
            snapshot_id = analysis.get("snapshot_id")
        with self._lock:
            self._prev = analysis
            self._prev_snapshot_id = snapshot_id
            if self._hysteresis >= 2:
                self._confirmed_health = analysis.get("summary", {}).get("health", "good")
            self._pending_health = None
            self._pending_count = 0

    @staticmethod
    def _annotate_event_details(events, snapshot_id, previous_snapshot_id):
        """Attach source snapshot provenance to generated event details."""
        if snapshot_id is None and previous_snapshot_id is None:
            return
        for event in events:
            details = event.get("details")
            if not isinstance(details, dict):
                details = {}
                event["details"] = details
            if snapshot_id is not None:
                details.setdefault("snapshot_id", snapshot_id)
            if previous_snapshot_id is not None:
                details.setdefault("previous_snapshot_id", previous_snapshot_id)

    def check(self, analysis: AnalysisResult, snapshot_id: int | None = None) -> list[EventDict]:
        """Compare current analysis with previous, return list of event dicts.

        Called after each poll. On first call (no previous), stores baseline
        and returns empty list.
        """
        with self._lock:
            prev = self._prev
            prev_snapshot_id = self._prev_snapshot_id
            self._prev = analysis
            self._prev_snapshot_id = snapshot_id
        ts = utc_now()

        if prev is None:
            # First poll: generate baseline event
            health = analysis.get("summary", {}).get("health", "unknown")
            events = [{
                "timestamp": ts,
                "severity": "info",
                "event_type": "monitoring_started",
                "message": f"Monitoring started (Health: {health})",
                "details": {"health": health},
            }]
            self._annotate_event_details(events, snapshot_id, prev_snapshot_id)
            return events

        events = []
        cur_s = analysis.get("summary", {})
        prev_s = prev.get("summary", {})

        # Health change
        self._check_health(events, ts, cur_s, prev_s)
        # Power change
        self._check_power(events, ts, cur_s, prev_s)
        # SNR change
        self._check_snr(events, ts, analysis, prev)
        # Channel count change
        self._check_channels(events, ts, analysis, prev)
        # Modulation change
        self._check_modulation(events, ts, analysis, prev)
        # Restart detection (before errors — restart causes negative delta)
        self._check_restart(events, ts, analysis, prev)
        # Error spike
        self._check_errors(events, ts, cur_s, prev_s)

        self._annotate_event_details(events, snapshot_id, prev_snapshot_id)
        return events

    def _check_health(self, events, ts, cur, prev):
        cur_health = cur.get("health", "good")

        if self._hysteresis < 2:
            # Original behavior: immediate state changes
            prev_health = prev.get("health", "good")
            if cur_health == prev_health:
                return
            self._emit_health_event(events, ts, prev_health, cur_health)
            return

        # Hysteresis mode: require N consecutive polls before confirming
        if self._confirmed_health is None:
            self._confirmed_health = prev.get("health", "good")

        confirmed = self._confirmed_health

        if cur_health == confirmed:
            # Back to confirmed state, reset pending
            self._pending_health = None
            self._pending_count = 0
            return

        if cur_health == self._pending_health:
            self._pending_count += 1
        else:
            # Different pending health, restart counter
            self._pending_health = cur_health
            self._pending_count = 1

        if self._pending_count >= self._hysteresis:
            # Transition confirmed
            self._emit_health_event(events, ts, confirmed, cur_health)
            self._confirmed_health = cur_health
            self._pending_health = None
            self._pending_count = 0

    @staticmethod
    def _emit_health_event(events, ts, prev_health, cur_health):
        health_order = {"good": 0, "tolerated": 1, "marginal": 2, "critical": 3}
        cur_level = health_order.get(cur_health, 0)
        prev_level = health_order.get(prev_health, 0)

        if cur_level > prev_level:
            severity = "critical" if cur_health == "critical" else "warning"
            message = f"Health changed from {prev_health} to {cur_health}"
        else:
            severity = "info"
            message = f"Health recovered from {prev_health} to {cur_health}"

        events.append({
            "timestamp": ts,
            "severity": severity,
            "event_type": "health_change",
            "message": message,
            "details": {"prev": prev_health, "current": cur_health},
        })

    def _check_power(self, events, ts, cur, prev):
        # Downstream power avg shift
        ds_cur = _coerce_float(cur.get("ds_power_avg"))
        ds_prev = _coerce_float(prev.get("ds_power_avg"))
        if ds_cur is not None and ds_prev is not None and abs(ds_cur - ds_prev) > POWER_SHIFT_THRESHOLD:
            events.append({
                "timestamp": ts,
                "severity": "warning",
                "event_type": "power_change",
                "message": f"DS power avg shifted from {ds_prev} to {ds_cur} dBmV",
                "details": {
                    "direction": "downstream",
                    "prev": ds_prev,
                    "current": ds_cur,
                    "threshold_delta": POWER_SHIFT_THRESHOLD,
                },
            })

        # Upstream power avg shift
        us_cur = _coerce_float(cur.get("us_power_avg"))
        us_prev = _coerce_float(prev.get("us_power_avg"))
        if us_cur is not None and us_prev is not None and abs(us_cur - us_prev) > POWER_SHIFT_THRESHOLD:
            events.append({
                "timestamp": ts,
                "severity": "warning",
                "event_type": "power_change",
                "message": f"US power avg shifted from {us_prev} to {us_cur} dBmV",
                "details": {
                    "direction": "upstream",
                    "prev": us_prev,
                    "current": us_cur,
                    "threshold_delta": POWER_SHIFT_THRESHOLD,
                },
            })

    def _check_snr(self, events, ts, cur_analysis, prev_analysis):
        cur = cur_analysis.get("summary", {})
        prev = prev_analysis.get("summary", {})
        snr_cur = _coerce_float(cur.get("ds_snr_min"))
        snr_prev = _coerce_float(prev.get("ds_snr_min"))
        if snr_cur is None or snr_prev is None or snr_cur == snr_prev:
            return

        health_affected = self._snr_affected_channels_by_health(cur_analysis, prev_analysis)
        if health_affected is not None:
            if not health_affected:
                return
            worst = max(
                health_affected,
                key=lambda channel: {"good": 0, "tolerated": 1, "warning": 2, "critical": 3}.get(channel.get("current_health"), 0),
            )
            current_health = worst.get("current_health", "warning")
            severity = "critical" if current_health == "critical" else "warning"
            events.append({
                "timestamp": ts,
                "severity": severity,
                "event_type": "snr_change",
                "message": f"DS SNR/MER health changed to {current_health} (min: {snr_cur} dB)",
                "details": {
                    "prev": snr_prev,
                    "current": snr_cur,
                    "threshold": current_health,
                    "affected_channels": health_affected,
                },
            })
            return

        st = _snr_thresholds()
        snr_crit = st["crit_min"]
        snr_warn = st["good_min"]

        # Fallback for legacy snapshots without analyzer-provided snr_health.
        if snr_cur < snr_crit and snr_prev >= snr_crit:
            affected_channels = self._snr_affected_channels(
                cur_analysis, prev_analysis,
                [("warning", snr_warn), ("critical", snr_crit)],
            )
            events.append({
                "timestamp": ts,
                "severity": "critical",
                "event_type": "snr_change",
                "message": f"DS SNR min dropped to {snr_cur} dB (critical threshold: {snr_crit})",
                "details": {
                    "prev": snr_prev,
                    "current": snr_cur,
                    "threshold": "critical",
                    "threshold_value": snr_crit,
                    "affected_channels": affected_channels,
                },
            })
        elif snr_cur < snr_warn and snr_prev >= snr_warn:
            affected_channels = self._snr_affected_channels(
                cur_analysis, prev_analysis,
                [("warning", snr_warn)],
            )
            events.append({
                "timestamp": ts,
                "severity": "warning",
                "event_type": "snr_change",
                "message": f"DS SNR min dropped to {snr_cur} dB (warning threshold: {snr_warn})",
                "details": {
                    "prev": snr_prev,
                    "current": snr_cur,
                    "threshold": "warning",
                    "threshold_value": snr_warn,
                    "affected_channels": affected_channels,
                },
            })

    @staticmethod
    def _snr_affected_channels_by_health(cur_analysis, prev_analysis):
        """Return analyzer health degradations, or ``None`` for legacy data."""
        health_rank = {"missing": -1, "good": 0, "tolerated": 1, "warning": 2, "critical": 3}
        analyzer_families = {"sc_qam", "ofdm"}
        prev_channels = {}
        for ch in prev_analysis.get("ds_channels", []):
            key = _normalize_channel_id(ch.get("channel_id"))
            if key is not None:
                prev_channels[key] = ch

        affected = []
        found_comparable = False
        for cur_ch in cur_analysis.get("ds_channels", []):
            key = _normalize_channel_id(cur_ch.get("channel_id"))
            if key is None:
                continue
            prev_ch = prev_channels.get(key)
            if not prev_ch:
                continue
            prev_snr = _coerce_float(prev_ch.get("snr"))
            cur_snr = _coerce_float(cur_ch.get("snr"))
            if prev_snr is None or cur_snr is None:
                continue
            found_comparable = True
            prev_health = prev_ch.get("snr_health")
            cur_health = cur_ch.get("snr_health")
            if not prev_health and prev_ch.get("channel_family") in analyzer_families:
                prev_health = "good"
            if not cur_health and cur_ch.get("channel_family") in analyzer_families:
                cur_health = "good"
            if not prev_health or not cur_health:
                return None
            if health_rank.get(cur_health, 0) <= health_rank.get(prev_health, 0):
                continue
            if health_rank.get(cur_health, 0) <= health_rank.get("good", 0):
                continue
            delta = round(cur_snr - prev_snr, 1)
            affected.append({
                "channel": cur_ch.get("channel_id"),
                "frequency": cur_ch.get("frequency") or prev_ch.get("frequency") or "",
                "docsis_version": cur_ch.get("docsis_version") or prev_ch.get("docsis_version") or "",
                "channel_type": _channel_type_label("DS", cur_ch, prev_ch),
                "modulation": cur_ch.get("modulation") or prev_ch.get("modulation") or "",
                "prev": prev_snr,
                "current": cur_snr,
                "delta": 0.0 if delta == -0.0 else delta,
                "prev_health": prev_health,
                "current_health": cur_health,
                "threshold": cur_health,
            })
        affected.sort(key=lambda ch: ({"critical": 0, "warning": 1, "tolerated": 2}.get(ch.get("current_health"), 3), ch.get("current") is None, ch.get("current") or 0, str(ch.get("channel"))))
        return affected if found_comparable else None

    @staticmethod
    def _snr_affected_channels(cur_analysis, prev_analysis, thresholds):
        """Identify channels whose SNR crossed any of the given thresholds.

        ``thresholds`` is an ordered list of ``(label, value)`` pairs from least
        to most severe. Each returned channel is tagged with the most severe
        label it crossed.
        """
        prev_channels = {}
        for ch in prev_analysis.get("ds_channels", []):
            key = _normalize_channel_id(ch.get("channel_id"))
            if key is None:
                continue
            prev_channels[key] = ch

        affected = []
        for cur_ch in cur_analysis.get("ds_channels", []):
            ch_id = cur_ch.get("channel_id")
            key = _normalize_channel_id(ch_id)
            if key is None:
                continue
            prev_ch = prev_channels.get(key)
            if not prev_ch:
                continue

            prev_snr = _coerce_float(prev_ch.get("snr"))
            cur_snr = _coerce_float(cur_ch.get("snr"))
            if prev_snr is None or cur_snr is None:
                continue

            crossed = None
            for label, value in thresholds:
                t = _coerce_float(value)
                if t is None:
                    continue
                if cur_snr < t <= prev_snr:
                    crossed = label  # ordered least → most severe; last wins
            if crossed is None:
                continue

            delta = round(cur_snr - prev_snr, 1)
            affected.append({
                "channel": ch_id,
                "frequency": cur_ch.get("frequency") or prev_ch.get("frequency") or "",
                "docsis_version": cur_ch.get("docsis_version") or prev_ch.get("docsis_version") or "",
                "channel_type": _channel_type_label("DS", cur_ch, prev_ch),
                "modulation": cur_ch.get("modulation") or prev_ch.get("modulation") or "",
                "prev": prev_snr,
                "current": cur_snr,
                "delta": 0.0 if delta == -0.0 else delta,
                "threshold": crossed,
            })

        affected.sort(key=lambda ch: (ch["current"], str(ch["channel"])))
        return affected

    def _check_channels(self, events, ts, cur_analysis, prev_analysis):
        cur = cur_analysis.get("summary", {})
        prev = prev_analysis.get("summary", {})
        ds_cur = cur.get("ds_total", 0)
        ds_prev = prev.get("ds_total", 0)
        us_cur = cur.get("us_total", 0)
        us_prev = prev.get("us_total", 0)

        def channel_map(analysis, source):
            mapped = {}
            for ch in analysis.get(source, []):
                key = _normalize_channel_id(ch.get("channel_id"))
                if key is not None:
                    mapped[key] = ch
            return mapped

        def channel_detail(ch, direction):
            detail = {
                "channel": ch.get("channel_id"),
                "frequency": ch.get("frequency") or "",
                "docsis_version": ch.get("docsis_version") or "",
                "channel_type": _channel_type_label(direction, ch),
                "modulation": ch.get("modulation") or "",
            }
            return {k: v for k, v in detail.items() if v not in (None, "")}

        def changed_channels(direction, source):
            cur_map = channel_map(cur_analysis, source)
            prev_map = channel_map(prev_analysis, source)
            lost = [channel_detail(prev_map[key], direction) for key in set(prev_map) - set(cur_map)]
            added = [channel_detail(cur_map[key], direction) for key in set(cur_map) - set(prev_map)]
            lost.sort(key=lambda ch: str(ch.get("channel", "")))
            added.sort(key=lambda ch: str(ch.get("channel", "")))
            return lost, added

        if ds_cur != ds_prev:
            lost, added = changed_channels("DS", "ds_channels")
            is_loss = ds_cur < ds_prev
            details = {"direction": "downstream", "prev": ds_prev, "current": ds_cur, "change": "loss" if is_loss else "gain"}
            if lost:
                details["lost_channels"] = lost
            if added:
                details["added_channels"] = added
            events.append({
                "timestamp": ts,
                "severity": "warning" if is_loss else "info",
                "event_type": "channel_change",
                "message": f"DS channel count changed from {ds_prev} to {ds_cur}",
                "details": details,
            })
        if us_cur != us_prev:
            lost, added = changed_channels("US", "us_channels")
            is_loss = us_cur < us_prev
            details = {"direction": "upstream", "prev": us_prev, "current": us_cur, "change": "loss" if is_loss else "gain"}
            if lost:
                details["lost_channels"] = lost
            if added:
                details["added_channels"] = added
            events.append({
                "timestamp": ts,
                "severity": "warning" if is_loss else "info",
                "event_type": "channel_change",
                "message": f"US channel count changed from {us_prev} to {us_cur}",
                "details": details,
            })

    def _check_modulation(self, events, ts, cur_analysis, prev_analysis):
        def channel_map(analysis, direction):
            source = "ds_channels" if direction == "DS" else "us_channels"
            mapped = {}
            for ch in analysis.get(source, []):
                key = _normalize_channel_id(ch.get("channel_id"))
                if key is not None:
                    mapped[key] = ch
            return mapped

        def change_entry(direction, cur_ch, prev_ch):
            cur_mod = cur_ch.get("modulation", "")
            prev_mod = prev_ch.get("modulation", "")
            cur_rank = _qam_rank(cur_mod)
            prev_rank = _qam_rank(prev_mod)
            docsis_version = cur_ch.get("docsis_version") or prev_ch.get("docsis_version") or ""
            entry = {
                "channel": cur_ch.get("channel_id", prev_ch.get("channel_id")),
                "direction": direction,
                "prev": prev_mod,
                "current": cur_mod,
                "prev_rank": prev_rank,
                "current_rank": cur_rank,
                "rank_drop": prev_rank - cur_rank,
            }
            if docsis_version:
                entry["docsis_version"] = docsis_version
            prev_health = prev_ch.get("modulation_health")
            cur_health = cur_ch.get("modulation_health")
            if prev_health:
                entry["prev_modulation_health"] = prev_health
            if cur_health:
                entry["current_modulation_health"] = cur_health
            channel_type = _channel_type_label(direction, cur_ch, prev_ch)
            if channel_type:
                entry["channel_type"] = channel_type
            frequency = cur_ch.get("frequency") or prev_ch.get("frequency") or ""
            if frequency:
                entry["frequency"] = frequency
            return entry

        cur_ds = channel_map(cur_analysis, "DS")
        prev_ds = channel_map(prev_analysis, "DS")
        cur_us = channel_map(cur_analysis, "US")
        prev_us = channel_map(prev_analysis, "US")

        downgrades = []
        upgrades = []
        for key in set(cur_ds) & set(prev_ds):
            if cur_ds[key].get("modulation", "") != prev_ds[key].get("modulation", ""):
                entry = change_entry("DS", cur_ds[key], prev_ds[key])
                if entry["current_rank"] < entry["prev_rank"]:
                    downgrades.append(entry)
                else:
                    upgrades.append(entry)
        for key in set(cur_us) & set(prev_us):
            if cur_us[key].get("modulation", "") != prev_us[key].get("modulation", ""):
                entry = change_entry("US", cur_us[key], prev_us[key])
                if entry["current_rank"] < entry["prev_rank"]:
                    downgrades.append(entry)
                else:
                    upgrades.append(entry)

        if downgrades:
            health_rank = {"good": 0, "tolerated": 1, "warning": 2, "critical": 3}
            max_drop = max(d["rank_drop"] for d in downgrades)
            current_health_ranks = [
                health_rank.get(d.get("current_modulation_health"), 0)
                for d in downgrades
                if d.get("current_modulation_health")
            ]
            max_current_health = max(current_health_ranks, default=0)
            severity = (
                "critical"
                if max_current_health >= health_rank["critical"] or (not current_health_ranks and max_drop >= QAM_CRITICAL_DROP)
                else "warning"
            )
            events.append({
                "timestamp": ts,
                "severity": severity,
                "event_type": "modulation_change",
                "message": f"Modulation dropped on {len(downgrades)} channel(s)",
                "details": {
                    "changes": downgrades,
                    "direction": "downgrade",
                    "critical_rank_drop": QAM_CRITICAL_DROP,
                },
            })
        if upgrades:
            events.append({
                "timestamp": ts,
                "severity": "info",
                "event_type": "modulation_change",
                "message": f"Modulation improved on {len(upgrades)} channel(s)",
                "details": {"changes": upgrades, "direction": "upgrade"},
            })

    def _check_errors(self, events, ts, cur, prev):
        if cur.get("errors_supported") is False or prev.get("errors_supported") is False:
            return
        uncorr_cur = cur.get("ds_uncorrectable_errors", 0)
        uncorr_prev = prev.get("ds_uncorrectable_errors", 0)
        if uncorr_cur is None or uncorr_prev is None:
            return
        delta = uncorr_cur - uncorr_prev

        if delta > UNCORR_SPIKE_THRESHOLD:
            events.append({
                "timestamp": ts,
                "severity": "warning",
                "event_type": "error_spike",
                "message": f"Uncorrectable errors jumped by {delta:,} (from {uncorr_prev:,} to {uncorr_cur:,})",
                "details": {
                    "prev": uncorr_prev,
                    "current": uncorr_cur,
                    "delta": delta,
                    "threshold_delta": UNCORR_SPIKE_THRESHOLD,
                },
            })

    def _check_restart(self, events, ts, cur, prev):
        """Detect modem restart via per-channel error counter reset."""
        prev_channels = {ch["channel_id"]: ch for ch in prev.get("ds_channels", [])}
        cur_channels = {ch["channel_id"]: ch for ch in cur.get("ds_channels", [])}

        overlap_ids = set(prev_channels.keys()) & set(cur_channels.keys())

        # Guard: insufficient continuity
        prev_count = len(prev_channels)
        cur_count = len(cur_channels)
        if len(overlap_ids) < RESTART_MIN_OVERLAP:
            return
        if prev_count > 0 and len(overlap_ids) / prev_count < RESTART_MIN_CONTINUITY:
            return
        if cur_count > 0 and len(overlap_ids) / cur_count < RESTART_MIN_CONTINUITY:
            return

        # Count channels with declining counters
        valid_channels = 0
        declining_channels = 0

        for ch_id in overlap_ids:
            p = prev_channels[ch_id]
            c = cur_channels[ch_id]
            p_corr = p.get("correctable_errors")
            p_uncorr = p.get("uncorrectable_errors")
            c_corr = c.get("correctable_errors")
            c_uncorr = c.get("uncorrectable_errors")

            # Evaluate each counter family independently.
            # A channel is valid if at least one counter pair is comparable.
            # A channel is declining if at least one counter declined and none increased.
            has_corr = p_corr is not None and c_corr is not None
            has_uncorr = p_uncorr is not None and c_uncorr is not None

            if not has_corr and not has_uncorr:
                continue  # No comparable counters at all

            valid_channels += 1
            corr_declined = has_corr and c_corr < p_corr
            uncorr_declined = has_uncorr and c_uncorr < p_uncorr
            corr_ok = not has_corr or c_corr <= p_corr
            uncorr_ok = not has_uncorr or c_uncorr <= p_uncorr
            if (corr_declined or uncorr_declined) and corr_ok and uncorr_ok:
                declining_channels += 1

        if valid_channels < RESTART_MIN_OVERLAP:
            return
        if declining_channels / valid_channels < RESTART_CHANNEL_THRESHOLD:
            return

        # Sanity check: at least one summary total must decline.
        # If either snapshot is missing the summary keys entirely, skip the
        # sanity check (rely on per-channel signal alone) rather than
        # defaulting to 0 which would create false positives.
        prev_s = prev.get("summary", {})
        cur_s = cur.get("summary", {})
        prev_corr_total = prev_s.get("ds_correctable_errors")
        prev_uncorr_total = prev_s.get("ds_uncorrectable_errors")
        cur_corr_total = cur_s.get("ds_correctable_errors")
        cur_uncorr_total = cur_s.get("ds_uncorrectable_errors")

        # Only enforce sanity check if all four values are present
        if all(v is not None for v in (prev_corr_total, prev_uncorr_total,
                                        cur_corr_total, cur_uncorr_total)):
            if cur_corr_total >= prev_corr_total and cur_uncorr_total >= prev_uncorr_total:
                return  # Neither total declining

        events.append({
            "timestamp": ts,
            "severity": "info",
            "event_type": "modem_restart_detected",
            "message": "Detected modem restart or counter reset pattern",
            "details": {
                "affected_channels": declining_channels,
                "total_channels": valid_channels,
                "prev_corr_total": prev_corr_total,
                "prev_uncorr_total": prev_uncorr_total,
                "current_corr_total": cur_corr_total,
                "current_uncorr_total": cur_uncorr_total,
                "declining_channel_ratio_threshold": RESTART_CHANNEL_THRESHOLD,
                "minimum_overlap_channels": RESTART_MIN_OVERLAP,
            },
        })
