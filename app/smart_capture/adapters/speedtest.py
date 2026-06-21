"""Speedtest Tracker action adapter -- triggers STT runs and links results."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone, timedelta
from typing import Any

import requests

from ...tz import utc_now
from ...types import EventDict
from ..types import CAPTURE_ACTION_TYPE, ExecutionStatus

log = logging.getLogger("docsis.smart_capture.adapters.speedtest")

DEFAULT_MATCH_WINDOW_SECONDS = 900  # 15 minutes
_ACCEPTED_STATUS_CODES = {200, 201, 202, 204}


def _as_bool(value: Any) -> bool:
    """Parse booleans from config values."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class SpeedtestAdapter:
    """Triggers a Speedtest Tracker run and matches imported results."""

    def __init__(self, storage, config_mgr):
        self.action_type = CAPTURE_ACTION_TYPE
        self._storage = storage
        self._config = config_mgr
        url = config_mgr.get("speedtest_tracker_url", "").rstrip("/")
        token = config_mgr.get("speedtest_tracker_token", "")
        tls_insecure = _as_bool(config_mgr.get("speedtest_tls_insecure", False))
        self._run_url = f"{url}/api/v1/speedtests/run"
        self._results_url = f"{url}/api/v1/results"
        self._verify_tls = not tls_insecure
        self._execute_lock = threading.Lock()
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        })

    def execute(self, execution_id: int, event: EventDict) -> tuple[bool, str | None]:
        """POST to STT run endpoint after speedtest-specific safety preflight."""
        # Keep preflight and fired_at recording atomic for this adapter instance.
        # Without this, future concurrent execution paths could pass preflight twice
        # before either accepted external side effect is persisted.
        with self._execute_lock:
            return self._execute_locked(execution_id, event)

    def _execute_locked(self, execution_id: int, event: EventDict) -> tuple[bool, str | None]:
        reference_ts = self._parse_timestamp(event.get("timestamp", ""))
        if reference_ts is None:
            reference_ts = datetime.now(timezone.utc)

        suppression_reason = self._preflight_suppression_reason(reference_ts)
        if suppression_reason:
            self._storage.update_execution(
                execution_id,
                status=ExecutionStatus.SUPPRESSED,
                suppression_reason=suppression_reason,
            )
            log.info("Smart Capture: suppressed STT run for #%d (%s)",
                     execution_id, suppression_reason)
            return False, suppression_reason

        try:
            resp = self._session.post(self._run_url, timeout=15, verify=self._verify_tls)
            if resp.status_code in _ACCEPTED_STATUS_CODES:
                self._mark_fired(execution_id, event)
                log.info("Smart Capture: triggered STT run (execution #%d)", execution_id)
                return True, None

            error = f"STT returned {resp.status_code}: {resp.text[:200]}"
            self._storage.update_execution(
                execution_id,
                status=ExecutionStatus.EXPIRED,
                last_error=error,
                attempt_count=1,
            )
            log.warning("Smart Capture: STT trigger failed for #%d: %s",
                        execution_id, error)
            return False, error
        except requests.exceptions.ReadTimeout:
            # The POST reached the remote service but the response did not return in time.
            # Treat it as accepted/unknown so rate limits persist and later imports can link.
            error = "trigger response timeout; external run state unknown, awaiting result import"
            self._mark_fired(execution_id, event, last_error=error)
            log.warning("Smart Capture: STT trigger timeout for #%d; awaiting result import",
                        execution_id)
            return True, None
        except Exception as e:
            error = str(e)
            self._storage.update_execution(
                execution_id,
                status=ExecutionStatus.EXPIRED,
                last_error=error,
                attempt_count=1,
            )
            log.warning("Smart Capture: STT trigger error for #%d: %s",
                        execution_id, error)
            return False, error

    def _mark_fired(self, execution_id: int, event: EventDict,
                    last_error: str | None = None) -> None:
        ts = utc_now()
        self._storage.update_execution(
            execution_id,
            status=ExecutionStatus.FIRED,
            fired_at=ts,
            attempt_count=1,
            last_error=last_error,
        )
        self._storage.save_event(
            timestamp=ts,
            severity="info",
            event_type="smart_capture_triggered",
            message=f"Speedtest triggered by {event.get('event_type', 'unknown')}",
            details={
                "trigger_type": event.get("event_type"),
                "action_type": self.action_type,
                "execution_id": execution_id,
                "source_event": event.get("message", ""),
                "state": "unknown" if last_error else "accepted",
            },
        )

    def _preflight_suppression_reason(self, reference_ts: datetime) -> str | None:
        min_interval = self._get_int("sc_speedtest_min_interval", 14400)
        if min_interval > 0:
            latest_result_ts = self._latest_tracker_result_timestamp()
            reason = self._interval_reason(
                latest_result_ts,
                reference_ts,
                min_interval,
                "recent_speedtest_result",
            )
            if reason:
                return reason

            latest_fire_ts = self._parse_timestamp(
                self._storage.get_latest_smart_capture_fire(self.action_type) or ""
            )
            reason = self._interval_reason(
                latest_fire_ts,
                reference_ts,
                min_interval,
                "speedtest_min_interval",
            )
            if reason:
                return reason

        max_per_day = self._get_int("sc_speedtest_max_actions_per_day", 4)
        if max_per_day > 0:
            cutoff = reference_ts - timedelta(hours=24)
            used = self._storage.count_smart_capture_fires_since(
                self.action_type,
                self._format_utc(cutoff),
            )
            if used >= max_per_day:
                return f"speedtest_daily_cap: {used}/{max_per_day} used in rolling 24h"

        return None

    def _latest_tracker_result_timestamp(self) -> datetime | None:
        timestamps = []
        cached_ts = self._parse_timestamp(
            self._storage.get_latest_speedtest_result_timestamp() or ""
        )
        if cached_ts is not None:
            timestamps.append(cached_ts)

        remote_ts = self._fetch_latest_remote_result_timestamp()
        if remote_ts is not None:
            timestamps.append(remote_ts)

        return max(timestamps) if timestamps else None

    def _fetch_latest_remote_result_timestamp(self) -> datetime | None:
        try:
            resp = self._session.get(
                self._results_url,
                params={"per_page": 1},
                timeout=5,
                verify=self._verify_tls,
            )
            if resp.status_code != 200:
                return None
            payload = resp.json()
            data = payload.get("data", []) if isinstance(payload, dict) else []
            if not data:
                return None
            first = data[0] if isinstance(data[0], dict) else {}
            return self._parse_timestamp(str(first.get("timestamp", "")))
        except Exception:
            return None

    @staticmethod
    def _interval_reason(previous_ts: datetime | None, reference_ts: datetime,
                         min_interval: int, code: str) -> str | None:
        if previous_ts is None:
            return None
        elapsed = (reference_ts - previous_ts).total_seconds()
        if elapsed < 0:
            elapsed = 0
        if elapsed < min_interval:
            remaining = int(min_interval - elapsed)
            return f"{code}: {remaining}s remaining"
        return None

    def _match_window_seconds(self) -> int:
        return max(1, self._get_int("sc_speedtest_match_window", DEFAULT_MATCH_WINDOW_SECONDS))

    def _get_int(self, key: str, default: int) -> int:
        try:
            return int(self._config.get(key, default))
        except (TypeError, ValueError):
            return default

    def on_results_imported(self, results: list[dict[str, Any]]) -> None:
        """Match newly imported speedtest results to FIRED executions.

        For each FIRED execution (FIFO, oldest first), find the closest
        result within the configured match window. This ensures the nearest
        result is selected when multiple results fall in the same window.
        """
        fired = self._storage.get_fired_unmatched(self.action_type)
        if not fired:
            return

        # Parse all result timestamps upfront
        parsed_results = []
        for result in results:
            result_ts = self._parse_timestamp(result.get("timestamp", ""))
            if result_ts is not None:
                parsed_results.append((result, result_ts))

        if not parsed_results:
            return

        matched_result_ids = set()
        match_window = self._match_window_seconds()

        for execution in fired:
            fired_ts = self._parse_timestamp(execution.get("fired_at", ""))
            if fired_ts is None:
                continue

            # Find the closest result within [fired_at, fired_at + window]
            window_end = fired_ts + timedelta(seconds=match_window)
            best_result = None
            best_distance = None

            for result, result_ts in parsed_results:
                if result.get("id") in matched_result_ids:
                    continue
                if fired_ts <= result_ts <= window_end:
                    distance = abs((result_ts - fired_ts).total_seconds())
                    if best_distance is None or distance < best_distance:
                        best_result = result
                        best_distance = distance

            if best_result is not None:
                ok = self._storage.claim_execution(
                    execution["id"],
                    expected_status="fired",
                    new_status=ExecutionStatus.COMPLETED,
                    completed_at=utc_now(),
                    linked_result_id=best_result["id"],
                )
                if ok:
                    log.info("Smart Capture: linked execution #%d to speedtest #%d",
                             execution["id"], best_result["id"])
                    matched_result_ids.add(best_result["id"])

    @staticmethod
    def _format_utc(dt: datetime) -> str:
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    @staticmethod
    def _parse_timestamp(ts: str) -> datetime | None:
        """Parse ISO-8601 timestamp to UTC datetime via fromisoformat().

        Handles Z-suffix, offset-bearing timestamps (+00:00, +02:00),
        and fractional seconds. All results are converted to UTC.
        """
        if not ts:
            return None
        try:
            # fromisoformat handles offsets and fractional seconds natively
            # but needs Z replaced with +00:00 on Python < 3.11
            normalized = ts.replace("Z", "+00:00") if ts.endswith("Z") else ts
            dt = datetime.fromisoformat(normalized)
            # Convert to UTC if offset-aware
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc)
            else:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            return None
