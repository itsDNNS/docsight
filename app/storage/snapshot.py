"""Snapshot CRUD and trend/range queries mixin."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import timedelta
from typing import cast

from ..types import AnalysisResult
from ..tz import _parse_utc, local_date_to_utc_range, utc_cutoff, utc_now
from .error_counters import unwrap_uint32_counter_series


_SUMMARY_ERROR_KEYS = ("ds_correctable_errors", "ds_uncorrectable_errors")
_LONGEST_TREND_RANGE_DAYS = 90
_UNWRAP_PRE_RANGE_ANCHOR_DAYS = 2
_UNWRAP_ANCHOR_DAYS = _LONGEST_TREND_RANGE_DAYS + _UNWRAP_PRE_RANGE_ANCHOR_DAYS

log = logging.getLogger("docsis.storage")


def _normalize_summary_errors(summary):
    """Return summary with unsupported DOCSIS error counters normalized to null."""
    if summary.get("errors_supported") is False:
        summary = dict(summary)
        summary["ds_correctable_errors"] = None
        summary["ds_uncorrectable_errors"] = None
    return summary


def _timestamp_in_range(
    timestamp: str,
    start_ts: str | None = None,
    end_ts: str | None = None,
) -> bool:
    """Return True when a canonical ISO UTC timestamp is inside the optional bounds."""
    if start_ts is not None and timestamp < start_ts:
        return False
    if end_ts is not None and timestamp > end_ts:
        return False
    return True


def _unwrap_anchor_start(timestamp: str) -> str:
    """Return the shared bounded anchor for range-stable uint32 unwrapping.

    Error trend ranges are presentation-level derived values. Anchor unwrapping
    from the query end, not the visible start, so every exposed rolling range up
    to 90 days uses the same unwrap history for the same endpoint while still
    avoiding full-history scans on long-lived installs. Stored timestamps are
    canonical UTC strings, so the result remains lexicographically sortable for
    SQLite filters.
    """
    return (_parse_utc(timestamp) - timedelta(days=_UNWRAP_ANCHOR_DAYS)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


class SnapshotMethods:

    def save_snapshot(self, analysis: AnalysisResult, is_demo: bool = False) -> None:
        """Save current analysis as a snapshot. Runs cleanup afterwards."""
        ts = utc_now()
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO snapshots (timestamp, summary_json, ds_channels_json, us_channels_json, is_demo) VALUES (?, ?, ?, ?, ?)",
                    (
                        ts,
                        json.dumps(analysis["summary"]),
                        json.dumps(analysis["ds_channels"]),
                        json.dumps(analysis["us_channels"]),
                        int(is_demo),
                    ),
                )
            log.debug("Snapshot saved: %s", ts)
        except Exception as e:
            log.error("Failed to save snapshot: %s", e)
            return
        self._cleanup()

    def get_snapshot_list(self) -> list[str]:
        """Return list of available snapshot timestamps (newest first)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT timestamp FROM snapshots ORDER BY timestamp DESC"
            ).fetchall()
        return [r[0] for r in rows]

    def get_latest_snapshot(self) -> AnalysisResult | None:
        """Load the latest stored snapshot, or None when no baseline exists."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT summary_json, ds_channels_json, us_channels_json FROM snapshots ORDER BY timestamp DESC, rowid DESC LIMIT 1"
            ).fetchone()
        if not row:
            return None
        return cast(AnalysisResult, {
            "summary": _normalize_summary_errors(json.loads(row[0])),
            "ds_channels": json.loads(row[1]),
            "us_channels": json.loads(row[2]),
        })

    def get_snapshot(self, timestamp: str) -> AnalysisResult | None:
        """Load a single snapshot by timestamp. Returns analysis dict or None."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT summary_json, ds_channels_json, us_channels_json FROM snapshots WHERE timestamp = ?",
                (timestamp,),
            ).fetchone()
        if not row:
            return None
        return cast(AnalysisResult, {
            "summary": _normalize_summary_errors(json.loads(row[0])),
            "ds_channels": json.loads(row[1]),
            "us_channels": json.loads(row[2]),
        })

    def get_range_data(self, start_ts: str, end_ts: str) -> list[dict]:
        """Get all snapshots between two ISO timestamps (inclusive)."""
        anchor_start = _unwrap_anchor_start(end_ts)
        with self._connect() as conn:
            anchor_rows = conn.execute(
                "SELECT timestamp, summary_json FROM snapshots "
                "WHERE timestamp >= ? AND timestamp < ? ORDER BY timestamp",
                (anchor_start, start_ts),
            ).fetchall()
            visible_rows = conn.execute(
                "SELECT timestamp, summary_json, ds_channels_json, us_channels_json "
                "FROM snapshots WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
                (start_ts, end_ts),
            ).fetchall()
        anchor_entries = []
        for row in anchor_rows:
            anchor_entries.append({
                "timestamp": row[0],
                "summary": _normalize_summary_errors(json.loads(row[1])),
            })
        visible_entries = []
        for row in visible_rows:
            visible_entries.append({
                "timestamp": row[0],
                "summary": _normalize_summary_errors(json.loads(row[1])),
                "ds_channels": json.loads(row[2]),
                "us_channels": json.loads(row[3]),
            })
        unwrap_uint32_counter_series(
            (entry["summary"] for entry in [*anchor_entries, *visible_entries]),
            _SUMMARY_ERROR_KEYS,
            allow_aggregate_wrap=True,
        )
        return visible_entries

    def get_intraday_data(self, date):
        """Get all snapshots for a single day (for day-detail trends).

        date is a local calendar date — converted to UTC range for querying.
        """
        start_utc, end_utc = local_date_to_utc_range(date, self.tz_name)
        anchor_start = _unwrap_anchor_start(end_utc)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT timestamp, summary_json FROM snapshots "
                "WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
                (anchor_start, end_utc),
            ).fetchall()
        results = []
        for row in rows:
            entry = {"timestamp": row[0]}
            entry.update(_normalize_summary_errors(json.loads(row[1])))
            results.append(entry)
        unwrap_uint32_counter_series(
            results,
            _SUMMARY_ERROR_KEYS,
            allow_aggregate_wrap=True,
        )
        return [
            entry for entry in results
            if _timestamp_in_range(entry["timestamp"], start_utc, end_utc)
        ]

    def _summary_rows_to_entries(
        self,
        rows,
        start_ts: str | None = None,
        end_ts: str | None = None,
    ):
        results = []
        for row in rows:
            entry = {"timestamp": row[0]}
            entry.update(_normalize_summary_errors(json.loads(row[1])))
            results.append(entry)
        unwrap_uint32_counter_series(
            results,
            _SUMMARY_ERROR_KEYS,
            allow_aggregate_wrap=True,
        )
        return [
            entry for entry in results
            if _timestamp_in_range(entry["timestamp"], start_ts, end_ts)
        ]

    def get_summary_since(self, hours):
        """Get summary snapshots from the last N hours."""
        cutoff = utc_cutoff(hours=hours)
        anchor_start = utc_cutoff(hours=_UNWRAP_ANCHOR_DAYS * 24)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT timestamp, summary_json FROM snapshots "
                "WHERE timestamp >= ? ORDER BY timestamp",
                (anchor_start,),
            ).fetchall()
        return self._summary_rows_to_entries(rows, start_ts=cutoff)

    def get_summary_range(self, start_date, end_date):
        """Get all snapshots (summary only) between two dates. Like get_intraday_data but multi-day.

        start_date and end_date are local calendar dates — converted to UTC range.
        """
        range_start, _ = local_date_to_utc_range(start_date, self.tz_name)
        _, range_end = local_date_to_utc_range(end_date, self.tz_name)
        anchor_start = _unwrap_anchor_start(range_end)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT timestamp, summary_json FROM snapshots "
                "WHERE timestamp >= ? AND timestamp <= ? "
                "ORDER BY timestamp",
                (anchor_start, range_end),
            ).fetchall()
        return self._summary_rows_to_entries(
            rows,
            start_ts=range_start,
            end_ts=range_end,
        )

    def get_closest_snapshot(self, timestamp: str) -> dict | None:
        """Find the snapshot closest to a given ISO timestamp (within 2 hours).
        Returns analysis dict with timestamp, or None if nothing within range.

        All timestamps are now stored as UTC with Z suffix.
        """
        ts_param = timestamp
        with self._connect() as conn:
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
            "summary": _normalize_summary_errors(json.loads(row[1])),
            "ds_channels": json.loads(row[2]),
            "us_channels": json.loads(row[3]),
        }

    def get_current_channels(self):
        """Return DS and US channels from the latest snapshot."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT ds_channels_json, us_channels_json FROM snapshots ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
        if not row:
            return {"ds_channels": [], "us_channels": []}
        return {
            "ds_channels": json.loads(row[0]),
            "us_channels": json.loads(row[1]),
        }
