"""Tests for the Smart Capture STT adapter."""

import logging
import sqlite3
from datetime import datetime, timezone

import pytest
import requests
from unittest.mock import MagicMock, patch

from app.modules.speedtest.storage import SpeedtestStorage
from app.smart_capture.adapters.speedtest import SpeedtestAdapter
from app.smart_capture.types import ExecutionStatus
from app.storage import SnapshotStorage
from app.types import EventDict
from tests.test_speedtest import TRACKER_SETTING_CHANGES


@pytest.fixture
def storage(tmp_path):
    return SnapshotStorage(str(tmp_path / "test.db"), max_days=7)


# ── STT Adapter Tests ──

def _make_config(**overrides):
    defaults = {
        "speedtest_tracker_url": "http://stt:8999",
        "speedtest_tracker_token": "test-token",
        "speedtest_tls_insecure": False,
        "sc_speedtest_min_interval": 14400,
        "sc_speedtest_max_actions_per_day": 4,
        "sc_speedtest_match_window": 900,
    }
    defaults.update(overrides)
    config = MagicMock()
    config.get = lambda key, default=None: defaults.get(key, default)
    return config


def _pending_execution(storage, *, trigger_timestamp="2026-03-15T12:00:00Z"):
    return storage.save_execution(
        trigger_type="modulation_change",
        action_type="capture",
        status=ExecutionStatus.PENDING,
        trigger_timestamp=trigger_timestamp,
    )


def _insert_speedtest_result(storage, *, result_id=10, timestamp="2026-03-15T11:30:00Z"):
    SpeedtestStorage(storage.db_path)
    with sqlite3.connect(storage.db_path) as conn:
        conn.execute(
            "INSERT INTO speedtest_results "
            "(id, timestamp, download_mbps, upload_mbps, download_human, upload_human, "
            " ping_ms, jitter_ms, packet_loss_pct, server_id, server_name) "
            "VALUES (?, ?, 100, 20, '100 Mbps', '20 Mbps', 10, 1, 0, 1, 'test')",
            (result_id, timestamp),
        )


def _event(timestamp="2026-03-15T12:00:00Z") -> EventDict:
    return {
        "event_type": "modulation_change",
        "severity": "warning",
        "timestamp": timestamp,
        "message": "Modulation dropped on 1 channel(s)",
    }


class _Response:
    def __init__(self, status_code=201, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


class TestSpeedtestAdapterExecute:
    def test_successful_trigger_sets_fired(self, storage):
        config = _make_config()
        eid = storage.save_execution(
            trigger_type="modulation_change", action_type="capture",
            status=ExecutionStatus.PENDING,
        )
        with patch("app.smart_capture.adapters.speedtest.requests.Session") as MockSession:
            mock_session = MagicMock()
            mock_session.post.return_value = MagicMock(status_code=201)
            MockSession.return_value = mock_session
            adapter = SpeedtestAdapter(storage, config)
            success, error = adapter.execute(eid, {"event_type": "modulation_change"})
        assert success is True
        assert error is None
        assert mock_session.post.call_args.kwargs["verify"] is True
        row = storage.get_execution(eid)
        assert row["status"] == "fired"
        assert row["fired_at"] is not None

    def test_insecure_tls_disables_certificate_verification(self, storage):
        config = _make_config(speedtest_tls_insecure="true")
        eid = storage.save_execution(
            trigger_type="modulation_change", action_type="capture",
            status=ExecutionStatus.PENDING,
        )
        with patch("app.smart_capture.adapters.speedtest.requests.Session") as MockSession:
            mock_session = MagicMock()
            mock_session.post.return_value = MagicMock(status_code=201)
            MockSession.return_value = mock_session
            adapter = SpeedtestAdapter(storage, config)
            success, error = adapter.execute(eid, {
                "timestamp": "2026-03-15T10:00:00Z",
                "severity": "warning",
                "event_type": "modulation_change",
                "message": "modulation changed",
            })
        assert success is True
        assert error is None
        assert mock_session.post.call_args.kwargs["verify"] is False

    def test_string_false_keeps_certificate_verification_enabled(self, storage):
        config = _make_config(speedtest_tls_insecure="false")
        eid = storage.save_execution(
            trigger_type="modulation_change", action_type="capture",
            status=ExecutionStatus.PENDING,
        )
        with patch("app.smart_capture.adapters.speedtest.requests.Session") as MockSession:
            mock_session = MagicMock()
            mock_session.post.return_value = MagicMock(status_code=201)
            MockSession.return_value = mock_session
            adapter = SpeedtestAdapter(storage, config)
            success, error = adapter.execute(eid, {
                "timestamp": "2026-03-15T10:00:00Z",
                "severity": "warning",
                "event_type": "modulation_change",
                "message": "modulation changed",
            })
        assert success is True
        assert error is None
        assert mock_session.post.call_args.kwargs["verify"] is True

    @pytest.mark.parametrize(("post", "expected"), [
        ({"return_value": MagicMock(status_code=500, text="upstream body")}, "STT returned 500"),
        ({"side_effect": ConnectionError("Connection refused")}, "Unexpected error, see the DOCSight log"),
        ({"side_effect": requests.exceptions.InvalidHeader("Invalid header value b'Bearer leaked-token'")},
         "Unexpected error, see the DOCSight log"),
    ])
    def test_failed_trigger_stores_only_a_fixed_error(self, storage, post, expected):
        config = _make_config()
        eid = storage.save_execution(
            trigger_type="modulation_change", action_type="capture",
            status=ExecutionStatus.PENDING,
        )
        with patch("app.smart_capture.adapters.speedtest.requests.Session") as MockSession:
            MockSession.return_value = MagicMock(post=MagicMock(**post))
            adapter = SpeedtestAdapter(storage, config)
            success, error = adapter.execute(eid, {"event_type": "modulation_change"})
        assert (success, error) == (False, expected)
        row = storage.get_execution(eid)
        assert (row["status"], row["attempt_count"], row["last_error"]) == ("expired", 1, expected)

@TRACKER_SETTING_CHANGES
def test_execute_uses_the_changed_tracker_settings(storage, changed):
    adapter = SpeedtestAdapter(storage, _make_config())
    adapter._config = config = _make_config(sc_speedtest_min_interval=0, **changed)
    with patch("app.modules.speedtest.client.requests.Session.post", autospec=True, return_value=_Response()) as post:
        assert adapter.execute(_pending_execution(storage), _event()) == (True, None)

    session, url = post.call_args.args
    assert (url, session.headers["Authorization"], post.call_args.kwargs["verify"]) == (
        config.get("speedtest_tracker_url") + "/api/v1/speedtests/run",
        "Bearer " + config.get("speedtest_tracker_token"), config.get("speedtest_tls_insecure") is not True)


class TestSpeedtestAdapterPreflight:
    def test_recent_tracker_result_suppresses_before_post(self, storage):
        _insert_speedtest_result(storage, timestamp="2026-03-15T11:30:00Z")
        execution_id = _pending_execution(storage, trigger_timestamp="2026-03-15T12:00:00Z")
        adapter = SpeedtestAdapter(storage, _make_config())
        adapter._client.session = MagicMock()
        adapter._client.session.get.side_effect = requests.RequestException("offline")

        ok, reason = adapter.execute(execution_id, _event())

        row = storage.get_execution(execution_id)
        assert ok is False
        assert reason is not None
        assert "recent_speedtest_result" in reason
        assert row["status"] == "suppressed"
        assert "recent_speedtest_result" in row["suppression_reason"]
        adapter._client.session.post.assert_not_called()

    @pytest.mark.parametrize("fields, expected", [
        ({}, datetime(2026, 3, 15, 11, 30, tzinfo=timezone.utc)),
        ({"created_at": 20260315}, None),
        ({"data": {"timestamp": 20260315}}, None),
        ({"created_at": "not a time"}, None),
    ])
    def test_remote_lookup_reads_the_newest_tracker_result(self, storage, caplog, fields, expected):
        adapter = SpeedtestAdapter(storage, _make_config())
        # A Tracker result carries created_at ("Y-m-d H:i:s") and no top-level timestamp.
        item = {"id": 10, "status": "completed", "created_at": "2026-03-15 11:30:00", "data": {}, **fields}
        result = _Response(200, {"data": [item]})
        adapter._client.session = MagicMock(get=MagicMock(return_value=result))
        with caplog.at_level(logging.DEBUG, logger="docsis.smart_capture.adapters.speedtest"):
            assert adapter._fetch_latest_remote_result_timestamp() == expected
        assert adapter._client.session.get.call_args.kwargs["params"] == {
            "page[size]": 1, "page[number]": 1, "sort": "-created_at",
        }
        assert ("latest STT result has no readable time" in caplog.text) == (expected is None)

    def test_failed_remote_lookup_is_logged_without_its_details(self, storage, caplog):
        adapter = SpeedtestAdapter(storage, _make_config())
        adapter._client.session = MagicMock()
        adapter._client.session.get.side_effect = requests.ConnectionError("http://stt:8999/api/v1/results")
        assert adapter._fetch_latest_remote_result_timestamp() is None
        assert [r.getMessage() for r in caplog.records] == [
            "Failed to fetch speedtest results: Cannot reach Speedtest Tracker (ConnectionError)"
        ]

    def test_recent_smart_capture_fire_suppresses_after_adapter_restart(self, storage):
        storage.save_execution(
            trigger_type="modulation_change",
            action_type="capture",
            status=ExecutionStatus.FIRED,
            fired_at="2026-03-15T10:30:00Z",
        )
        execution_id = _pending_execution(storage, trigger_timestamp="2026-03-15T12:00:00Z")
        adapter = SpeedtestAdapter(storage, _make_config())
        adapter._client.session = MagicMock()
        adapter._client.session.get.return_value = _Response(200, {"data": []})

        ok, reason = adapter.execute(execution_id, _event())

        row = storage.get_execution(execution_id)
        assert ok is False
        assert reason is not None
        assert "speedtest_min_interval" in reason
        assert row["status"] == "suppressed"
        adapter._client.session.post.assert_not_called()

    def test_daily_speedtest_smart_capture_budget_is_persistent(self, storage):
        for fired_at in ("2026-03-15T01:00:00Z", "2026-03-15T06:00:00Z"):
            storage.save_execution(
                trigger_type="modulation_change",
                action_type="capture",
                status=ExecutionStatus.FIRED,
                fired_at=fired_at,
            )
        execution_id = _pending_execution(storage, trigger_timestamp="2026-03-15T12:00:00Z")
        adapter = SpeedtestAdapter(
            storage,
            _make_config(sc_speedtest_max_actions_per_day=2, sc_speedtest_min_interval=0),
        )
        adapter._client.session = MagicMock()
        adapter._client.session.get.return_value = _Response(200, {"data": []})

        ok, reason = adapter.execute(execution_id, _event())

        row = storage.get_execution(execution_id)
        assert ok is False
        assert reason is not None
        assert "speedtest_daily_cap" in reason
        assert row["status"] == "suppressed"
        adapter._client.session.post.assert_not_called()

    def test_read_timeout_is_recorded_as_fired_pending_result_link(self, storage):
        execution_id = _pending_execution(storage)
        adapter = SpeedtestAdapter(storage, _make_config(sc_speedtest_min_interval=0))
        adapter._client.session = MagicMock()
        adapter._client.session.get.return_value = _Response(200, {"data": []})
        adapter._client.session.post.side_effect = requests.exceptions.ReadTimeout("slow run")

        ok, reason = adapter.execute(execution_id, _event())

        row = storage.get_execution(execution_id)
        assert ok is True
        assert reason is None
        assert row["status"] == "fired"
        assert row["fired_at"] is not None
        assert "unknown" in row["last_error"]


class TestSpeedtestAdapterMatching:
    def _make_adapter(self, storage):
        config = _make_config()
        with patch("app.smart_capture.adapters.speedtest.requests.Session"):
            return SpeedtestAdapter(storage, config)

    def test_matches_result_in_time_window(self, storage):
        adapter = self._make_adapter(storage)
        eid = storage.save_execution(
            trigger_type="modulation_change", action_type="capture",
            status=ExecutionStatus.FIRED, fired_at="2026-03-15T10:00:05Z",
        )
        adapter.on_results_imported([{"id": 42, "timestamp": "2026-03-15T10:00:42Z"}])
        row = storage.get_execution(eid)
        assert row["status"] == "completed"
        assert row["linked_result_id"] == 42

    def test_ignores_result_outside_window(self, storage):
        adapter = self._make_adapter(storage)
        eid = storage.save_execution(
            trigger_type="modulation_change", action_type="capture",
            status=ExecutionStatus.FIRED, fired_at="2026-03-15T10:00:05Z",
        )
        adapter.on_results_imported([{"id": 99, "timestamp": "2026-03-15T10:20:00Z"}])
        assert storage.get_execution(eid)["status"] == "fired"

    def test_ignores_result_before_fired_at(self, storage):
        adapter = self._make_adapter(storage)
        storage.save_execution(
            trigger_type="modulation_change", action_type="capture",
            status=ExecutionStatus.FIRED, fired_at="2026-03-15T10:00:05Z",
        )
        adapter.on_results_imported([{"id": 99, "timestamp": "2026-03-15T09:55:00Z"}])
        assert len(storage.get_fired_unmatched("capture")) == 1

    def test_fifo_matching_oldest_first(self, storage):
        adapter = self._make_adapter(storage)
        eid1 = storage.save_execution(
            trigger_type="modulation_change", action_type="capture",
            status=ExecutionStatus.FIRED, fired_at="2026-03-15T10:00:00Z",
        )
        eid2 = storage.save_execution(
            trigger_type="modulation_change", action_type="capture",
            status=ExecutionStatus.FIRED, fired_at="2026-03-15T10:00:10Z",
        )
        adapter.on_results_imported([{"id": 42, "timestamp": "2026-03-15T10:00:42Z"}])
        assert storage.get_execution(eid1)["status"] == "completed"
        assert storage.get_execution(eid1)["linked_result_id"] == 42
        assert storage.get_execution(eid2)["status"] == "fired"

    def test_nearest_result_selected(self, storage):
        adapter = self._make_adapter(storage)
        eid = storage.save_execution(
            trigger_type="modulation_change", action_type="capture",
            status=ExecutionStatus.FIRED, fired_at="2026-03-15T10:00:00Z",
        )
        adapter.on_results_imported([
            {"id": 99, "timestamp": "2026-03-15T10:04:00Z"},
            {"id": 42, "timestamp": "2026-03-15T10:00:30Z"},
        ])
        assert storage.get_execution(eid)["linked_result_id"] == 42

    def test_skips_invalid_timestamp(self, storage):
        adapter = self._make_adapter(storage)
        storage.save_execution(
            trigger_type="modulation_change", action_type="capture",
            status=ExecutionStatus.FIRED, fired_at="2026-03-15T10:00:05Z",
        )
        adapter.on_results_imported([{"id": 42, "timestamp": ""}])
        assert len(storage.get_fired_unmatched("capture")) == 1

    def test_matches_offset_bearing_timestamp(self, storage):
        """STT may return timestamps with +00:00 instead of Z."""
        adapter = self._make_adapter(storage)
        eid = storage.save_execution(
            trigger_type="modulation_change", action_type="capture",
            status=ExecutionStatus.FIRED, fired_at="2026-03-15T10:00:05Z",
        )
        adapter.on_results_imported([
            {"id": 42, "timestamp": "2026-03-15T10:00:42+00:00"},
        ])
        assert storage.get_execution(eid)["status"] == "completed"
        assert storage.get_execution(eid)["linked_result_id"] == 42

    def test_converts_non_utc_offset_to_utc(self, storage):
        """Timestamp with +02:00 offset must be converted to UTC for correct matching."""
        adapter = self._make_adapter(storage)
        # fired_at is 10:00:05 UTC
        eid = storage.save_execution(
            trigger_type="modulation_change", action_type="capture",
            status=ExecutionStatus.FIRED, fired_at="2026-03-15T10:00:05Z",
        )
        # Result at 12:00:42+02:00 = 10:00:42 UTC — within window
        adapter.on_results_imported([
            {"id": 42, "timestamp": "2026-03-15T12:00:42+02:00"},
        ])
        assert storage.get_execution(eid)["status"] == "completed"

    def test_handles_fractional_seconds(self, storage):
        adapter = self._make_adapter(storage)
        eid = storage.save_execution(
            trigger_type="modulation_change", action_type="capture",
            status=ExecutionStatus.FIRED, fired_at="2026-03-15T10:00:05Z",
        )
        adapter.on_results_imported([
            {"id": 42, "timestamp": "2026-03-15T10:00:42.123456+00:00"},
        ])
        assert storage.get_execution(eid)["status"] == "completed"

    def test_configured_match_window_can_link_long_running_results(self, storage):
        adapter = SpeedtestAdapter(storage, _make_config(sc_speedtest_match_window=1200))
        eid = storage.save_execution(
            trigger_type="modulation_change", action_type="capture",
            status=ExecutionStatus.FIRED, fired_at="2026-03-15T10:00:00Z",
        )
        adapter.on_results_imported([{"id": 42, "timestamp": "2026-03-15T10:16:40Z"}])
        row = storage.get_execution(eid)
        assert row["status"] == "completed"
        assert row["linked_result_id"] == 42

    def test_configured_match_window_can_reject_late_results(self, storage):
        adapter = SpeedtestAdapter(storage, _make_config(sc_speedtest_match_window=30))
        eid = storage.save_execution(
            trigger_type="modulation_change", action_type="capture",
            status=ExecutionStatus.FIRED, fired_at="2026-03-15T10:00:00Z",
        )
        adapter.on_results_imported([{"id": 42, "timestamp": "2026-03-15T10:00:42Z"}])
        assert storage.get_execution(eid)["status"] == "fired"


# ── E2E & Race Condition Tests ──

class TestEndToEnd:
    def test_full_lifecycle_trigger_to_completion(self, storage):
        """Event -> Engine -> Adapter -> FIRED -> Import -> COMPLETED."""
        from app.smart_capture.engine import SmartCaptureEngine
        from app.smart_capture.types import Trigger

        config = MagicMock()
        config.get = lambda key, default=None: {
            "sc_enabled": True, "sc_global_cooldown": 0,
            "sc_trigger_cooldown": 0, "sc_max_actions_per_hour": 999,
            "sc_flapping_window": 3600, "sc_flapping_threshold": 999,
            "speedtest_tracker_url": "http://stt:8999",
            "speedtest_tracker_token": "test-token",
        }.get(key, default)

        engine = SmartCaptureEngine(storage, config)
        engine.register_trigger(Trigger(
            event_type="modulation_change",
            require_details={"direction": "downgrade"},
        ))

        with patch("app.smart_capture.adapters.speedtest.requests.Session") as MockSession:
            mock_session = MagicMock()
            mock_session.post.return_value = MagicMock(status_code=201)
            MockSession.return_value = mock_session
            adapter = SpeedtestAdapter(storage, config)

        engine.register_speedtest_adapter(adapter)

        # Trigger event
        event = {
            "event_type": "modulation_change", "severity": "warning",
            "timestamp": "2026-03-15T10:00:00Z", "message": "QAM drop",
            "details": {"direction": "downgrade"}, "_id": 1,
        }

        with patch.object(adapter._client, 'session') as mock_sess:
            mock_sess.post.return_value = MagicMock(status_code=201)
            engine.evaluate([event])

        # Verify FIRED
        rows = storage.get_executions(status="fired")
        assert len(rows) == 1
        eid = rows[0]["id"]
        fired_at = rows[0]["fired_at"]

        # Simulate imported speedtest result — timestamp must be after fired_at
        from datetime import datetime, timedelta, timezone
        fired_dt = datetime.strptime(fired_at.rstrip("Z"), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        result_ts = (fired_dt + timedelta(seconds=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        adapter.on_results_imported([
            {"id": 42, "timestamp": result_ts},
        ])

        # Verify COMPLETED
        row = storage.get_execution(eid)
        assert row["status"] == "completed"
        assert row["linked_result_id"] == 42


class TestEventEmission:
    def test_fired_execution_emits_event(self, storage):
        config = _make_config()
        with patch("app.smart_capture.adapters.speedtest.requests.Session") as MockSession:
            mock_session = MagicMock()
            mock_session.post.return_value = MagicMock(status_code=201)
            MockSession.return_value = mock_session
            adapter = SpeedtestAdapter(storage, config)

        eid = storage.save_execution(
            trigger_type="modulation_change", action_type="capture",
            status=ExecutionStatus.PENDING,
        )

        with patch.object(adapter._client, 'session') as mock_sess:
            mock_sess.post.return_value = MagicMock(status_code=201)
            adapter.execute(eid, {
                "event_type": "modulation_change", "severity": "warning",
                "timestamp": "2026-03-16T10:00:00Z",
                "message": "Modulation dropped on 1 channel(s)",
            })

        events = storage.get_events(event_type="smart_capture_triggered")
        assert len(events) == 1
        assert events[0]["severity"] == "info"
        assert "modulation" in events[0]["message"].lower()

    def test_failed_execution_no_event(self, storage):
        config = _make_config()
        with patch("app.smart_capture.adapters.speedtest.requests.Session") as MockSession:
            mock_session = MagicMock()
            mock_session.post.return_value = MagicMock(status_code=500, text="error")
            MockSession.return_value = mock_session
            adapter = SpeedtestAdapter(storage, config)

        eid = storage.save_execution(
            trigger_type="modulation_change", action_type="capture",
            status=ExecutionStatus.PENDING,
        )
        adapter.execute(eid, {"event_type": "modulation_change"})

        events = storage.get_events(event_type="smart_capture_triggered")
        assert len(events) == 0


class TestExpiryRace:
    def test_claim_prevents_double_transition(self, storage):
        """If expiry runs while matching is in progress, claim_execution prevents conflict."""
        eid = storage.save_execution(
            trigger_type="modulation_change", action_type="capture",
            status=ExecutionStatus.FIRED, fired_at="2026-03-15T09:00:00Z",
        )
        # Matching claims first
        ok1 = storage.claim_execution(eid, expected_status="fired",
                                      new_status=ExecutionStatus.COMPLETED,
                                      linked_result_id=42)
        assert ok1 is True
        # Expiry tries same row — should fail
        ok2 = storage.claim_execution(eid, expected_status="fired",
                                      new_status=ExecutionStatus.EXPIRED)
        assert ok2 is False
        assert storage.get_execution(eid)["status"] == "completed"

    def test_expiry_after_matching_window(self, storage):
        """FIRED execution not matched within 10min gets expired."""
        storage.save_execution(
            trigger_type="modulation_change", action_type="capture",
            status=ExecutionStatus.FIRED, fired_at="2026-03-15T09:00:00Z",
        )
        count = storage.expire_stale_fired("2026-03-15T09:11:00Z", action_type="capture")
        assert count == 1
        rows = storage.get_executions()
        assert rows[0]["status"] == "expired"
        assert "no matching" in rows[0]["last_error"]
