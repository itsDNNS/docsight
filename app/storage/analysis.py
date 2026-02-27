"""Channel history and correlation timeline mixin."""

import json
import sqlite3

from ..tz import utc_cutoff


class AnalysisMixin:

    def get_correlation_timeline(self, start_ts, end_ts, sources=None):
        """Return unified timeline entries from all sources, sorted by timestamp.

        Args:
            start_ts: UTC start timestamp (with Z suffix)
            end_ts: UTC end timestamp (with Z suffix)
            sources: set of source names to include (modem, speedtest, events).
                     None means all.

        Returns list of dicts with 'timestamp', 'source', and source-specific fields.
        """
        if sources is None:
            sources = {"modem", "speedtest", "events", "bnetz"}
        timeline = []

        if "modem" in sources:
            for snap in self.get_range_data(start_ts, end_ts):
                s = snap["summary"]
                timeline.append({
                    "timestamp": snap["timestamp"],
                    "source": "modem",
                    "health": s.get("health", "unknown"),
                    "ds_power_avg": s.get("ds_power_avg"),
                    "ds_power_max": s.get("ds_power_max"),
                    "ds_snr_min": s.get("ds_snr_min"),
                    "ds_snr_avg": s.get("ds_snr_avg"),
                    "us_power_avg": s.get("us_power_avg"),
                    "ds_correctable_errors": s.get("ds_correctable_errors", 0),
                    "ds_uncorrectable_errors": s.get("ds_uncorrectable_errors", 0),
                })

        if "speedtest" in sources:
            for st in self.get_speedtest_in_range(start_ts, end_ts):
                timeline.append({
                    "timestamp": st["timestamp"],
                    "source": "speedtest",
                    "id": st["id"],
                    "download_mbps": st.get("download_mbps"),
                    "upload_mbps": st.get("upload_mbps"),
                    "ping_ms": st.get("ping_ms"),
                    "jitter_ms": st.get("jitter_ms"),
                    "packet_loss_pct": st.get("packet_loss_pct"),
                })

        if "events" in sources:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
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
                    try:
                        event["details"] = json.loads(r["details"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                timeline.append(event)

        if "bnetz" in sources:
            for m in self.get_bnetz_in_range(start_ts, end_ts):
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

        timeline.sort(key=lambda x: x["timestamp"])
        return timeline

    def get_channel_history(self, channel_id, direction, days=7):
        """Return time series for a single channel over the last N days.
        direction: 'ds' or 'us'. Returns list of dicts with timestamp + channel fields."""
        _COL_MAP = {"ds": "ds_channels_json", "us": "us_channels_json"}
        channel_id = int(channel_id)
        col = _COL_MAP[direction]  # validated in web.py to be 'ds' or 'us'
        cutoff = utc_cutoff(days=days)
        with sqlite3.connect(self.db_path) as conn:
            if direction == "ds":
                rows = conn.execute(
                    "SELECT timestamp, ds_channels_json FROM snapshots WHERE timestamp >= ? ORDER BY timestamp",
                    (cutoff,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT timestamp, us_channels_json FROM snapshots WHERE timestamp >= ? ORDER BY timestamp",
                    (cutoff,),
                ).fetchall()
        results = []
        for ts, channels_json in rows:
            channels = json.loads(channels_json)
            for ch in channels:
                if ch.get("channel_id") == channel_id:
                    results.append({
                        "timestamp": ts,
                        "power": ch.get("power"),
                        "snr": ch.get("snr"),
                        "correctable_errors": ch.get("correctable_errors", 0),
                        "uncorrectable_errors": ch.get("uncorrectable_errors", 0),
                        "modulation": ch.get("modulation", ""),
                        "health": ch.get("health", ""),
                    })
                    break
        return results

    def get_multi_channel_history(self, channel_ids, direction, days=7):
        """Return time series for multiple channels over the last N days.
        direction: 'ds' or 'us'. Returns dict {channel_id: [{timestamp, power, snr, ...}, ...]}"""
        channel_ids = [int(c) for c in channel_ids]
        channel_set = set(channel_ids)
        cutoff = utc_cutoff(days=days)
        col = "ds_channels_json" if direction == "ds" else "us_channels_json"
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT timestamp, {col} FROM snapshots WHERE timestamp >= ? ORDER BY timestamp",
                (cutoff,),
            ).fetchall()
        results = {cid: [] for cid in channel_ids}
        for ts, channels_json in rows:
            channels = json.loads(channels_json)
            for ch in channels:
                cid = ch.get("channel_id")
                if cid in channel_set:
                    results[cid].append({
                        "timestamp": ts,
                        "power": ch.get("power"),
                        "snr": ch.get("snr"),
                        "correctable_errors": ch.get("correctable_errors", 0),
                        "uncorrectable_errors": ch.get("uncorrectable_errors", 0),
                        "modulation": ch.get("modulation", ""),
                        "frequency": ch.get("frequency", ""),
                    })
        return results
