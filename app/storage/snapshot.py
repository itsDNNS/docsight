"""Snapshot CRUD and trend/range queries mixin."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import timedelta
from typing import Any, cast

from ..analyzer import get_analysis_metadata
from ..types import AnalysisResult, DocsisData
from ..tz import _parse_utc, local_date_to_utc_range, utc_cutoff, utc_now
from ..version import get_available_app_version
from .error_counters import unwrap_uint32_counter_series


_SUMMARY_ERROR_KEYS = ("ds_correctable_errors", "ds_uncorrectable_errors")
_LONGEST_TREND_RANGE_DAYS = 90
_UNWRAP_PRE_RANGE_ANCHOR_DAYS = 2
_UNWRAP_ANCHOR_DAYS = _LONGEST_TREND_RANGE_DAYS + _UNWRAP_PRE_RANGE_ANCHOR_DAYS
MAX_RAW_SNAPSHOT_BYTES = 512 * 1024
_SENSITIVE_RAW_KEYS = {
    "authorization",
    "cookie",
    "csrf",
    "key",
    "password",
    "secret",
    "session",
    "token",
}

log = logging.getLogger("docsis.storage")


def _normalize_summary_errors(summary):
    """Return summary with unsupported DOCSIS error counters normalized to null."""
    if summary.get("errors_supported") is False:
        summary = dict(summary)
        summary["ds_correctable_errors"] = None
        summary["ds_uncorrectable_errors"] = None
    return summary


def _load_analysis_meta(raw: str | None) -> dict | None:
    """Load optional snapshot provenance metadata."""
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _load_raw_data(raw: str | None) -> dict | None:
    """Load optional raw snapshot evidence payload."""
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _redact_raw_value(value: Any) -> Any:
    """Return a JSON-safe raw payload with obvious secret-bearing keys redacted."""
    if isinstance(value, dict):
        cleaned = {}
        for key, child in value.items():
            key_text = str(key)
            if any(marker in key_text.lower() for marker in _SENSITIVE_RAW_KEYS):
                cleaned[key_text] = "[REDACTED]"
            else:
                cleaned[key_text] = _redact_raw_value(child)
        return cleaned
    if isinstance(value, list):
        return [_redact_raw_value(child) for child in value]
    if isinstance(value, tuple):
        return [_redact_raw_value(child) for child in value]
    return value


def _dump_raw_data(raw_data: DocsisData | dict[str, Any] | None) -> str | None:
    """Serialize raw snapshot evidence when it is JSON-safe and bounded."""
    if raw_data is None:
        return None
    try:
        payload = json.dumps(_redact_raw_value(raw_data), separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError):
        log.warning("Skipping raw snapshot payload: payload is not JSON serializable")
        return None
    if len(payload.encode("utf-8")) > MAX_RAW_SNAPSHOT_BYTES:
        log.warning("Skipping raw snapshot payload: payload exceeds %d bytes", MAX_RAW_SNAPSHOT_BYTES)
        return None
    return payload


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

    def save_snapshot(
        self,
        analysis: AnalysisResult,
        is_demo: bool = False,
        raw_data: DocsisData | dict[str, Any] | None = None,
    ) -> None:
        """Save current analysis as a snapshot. Runs cleanup afterwards."""
        ts = utc_now()
        analysis_meta = get_analysis_metadata(app_version=get_available_app_version())
        raw_json = _dump_raw_data(raw_data)
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO snapshots (timestamp, summary_json, ds_channels_json, us_channels_json, is_demo, raw_json, analysis_meta_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        ts,
                        json.dumps(analysis["summary"]),
                        json.dumps(analysis["ds_channels"]),
                        json.dumps(analysis["us_channels"]),
                        int(is_demo),
                        raw_json,
                        json.dumps(analysis_meta),
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
                "SELECT summary_json, ds_channels_json, us_channels_json, analysis_meta_json, raw_json FROM snapshots ORDER BY timestamp DESC, rowid DESC LIMIT 1"
            ).fetchone()
        if not row:
            return None
        return cast(AnalysisResult, {
            "summary": _normalize_summary_errors(json.loads(row[0])),
            "ds_channels": json.loads(row[1]),
            "us_channels": json.loads(row[2]),
            "analysis_meta": _load_analysis_meta(row[3]),
            "raw_data": _load_raw_data(row[4]),
        })

    def get_snapshot(self, timestamp: str) -> AnalysisResult | None:
        """Load a single snapshot by timestamp. Returns analysis dict or None."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT summary_json, ds_channels_json, us_channels_json, analysis_meta_json, raw_json FROM snapshots WHERE timestamp = ?",
                (timestamp,),
            ).fetchone()
        if not row:
            return None
        return cast(AnalysisResult, {
            "summary": _normalize_summary_errors(json.loads(row[0])),
            "ds_channels": json.loads(row[1]),
            "us_channels": json.loads(row[2]),
            "analysis_meta": _load_analysis_meta(row[3]),
            "raw_data": _load_raw_data(row[4]),
        })

    def get_snapshot_raw_data(self, timestamp: str) -> dict | None:
        """Return the raw driver payload stored with a snapshot, if available."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT raw_json FROM snapshots WHERE timestamp = ?",
                (timestamp,),
            ).fetchone()
        return _load_raw_data(row[0]) if row else None

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
