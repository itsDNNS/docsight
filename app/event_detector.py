"""Detect significant signal changes between consecutive DOCSIS snapshots."""

import logging
import threading

from .tz import utc_now

log = logging.getLogger("docsis.events")

# Thresholds for event detection
POWER_SHIFT_THRESHOLD = 2.0  # dBmV shift to trigger power_change
UNCORR_SPIKE_THRESHOLD = 1000

# Restart detection thresholds
RESTART_CHANNEL_THRESHOLD = 0.8    # 80% of valid channels must be declining
RESTART_MIN_OVERLAP = 4            # Minimum overlapping channels for fair comparison
RESTART_MIN_CONTINUITY = 0.5       # Minimum overlap ratio (vs either snapshot)

# Import SNR thresholds from analyzer (loaded from thresholds.json)
from app.analyzer import _get_snr_thresholds as _snr_thresholds

from .docsis_utils import qam_rank as _qam_rank

# A drop of this many levels or more counts as critical (e.g. 256QAM → 16QAM = 4 levels)
QAM_CRITICAL_DROP = 3


class EventDetector:
    """Compare consecutive analyses and emit event dicts."""

    def __init__(self, hysteresis=0):
        self._prev = None
        self._lock = threading.Lock()
        self._hysteresis = max(0, int(hysteresis or 0))
        self._confirmed_health = None
        self._pending_health = None
        self._pending_count = 0

    def check(self, analysis):
        """Compare current analysis with previous, return list of event dicts.

        Called after each poll. On first call (no previous), stores baseline
        and returns empty list.
        """
        with self._lock:
            prev = self._prev
            self._prev = analysis
        ts = utc_now()

        if prev is None:
            # First poll: generate baseline event
            health = analysis.get("summary", {}).get("health", "unknown")
            return [{
                "timestamp": ts,
                "severity": "info",
                "event_type": "monitoring_started",
                "message": f"Monitoring started (Health: {health})",
                "details": {"health": health},
            }]

        events = []
        cur_s = analysis.get("summary", {})
        prev_s = prev.get("summary", {})

        # Health change
        self._check_health(events, ts, cur_s, prev_s)
        # Power change
        self._check_power(events, ts, cur_s, prev_s)
        # SNR change
        self._check_snr(events, ts, cur_s, prev_s)
        # Channel count change
        self._check_channels(events, ts, cur_s, prev_s)
        # Modulation change
        self._check_modulation(events, ts, analysis, prev)
        # Restart detection (before errors — restart causes negative delta)
        self._check_restart(events, ts, analysis, prev)
        # Error spike
        self._check_errors(events, ts, cur_s, prev_s)

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
        ds_cur = cur.get("ds_power_avg", 0)
        ds_prev = prev.get("ds_power_avg", 0)
        if abs(ds_cur - ds_prev) > POWER_SHIFT_THRESHOLD:
            events.append({
                "timestamp": ts,
                "severity": "warning",
                "event_type": "power_change",
                "message": f"DS power avg shifted from {ds_prev} to {ds_cur} dBmV",
                "details": {"direction": "downstream", "prev": ds_prev, "current": ds_cur},
            })

        # Upstream power avg shift
        us_cur = cur.get("us_power_avg", 0)
        us_prev = prev.get("us_power_avg", 0)
        if abs(us_cur - us_prev) > POWER_SHIFT_THRESHOLD:
            events.append({
                "timestamp": ts,
                "severity": "warning",
                "event_type": "power_change",
                "message": f"US power avg shifted from {us_prev} to {us_cur} dBmV",
                "details": {"direction": "upstream", "prev": us_prev, "current": us_cur},
            })

    def _check_snr(self, events, ts, cur, prev):
        snr_cur = cur.get("ds_snr_min", 0)
        snr_prev = prev.get("ds_snr_min", 0)
        if snr_cur == snr_prev:
            return

        st = _snr_thresholds()
        snr_crit = st["crit_min"]
        snr_warn = st["good_min"]

        # Crossed critical threshold
        if snr_cur < snr_crit and snr_prev >= snr_crit:
            events.append({
                "timestamp": ts,
                "severity": "critical",
                "event_type": "snr_change",
                "message": f"DS SNR min dropped to {snr_cur} dB (critical threshold: {snr_crit})",
                "details": {"prev": snr_prev, "current": snr_cur, "threshold": "critical"},
            })
        # Crossed warning threshold
        elif snr_cur < snr_warn and snr_prev >= snr_warn:
            events.append({
                "timestamp": ts,
                "severity": "warning",
                "event_type": "snr_change",
                "message": f"DS SNR min dropped to {snr_cur} dB (warning threshold: {snr_warn})",
                "details": {"prev": snr_prev, "current": snr_cur, "threshold": "warning"},
            })

    def _check_channels(self, events, ts, cur, prev):
        ds_cur = cur.get("ds_total", 0)
        ds_prev = prev.get("ds_total", 0)
        us_cur = cur.get("us_total", 0)
        us_prev = prev.get("us_total", 0)

        if ds_cur != ds_prev:
            events.append({
                "timestamp": ts,
                "severity": "info",
                "event_type": "channel_change",
                "message": f"DS channel count changed from {ds_prev} to {ds_cur}",
                "details": {"direction": "downstream", "prev": ds_prev, "current": ds_cur},
            })
        if us_cur != us_prev:
            events.append({
                "timestamp": ts,
                "severity": "info",
                "event_type": "channel_change",
                "message": f"US channel count changed from {us_prev} to {us_cur}",
                "details": {"direction": "upstream", "prev": us_prev, "current": us_cur},
            })

    def _check_modulation(self, events, ts, cur_analysis, prev_analysis):
        cur_ds = {ch["channel_id"]: ch.get("modulation", "") for ch in cur_analysis.get("ds_channels", [])}
        prev_ds = {ch["channel_id"]: ch.get("modulation", "") for ch in prev_analysis.get("ds_channels", [])}
        cur_us = {ch["channel_id"]: ch.get("modulation", "") for ch in cur_analysis.get("us_channels", [])}
        prev_us = {ch["channel_id"]: ch.get("modulation", "") for ch in prev_analysis.get("us_channels", [])}

        downgrades = []
        upgrades = []
        for ch_id in set(cur_ds) & set(prev_ds):
            if cur_ds[ch_id] != prev_ds[ch_id]:
                entry = {"channel": ch_id, "direction": "DS", "prev": prev_ds[ch_id], "current": cur_ds[ch_id]}
                cur_rank = _qam_rank(cur_ds[ch_id])
                prev_rank = _qam_rank(prev_ds[ch_id])
                entry["prev_rank"] = prev_rank
                entry["current_rank"] = cur_rank
                entry["rank_drop"] = prev_rank - cur_rank
                if cur_rank < prev_rank:
                    downgrades.append(entry)
                else:
                    upgrades.append(entry)
        for ch_id in set(cur_us) & set(prev_us):
            if cur_us[ch_id] != prev_us[ch_id]:
                entry = {"channel": ch_id, "direction": "US", "prev": prev_us[ch_id], "current": cur_us[ch_id]}
                cur_rank = _qam_rank(cur_us[ch_id])
                prev_rank = _qam_rank(prev_us[ch_id])
                entry["prev_rank"] = prev_rank
                entry["current_rank"] = cur_rank
                entry["rank_drop"] = prev_rank - cur_rank
                if cur_rank < prev_rank:
                    downgrades.append(entry)
                else:
                    upgrades.append(entry)

        if downgrades:
            max_drop = max(d["rank_drop"] for d in downgrades)
            severity = "critical" if max_drop >= QAM_CRITICAL_DROP else "warning"
            events.append({
                "timestamp": ts,
                "severity": severity,
                "event_type": "modulation_change",
                "message": f"Modulation dropped on {len(downgrades)} channel(s)",
                "details": {"changes": downgrades, "direction": "downgrade"},
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
        uncorr_cur = cur.get("ds_uncorrectable_errors", 0)
        uncorr_prev = prev.get("ds_uncorrectable_errors", 0)
        delta = uncorr_cur - uncorr_prev

        if delta > UNCORR_SPIKE_THRESHOLD:
            events.append({
                "timestamp": ts,
                "severity": "warning",
                "event_type": "error_spike",
                "message": f"Uncorrectable errors jumped by {delta:,} (from {uncorr_prev:,} to {uncorr_cur:,})",
                "details": {"prev": uncorr_prev, "current": uncorr_cur, "delta": delta},
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
            },
        })
