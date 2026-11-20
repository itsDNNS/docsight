"""Channel history and correlation timeline mixin."""

import json

from app.channel_selector import match_channel, match_channels

from ..tz import utc_cutoff
from .error_counters import unwrap_uint32_counter_series
from .events import decode_details


_CHANNEL_ERROR_KEYS = ("correctable_errors", "uncorrectable_errors")


def _history_row(timestamp, channel, *, include_frequency=False):
    row = {
        "timestamp": timestamp,
        "power": channel.get("power"),
        "snr": channel.get("snr"),
        "correctable_errors": channel.get("correctable_errors"),
        "uncorrectable_errors": channel.get("uncorrectable_errors"),
        "modulation": channel.get("modulation", ""),
    }
    if include_frequency:
        row["frequency"] = channel.get("frequency", "")
    else:
        row["health"] = channel.get("health", "")
    return row


class AnalysisMethods:

    def get_correlation_timeline(self, start_ts, end_ts, sources=None):
        """Return unified timeline entries from all sources, sorted by timestamp.

        Args:
            start_ts: UTC start timestamp (with Z suffix)
            end_ts: UTC end timestamp (with Z suffix)
            sources: set of source names to include (modem, speedtest, events,
                     bnetz, segment, capture). None means all.

        Returns list of dicts with 'timestamp', 'source', and source-specific fields.
        """
        if sources is None:
            sources = {"modem", "speedtest", "events", "bnetz", "segment", "capture"}
        timeline = []

        if "modem" in sources:
            for snap in self.get_range_summaries(start_ts, end_ts):
                s = snap["summary"]
                errors_supported = s.get("errors_supported", True)
                corr_errors = s.get("ds_correctable_errors") if errors_supported else None
                uncorr_errors = s.get("ds_uncorrectable_errors") if errors_supported else None
                timeline.append({
                    "timestamp": snap["timestamp"],
                    "source": "modem",
                    "health": s.get("health", "unknown"),
                    "ds_power_avg": s.get("ds_power_avg"),
                    "ds_power_max": s.get("ds_power_max"),
                    "ds_snr_min": s.get("ds_snr_min"),
                    "ds_snr_avg": s.get("ds_snr_avg"),
                    "us_power_avg": s.get("us_power_avg"),
                    "ds_correctable_errors": corr_errors,
                    "ds_uncorrectable_errors": uncorr_errors,
                })

        if "speedtest" in sources:
            from app.modules.speedtest.storage import SpeedtestStorage
            for st in SpeedtestStorage(self.db_path).get_speedtest_in_range(start_ts, end_ts):
                download_mbps = st.get("download_mbps")
                timeline.append({
                    "timestamp": st["timestamp"],
                    "source": "speedtest",
                    "id": st["id"],
                    "download_mbps": download_mbps,
                    "speedtest_download": download_mbps,
                    "upload_mbps": st.get("upload_mbps"),
                    "ping_ms": st.get("ping_ms"),
                    "jitter_ms": st.get("jitter_ms"),
                    "packet_loss_pct": st.get("packet_loss_pct"),
                })

        if "events" in sources:
            with self._read() as conn:
                rows = conn.execute(
                    "SELECT id, timestamp, severity, event_type, message, details "
                    "FROM events WHERE timestamp >= ? AND timestamp <= ? "
                    "ORDER BY timestamp",
                    (start_ts, end_ts),
                ).fetchall()
            for r in rows:
                event = {
                    "timestamp": r["timestamp"],
                    "source": "event",
                    "severity": r["severity"],
                    "event_type": r["event_type"],
                    "message": r["message"],
                }
                if r["details"]:
                    event["details"] = decode_details(r["details"])
                timeline.append(event)

        if "bnetz" in sources:
            from app.modules.bnetz.storage import BnetzStorage
            for m in BnetzStorage(self.db_path).get_bnetz_in_range(start_ts, end_ts):
                timeline.append({
                    "timestamp": m["timestamp"],
                    "source": "bnetz",
                    "download_tariff": m.get("download_max_tariff"),
                    "download_avg": m.get("download_measured_avg"),
                    "upload_tariff": m.get("upload_max_tariff"),
                    "upload_avg": m.get("upload_measured_avg"),
                    "verdict_download": m.get("verdict_download"),
                    "verdict_upload": m.get("verdict_upload"),
                })

        # Smart Capture executions
        if "capture" in sources:
            with self._read() as conn:
                rows = conn.execute(
                    "SELECT * FROM smart_capture_executions "
                    "WHERE created_at >= ? AND created_at <= ? "
                    "ORDER BY created_at",
                    (start_ts, end_ts),
                ).fetchall()
            for r in rows:
                entry = {
                    "timestamp": r["created_at"],
                    "source": "capture",
                    "status": r["status"],
                    "trigger_type": r["trigger_type"],
                    "action_type": r["action_type"],
                    "linked_result_id": r["linked_result_id"],
                    "suppression_reason": r["suppression_reason"],
                    "last_error": r["last_error"],
                }
                if r["details"]:
                    entry["details"] = decode_details(r["details"])
                timeline.append(entry)

            # Filter smart_capture_triggered from events to avoid double-counting
            timeline = [e for e in timeline
                        if not (e.get("source") == "event"
                                and e.get("event_type") == "smart_capture_triggered")]

        # Segment utilization
        if "segment" in sources:
            from app.storage.segment_utilization import SegmentUtilizationStorage
            for row in SegmentUtilizationStorage(self.db_path).get_range(start_ts, end_ts):
                timeline.append({
                    "timestamp": row["timestamp"],
                    "source": "segment",
                    "ds_total": row["ds_total"],
                    "us_total": row["us_total"],
                    "ds_own": row["ds_own"],
                    "us_own": row["us_own"],
                })

        timeline.sort(key=lambda x: x["timestamp"])
        return timeline

    def get_channel_history(
        self, channel_id, direction, days=7, hours=None, selector=None
    ):
        """Return time series for a single channel over the selected window.
        An exact selector takes precedence over the legacy unique channel_id.
        direction: 'ds' or 'us'. Returns list of dicts with timestamp + channel fields."""
        cutoff = utc_cutoff(hours=hours) if hours is not None else utc_cutoff(days=days)
        col = {"ds": "ds_channels_json", "us": "us_channels_json"}[direction]
        with self._read() as conn:
            rows = conn.execute(
                f"SELECT timestamp, {col} FROM snapshots WHERE timestamp >= ? ORDER BY timestamp",
                (cutoff,),
            ).fetchall()
        results = []
        for ts, channels_json in rows:
            channels = json.loads(channels_json)
            channel = match_channel(
                channels, selector=selector, channel_id=channel_id
            )
            if channel is not None:
                results.append(_history_row(ts, channel))
        unwrap_uint32_counter_series(results, _CHANNEL_ERROR_KEYS)
        return results

    def get_channel_snapshots(self, days=7, hours=None, start=None, end=None):
        """Return (timestamp, ds_channels, us_channels) for every snapshot in the window.
        An explicit UTC start (and optional end) takes precedence over days/hours."""
        if start is None:
            start = utc_cutoff(hours=hours) if hours is not None else utc_cutoff(days=days)
        query = "SELECT timestamp, ds_channels_json, us_channels_json FROM snapshots WHERE timestamp >= ?"
        params = [start]
        if end is not None:
            query += " AND timestamp <= ?"
            params.append(end)
        with self._read() as conn:
            rows = conn.execute(query + " ORDER BY timestamp", params).fetchall()
        return [(ts, json.loads(ds or "[]"), json.loads(us or "[]")) for ts, ds, us in rows]

    def get_multi_channel_history(
        self, channel_ids, direction, days=7, hours=None, selectors=None
    ):
        """Return time series for multiple channels over the selected window.
        Exact selectors take precedence over legacy unique channel IDs.
        direction: 'ds' or 'us'. Returns keyed lists of channel history rows."""
        selectors = list(selectors or [])
        channel_ids = [int(c) for c in channel_ids]
        targets = (
            [(selector, {"selector": selector}) for selector in selectors]
            if selectors
            else [(channel_id, {"channel_id": channel_id}) for channel_id in channel_ids]
        )
        cutoff = utc_cutoff(hours=hours) if hours is not None else utc_cutoff(days=days)
        col = "ds_channels_json" if direction == "ds" else "us_channels_json"
        with self._read() as conn:
            rows = conn.execute(
                f"SELECT timestamp, {col} FROM snapshots WHERE timestamp >= ? ORDER BY timestamp",
                (cutoff,),
            ).fetchall()
        results = {key: [] for key, _match_args in targets}
        for ts, channels_json in rows:
            channels = json.loads(channels_json)
            matches = match_channels(
                channels,
                selectors=selectors if selectors else None,
                channel_ids=channel_ids if not selectors else None,
            )
            for key, _match_args in targets:
                channel = matches.get(key)
                if channel is not None:
                    results[key].append(
                        _history_row(ts, channel, include_frequency=True)
                    )
        for rows_for_channel in results.values():
            unwrap_uint32_counter_series(rows_for_channel, _CHANNEL_ERROR_KEYS)
        return results
