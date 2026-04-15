"""Speedtest Tracker action adapter -- triggers STT runs and links results."""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

import requests

from ...tz import utc_now
from ...types import EventDict
from ..types import ExecutionStatus
from .base import ActionAdapter

log = logging.getLogger("docsis.smart_capture.adapters.speedtest")

MATCH_WINDOW_SECONDS = 300  # 5 minutes


class SpeedtestAdapter(ActionAdapter):
    """Triggers a Speedtest Tracker run and matches imported results."""

    def __init__(self, storage, config_mgr):
        super().__init__(action_type="capture")
        self._storage = storage
        self._config = config_mgr
        url = config_mgr.get("speedtest_tracker_url", "").rstrip("/")
        token = config_mgr.get("speedtest_tracker_token", "")
        self._run_url = f"{url}/api/v1/speedtests/run"
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        })

    def execute(self, execution_id: int, event: EventDict) -> tuple[bool, str | None]:
        """POST to STT run endpoint. Updates execution to FIRED or EXPIRED."""
        try:
            resp = self._session.post(self._run_url, timeout=15)
            if resp.status_code == 201:
                ts = utc_now()
                self._storage.update_execution(
                    execution_id,
                    status=ExecutionStatus.FIRED,
                    fired_at=ts,
                )
                # Emit event for Event Log visibility
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
                    },
                )
                log.info("Smart Capture: triggered STT run (execution #%d)", execution_id)
                return True, None
            else:
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

    def on_results_imported(self, results: list[dict[str, Any]]) -> None:
        """Match newly imported speedtest results to FIRED executions.

        For each FIRED execution (FIFO, oldest first), find the closest
        result within the match window. This ensures the nearest result
        is selected when multiple results fall in the same window.
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

        for execution in fired:
            fired_ts = self._parse_timestamp(execution.get("fired_at", ""))
            if fired_ts is None:
                continue

            # Find the closest result within [fired_at, fired_at + 5min]
            window_end = fired_ts + timedelta(seconds=MATCH_WINDOW_SECONDS)
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
