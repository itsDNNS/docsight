"""Snapshot CRUD and trend/range queries mixin."""

import json
import logging
import sqlite3

from ..tz import utc_now, utc_cutoff

log = logging.getLogger("docsis.storage")


class SnapshotMixin:

    def save_snapshot(self, analysis):
        """Save current analysis as a snapshot. Runs cleanup afterwards."""
        ts = utc_now()
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT INTO snapshots (timestamp, summary_json, ds_channels_json, us_channels_json) VALUES (?, ?, ?, ?)",
                    (
                        ts,
                        json.dumps(analysis["summary"]),
                        json.dumps(analysis["ds_channels"]),
                        json.dumps(analysis["us_channels"]),
                    ),
                )
            log.debug("Snapshot saved: %s", ts)
        except Exception as e:
            log.error("Failed to save snapshot: %s", e)
            return
        self._cleanup()

    def get_snapshot_list(self):
        """Return list of available snapshot timestamps (newest first)."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT timestamp FROM snapshots ORDER BY timestamp DESC"
            ).fetchall()
        return [r[0] for r in rows]

    def get_snapshot(self, timestamp):
        """Load a single snapshot by timestamp. Returns analysis dict or None."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT summary_json, ds_channels_json, us_channels_json FROM snapshots WHERE timestamp = ?",
                (timestamp,),
            ).fetchone()
        if not row:
            return None
        return {
            "summary": json.loads(row[0]),
            "ds_channels": json.loads(row[1]),
            "us_channels": json.loads(row[2]),
        }

    def get_dates_with_data(self):
        """Return list of dates (YYYY-MM-DD) that have at least one snapshot.

        Converts UTC timestamps to local dates using the configured timezone,
        so the returned dates match the user's calendar.
        """
        from ..tz import to_local
        tz = self.tz_name
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT DISTINCT timestamp FROM snapshots ORDER BY timestamp"
            ).fetchall()
        # Convert each UTC timestamp to local date and deduplicate
        dates = sorted({to_local(r[0], tz)[:10] for r in rows if r[0]})
        return dates

    def get_daily_snapshot(self, date, target_time="06:00"):
        """Get the snapshot closest to target_time on the given date.

        date and target_time are local concepts — converted to UTC for querying.
        """
        from ..tz import local_date_to_utc_range, local_to_utc as _l2u
        tz = self.tz_name
        start_utc, end_utc = local_date_to_utc_range(date, tz)
        target_utc = _l2u(f"{date}T{target_time}:00", tz)
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """SELECT timestamp, summary_json, ds_channels_json, us_channels_json
                   FROM snapshots
                   WHERE timestamp >= ? AND timestamp <= ?
                   ORDER BY ABS(julianday(timestamp) - julianday(?))
                   LIMIT 1""",
                (start_utc, end_utc, target_utc),
            ).fetchone()
        if not row:
            return None
        return {
            "timestamp": row[0],
            "summary": json.loads(row[1]),
            "ds_channels": json.loads(row[2]),
            "us_channels": json.loads(row[3]),
        }

    def get_trend_data(self, start_date, end_date, target_time="06:00"):
        """Get summary data points for a date range, one per day (closest to target_time).
        Returns list of {date, timestamp, ...summary_fields}.

        start_date and end_date are local calendar dates (YYYY-MM-DD).
        """
        from ..tz import to_local, local_date_to_utc_range
        tz = self.tz_name
        # Get the full UTC range covering both local date boundaries
        range_start, _ = local_date_to_utc_range(start_date, tz)
        _, range_end = local_date_to_utc_range(end_date, tz)
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT DISTINCT timestamp FROM snapshots WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
                (range_start, range_end),
            ).fetchall()
        # Convert UTC timestamps to local dates and deduplicate
        dates = sorted({to_local(r[0], tz)[:10] for r in rows if r[0]})

        results = []
        for date in dates:
            snap = self.get_daily_snapshot(date, target_time)
            if snap:
                entry = {"date": date, "timestamp": snap["timestamp"]}
                entry.update(snap["summary"])
                results.append(entry)
        return results

    def get_range_data(self, start_ts, end_ts):
        """Get all snapshots between two ISO timestamps (inclusive)."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT timestamp, summary_json, ds_channels_json, us_channels_json "
                "FROM snapshots WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
                (start_ts, end_ts),
            ).fetchall()
        results = []
        for row in rows:
            entry = {
                "timestamp": row[0],
                "summary": json.loads(row[1]),
                "ds_channels": json.loads(row[2]),
                "us_channels": json.loads(row[3]),
            }
            results.append(entry)
        return results

    def get_intraday_data(self, date):
        """Get all snapshots for a single day (for day-detail trends).

        date is a local calendar date — converted to UTC range for querying.
        """
        from ..tz import local_date_to_utc_range
        start_utc, end_utc = local_date_to_utc_range(date, self.tz_name)
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT timestamp, summary_json FROM snapshots "
                "WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
                (start_utc, end_utc),
            ).fetchall()
        results = []
        for row in rows:
            entry = {"timestamp": row[0]}
            entry.update(json.loads(row[1]))
            results.append(entry)
        return results

    def get_summary_range(self, start_date, end_date):
        """Get all snapshots (summary only) between two dates. Like get_intraday_data but multi-day.

        start_date and end_date are local calendar dates — converted to UTC range.
        """
        from ..tz import local_date_to_utc_range
        range_start, _ = local_date_to_utc_range(start_date, self.tz_name)
        _, range_end = local_date_to_utc_range(end_date, self.tz_name)
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT timestamp, summary_json FROM snapshots "
                "WHERE timestamp >= ? AND timestamp <= ? "
                "ORDER BY timestamp",
                (range_start, range_end),
            ).fetchall()
        results = []
        for row in rows:
            entry = {"timestamp": row[0]}
            entry.update(json.loads(row[1]))
            results.append(entry)
        return results

    def get_closest_snapshot(self, timestamp):
        """Find the snapshot closest to a given ISO timestamp (within 2 hours).
        Returns analysis dict with timestamp, or None if nothing within range.

        All timestamps are now stored as UTC with Z suffix.
        """
        ts_param = timestamp
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """SELECT timestamp, summary_json, ds_channels_json, us_channels_json
                   FROM snapshots
                   WHERE ABS(julianday(REPLACE(timestamp, 'Z', '')) - julianday(REPLACE(?, 'Z', ''))) <= (2.0 / 24.0)
                   ORDER BY ABS(julianday(REPLACE(timestamp, 'Z', '')) - julianday(REPLACE(?, 'Z', '')))
                   LIMIT 1""",
                (ts_param, ts_param),
            ).fetchone()
        if not row:
            return None
        return {
            "timestamp": row[0],
            "summary": json.loads(row[1]),
            "ds_channels": json.loads(row[2]),
            "us_channels": json.loads(row[3]),
        }

    def get_current_channels(self):
        """Return DS and US channels from the latest snapshot."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT ds_channels_json, us_channels_json FROM snapshots ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
        if not row:
            return {"ds_channels": [], "us_channels": []}
        return {
            "ds_channels": json.loads(row[0]),
            "us_channels": json.loads(row[1]),
        }
