"""Detect significant signal changes between consecutive DOCSIS snapshots."""

import logging
from datetime import datetime

log = logging.getLogger("docsis.events")

# Thresholds for event detection
POWER_SHIFT_THRESHOLD = 2.0  # dBmV shift to trigger power_change
SNR_WARN_THRESHOLD = 30.0
SNR_CRIT_THRESHOLD = 25.0
UNCORR_SPIKE_THRESHOLD = 1000


class EventDetector:
    """Compare consecutive analyses and emit event dicts."""

    def __init__(self):
        self._prev = None

    def check(self, analysis):
        """Compare current analysis with previous, return list of event dicts.

        Called after each poll. On first call (no previous), stores baseline
        and returns empty list.
        """
        prev = self._prev
        self._prev = analysis
        ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

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
        # Error spike
        self._check_errors(events, ts, cur_s, prev_s)

        return events

    def _check_health(self, events, ts, cur, prev):
        cur_health = cur.get("health", "good")
        prev_health = prev.get("health", "good")
        if cur_health == prev_health:
            return

        # Determine severity based on transition direction
        health_order = {"good": 0, "marginal": 1, "poor": 2}
        cur_level = health_order.get(cur_health, 0)
        prev_level = health_order.get(prev_health, 0)

        if cur_level > prev_level:
            # Degradation
            severity = "critical" if cur_health == "poor" else "warning"
            message = f"Health changed from {prev_health} to {cur_health}"
        else:
            # Recovery
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

        # Crossed critical threshold
        if snr_cur < SNR_CRIT_THRESHOLD and snr_prev >= SNR_CRIT_THRESHOLD:
            events.append({
                "timestamp": ts,
                "severity": "critical",
                "event_type": "snr_change",
                "message": f"DS SNR min dropped to {snr_cur} dB (critical threshold: {SNR_CRIT_THRESHOLD})",
                "details": {"prev": snr_prev, "current": snr_cur, "threshold": "critical"},
            })
        # Crossed warning threshold
        elif snr_cur < SNR_WARN_THRESHOLD and snr_prev >= SNR_WARN_THRESHOLD:
            events.append({
                "timestamp": ts,
                "severity": "warning",
                "event_type": "snr_change",
                "message": f"DS SNR min dropped to {snr_cur} dB (warning threshold: {SNR_WARN_THRESHOLD})",
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

        changed = []
        for ch_id in set(cur_ds) & set(prev_ds):
            if cur_ds[ch_id] != prev_ds[ch_id]:
                changed.append({"channel": ch_id, "direction": "DS", "prev": prev_ds[ch_id], "current": cur_ds[ch_id]})
        for ch_id in set(cur_us) & set(prev_us):
            if cur_us[ch_id] != prev_us[ch_id]:
                changed.append({"channel": ch_id, "direction": "US", "prev": prev_us[ch_id], "current": cur_us[ch_id]})

        if changed:
            events.append({
                "timestamp": ts,
                "severity": "info",
                "event_type": "modulation_change",
                "message": f"Modulation changed on {len(changed)} channel(s)",
                "details": {"changes": changed},
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
