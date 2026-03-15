"""Tests for Smart Capture STT adapter and collector import hook."""

import pytest
from unittest.mock import MagicMock, patch

from app.modules.speedtest.collector import SpeedtestCollector
from app.storage import SnapshotStorage
from app.smart_capture.types import ExecutionStatus


@pytest.fixture
def storage(tmp_path):
    return SnapshotStorage(str(tmp_path / "test.db"), max_days=7)


class TestCollectorOnImport:
    def _make_collector(self):
        config = MagicMock()
        config.get = MagicMock(side_effect=lambda k, d=None: {
            "speedtest_tracker_url": "http://stt:8999",
            "speedtest_tracker_token": "test-token",
        }.get(k, d))
        config.is_speedtest_configured = MagicMock(return_value=True)
        storage = MagicMock()
        storage.db_path = ":memory:"
        web = MagicMock()
        with patch("app.modules.speedtest.collector.SpeedtestStorage"):
            collector = SpeedtestCollector(config_mgr=config, storage=storage, web=web)
        collector._storage = MagicMock()
        return collector

    def test_on_import_called_with_new_results_on_delta_sync(self):
        collector = self._make_collector()
        callback = MagicMock()
        collector.on_import = callback

        # Cache is warm (>= 50), so delta sync path is used
        collector._storage.get_latest_speedtest_id.return_value = 10
        collector._storage.get_speedtest_count.return_value = 100

        new_results = [
            {"id": 11, "timestamp": "2026-03-15T10:00:00Z", "download_mbps": 100.0,
             "upload_mbps": 20.0, "download_human": "100 Mbps", "upload_human": "20 Mbps",
             "ping_ms": 10.0, "jitter_ms": 1.0, "packet_loss_pct": 0.0},
        ]

        mock_client = MagicMock()
        mock_client.get_newer_than.return_value = new_results
        mock_client.get_latest_with_error.return_value = (new_results[:1], None)
        collector._client = mock_client
        collector._last_url = "http://stt:8999"  # prevent _ensure_client from overwriting
        collector.collect()

        callback.assert_called_once()
        imported = callback.call_args[0][0]
        assert len(imported) == 1
        assert imported[0]["id"] == 11

    def test_on_import_skipped_during_initial_backfill(self):
        collector = self._make_collector()
        callback = MagicMock()
        collector.on_import = callback

        # Cache is small (< 50), so backfill path is used
        collector._storage.get_latest_speedtest_id.return_value = 0
        collector._storage.get_speedtest_count.return_value = 0

        backfill_results = [
            {"id": i, "timestamp": f"2026-03-{i:02d}T10:00:00Z", "download_mbps": 100.0,
             "upload_mbps": 20.0, "download_human": "100 Mbps", "upload_human": "20 Mbps",
             "ping_ms": 10.0, "jitter_ms": 1.0, "packet_loss_pct": 0.0}
            for i in range(1, 20)
        ]

        mock_client = MagicMock()
        mock_client.get_results.return_value = backfill_results
        mock_client.get_latest_with_error.return_value = (backfill_results[-1:], None)
        collector._client = mock_client
        collector._last_url = "http://stt:8999"
        collector.collect()

        callback.assert_not_called()

    def test_on_import_not_called_when_no_new_results(self):
        collector = self._make_collector()
        callback = MagicMock()
        collector.on_import = callback

        collector._storage.get_latest_speedtest_id.return_value = 10
        collector._storage.get_speedtest_count.return_value = 100

        mock_client = MagicMock()
        mock_client.get_newer_than.return_value = []
        mock_client.get_latest_with_error.return_value = ([], None)
        collector._client = mock_client
        collector._last_url = "http://stt:8999"
        collector.collect()

        callback.assert_not_called()


# ── STT Adapter Tests ──

def _make_config(**overrides):
    defaults = {
        "speedtest_tracker_url": "http://stt:8999",
        "speedtest_tracker_token": "test-token",
    }
    defaults.update(overrides)
    config = MagicMock()
    config.get = lambda key, default=None: defaults.get(key, default)
    return config


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
            from app.smart_capture.adapters.speedtest import SpeedtestAdapter
            adapter = SpeedtestAdapter(storage, config)
            success, error = adapter.execute(eid, {"event_type": "modulation_change"})
        assert success is True
        assert error is None
        row = storage.get_execution(eid)
        assert row["status"] == "fired"
        assert row["fired_at"] is not None

    def test_failed_trigger_sets_expired(self, storage):
        config = _make_config()
        eid = storage.save_execution(
            trigger_type="modulation_change", action_type="capture",
            status=ExecutionStatus.PENDING,
        )
        with patch("app.smart_capture.adapters.speedtest.requests.Session") as MockSession:
            mock_session = MagicMock()
            mock_session.post.return_value = MagicMock(status_code=500, text="Internal Server Error")
            MockSession.return_value = mock_session
            from app.smart_capture.adapters.speedtest import SpeedtestAdapter
            adapter = SpeedtestAdapter(storage, config)
            success, error = adapter.execute(eid, {"event_type": "modulation_change"})
        assert success is False
        assert "500" in error
        row = storage.get_execution(eid)
        assert row["status"] == "expired"
        assert row["attempt_count"] == 1

    def test_connection_error_sets_expired(self, storage):
        config = _make_config()
        eid = storage.save_execution(
            trigger_type="modulation_change", action_type="capture",
            status=ExecutionStatus.PENDING,
        )
        with patch("app.smart_capture.adapters.speedtest.requests.Session") as MockSession:
            mock_session = MagicMock()
            mock_session.post.side_effect = ConnectionError("Connection refused")
            MockSession.return_value = mock_session
            from app.smart_capture.adapters.speedtest import SpeedtestAdapter
            adapter = SpeedtestAdapter(storage, config)
            success, error = adapter.execute(eid, {"event_type": "modulation_change"})
        assert success is False
        row = storage.get_execution(eid)
        assert row["status"] == "expired"


class TestSpeedtestAdapterMatching:
    def _make_adapter(self, storage):
        config = _make_config()
        with patch("app.smart_capture.adapters.speedtest.requests.Session"):
            from app.smart_capture.adapters.speedtest import SpeedtestAdapter
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
        adapter.on_results_imported([{"id": 99, "timestamp": "2026-03-15T10:12:00Z"}])
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
            event_type="modulation_change", action_type="capture",
            require_details={"direction": "downgrade"},
        ))

        with patch("app.smart_capture.adapters.speedtest.requests.Session") as MockSession:
            mock_session = MagicMock()
            mock_session.post.return_value = MagicMock(status_code=201)
            MockSession.return_value = mock_session
            from app.smart_capture.adapters.speedtest import SpeedtestAdapter
            adapter = SpeedtestAdapter(storage, config)

        engine.register_adapter("capture", adapter)

        # Trigger event
        event = {
            "event_type": "modulation_change", "severity": "warning",
            "timestamp": "2026-03-15T10:00:00Z", "message": "QAM drop",
            "details": {"direction": "downgrade"}, "_id": 1,
        }

        with patch.object(adapter, '_session') as mock_sess:
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
