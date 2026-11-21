"""Tests for speedtest, backup, and BQM collectors."""

import time
from datetime import datetime
from unittest.mock import MagicMock, call, patch

import pytest

from app.modules.speedtest.collector import SpeedtestCollector
from app.modules.bqm.collector import BQMCollector


DELTA_ROWS = [
    {"id": 1, "timestamp": "2025-01-01T00:00:00Z", "download_mbps": 100,
     "upload_mbps": 10, "download_human": "", "upload_human": "",
     "ping_ms": 5, "jitter_ms": 1, "packet_loss_pct": 0},
    {"id": 2, "timestamp": "2025-01-01T01:00:00Z", "download_mbps": 200,
     "upload_mbps": 20, "download_human": "", "upload_human": "",
     "ping_ms": 5, "jitter_ms": 1, "packet_loss_pct": 0},
]


@pytest.mark.usefixtures("class_mock_storage")
class TestSpeedtestCollector:
    def _make_collector(self, configured=True):
        config_mgr = MagicMock()
        config_mgr.is_speedtest_configured.return_value = configured
        config_mgr.is_demo_mode.return_value = False
        config_mgr.get.side_effect = lambda k, *a: {
            "speedtest_tracker_url": "http://speed:8999",
            "speedtest_tracker_token": "tok",
        }.get(k, a[0] if a else None)

        web = MagicMock()

        c = SpeedtestCollector(config_mgr=config_mgr, storage=self.storage, web=web, poll_interval=300)
        return c, config_mgr, self.storage, web

    def test_is_enabled_true(self):
        c, *_ = self._make_collector(configured=True)
        assert c.is_enabled() is True

    def test_is_enabled_false(self):
        c, *_ = self._make_collector(configured=False)
        assert c.is_enabled() is False

    @pytest.fixture
    def client_cls(self):
        """The patched client class; its client finds no newer result and reads DELTA_ROWS in full."""
        with patch("app.modules.speedtest.collector.SpeedtestClient") as cls:
            cls.from_config.return_value = cls.return_value
            cls.return_value.base_url = "http://speed:8999"
            cls.return_value.get_latest_with_error.return_value = ([], None)
            cls.return_value.get_results_with_error.return_value = (DELTA_ROWS, None)
            yield cls

    def test_collect_keeps_the_client_while_its_settings_apply(self, client_cls):
        c, config_mgr, *_ = self._make_collector()
        c.collect()
        c.collect()
        assert client_cls.from_config.call_args_list == [call(config_mgr, None), call(config_mgr, client_cls.return_value)]

    @pytest.mark.parametrize("cached", [[], [DELTA_ROWS[0]]], ids=["nothing-finished", "finished-cached"])
    def test_collect_shows_newest_cached_result(self, client_cls, cached):
        """The dashboard shows the newest finished result even when only running tests are newer."""
        client_cls.return_value.get_latest_with_error.return_value = ([{"id": 9, "status": "running"}], None)
        client_cls.return_value.get_results_with_error.return_value = (cached, None)

        c, _, _, web = self._make_collector()
        c.collect()
        assert [call.kwargs["speedtest_latest"]["id"] for call in web.update_state.call_args_list] == [r["id"] for r in cached]
        assert web.clear_speedtest_latest.called == (not cached)

    def test_collect_fetch_failure_returns_error(self, client_cls):
        client_cls.return_value.get_latest_with_error.return_value = ([], "ConnectionError: refused")

        c, _, _, web = self._make_collector()
        result = c.collect()
        assert result.success is False
        assert "ConnectionError" in result.error
        web.update_state.assert_not_called()

    def test_collect_delta_cache(self, client_cls):
        c, *_ = self._make_collector()
        c.collect()
        # Verify results were saved to the module's internal storage
        assert c._storage.get_speedtest_count() == 2

    def test_collect_delta_cache_failure_does_not_crash(self, client_cls):
        """Delta cache failure should not prevent a successful collect result."""
        client_cls.return_value.get_results_with_error.side_effect = Exception("API timeout")

        c, *_ = self._make_collector()
        assert c.collect().success is True

    def test_name(self):
        c, *_ = self._make_collector()
        assert c.name == "speedtest"


# ── BackupCollector Tests ──


class TestBackupCollector:
    def _make_collector(self, configured=True, interval_hours=24, backups=None):
        config_mgr = MagicMock()
        config_mgr.is_backup_configured.return_value = configured
        config_mgr.data_dir = "/data"
        config_mgr.get.side_effect = lambda k, *a: {
            "backup_path": "/backup",
            "backup_interval_hours": interval_hours,
            "backup_retention": 5,
        }.get(k, a[0] if a else None)

        from app.modules.backup.collector import BackupCollector
        with patch("app.modules.backup.backup.list_backups", return_value=backups or []):
            c = BackupCollector(config_mgr=config_mgr)
        return c, config_mgr

    def test_name(self):
        c, _ = self._make_collector()
        assert c.name == "backup"

    def test_is_enabled(self):
        c, _ = self._make_collector(configured=True)
        assert c.is_enabled() is True
        c2, _ = self._make_collector(configured=False)
        assert c2.is_enabled() is False

    def test_interval_from_config(self):
        c, _ = self._make_collector(interval_hours=168)
        assert c._poll_interval_seconds == 168 * 3600

    def test_seed_last_poll_from_disk(self):
        """_last_poll is seeded from newest backup file on init."""
        from datetime import datetime, timedelta
        two_hours_ago = (datetime.now() - timedelta(hours=2)).isoformat()
        backups = [{"filename": "docsight_backup_test.tar.gz", "size": 100, "modified": two_hours_ago}]
        c, _ = self._make_collector(backups=backups)
        # _last_poll should be close to 2h ago, not 0
        assert c._last_poll > 0
        age = time.time() - c._last_poll
        assert 7000 < age < 7400  # ~2h in seconds

    def test_seed_no_backups_leaves_last_poll_zero(self):
        """No backups on disk → _last_poll stays 0, first backup runs immediately."""
        c, _ = self._make_collector(backups=[])
        assert c._last_poll == 0.0

    def test_should_poll_false_after_seed(self):
        """Container restart with recent backup → should_poll() returns False."""
        from datetime import datetime, timedelta
        one_hour_ago = (datetime.now() - timedelta(hours=1)).isoformat()
        backups = [{"filename": "docsight_backup_test.tar.gz", "size": 100, "modified": one_hour_ago}]
        c, _ = self._make_collector(interval_hours=24, backups=backups)
        assert c.should_poll() is False

    def test_should_poll_true_when_backup_expired(self):
        """Backup older than interval → should_poll() returns True."""
        from datetime import datetime, timedelta
        two_days_ago = (datetime.now() - timedelta(days=2)).isoformat()
        backups = [{"filename": "docsight_backup_old.tar.gz", "size": 100, "modified": two_days_ago}]
        c, _ = self._make_collector(interval_hours=24, backups=backups)
        assert c.should_poll() is True

    def test_seed_includes_manual_backups(self):
        """Seed uses newest backup regardless of source (scheduled or manual).

        After a restart, _last_poll anchors to the newest file on disk.
        This means a manual backup can shift the automatic schedule, which
        is by design: the guarantee is "at least one backup every <interval>".
        """
        from datetime import datetime, timedelta
        one_hour_ago = (datetime.now() - timedelta(hours=1)).isoformat()
        backups = [{"filename": "docsight_backup_2026-03-15_120000.tar.gz", "size": 100, "modified": one_hour_ago}]
        c, _ = self._make_collector(interval_hours=24, backups=backups)
        # _last_poll is seeded from the file, so should_poll() waits
        assert c.should_poll() is False

    @patch("app.modules.backup.backup.create_backup_to_file")
    @patch("app.modules.backup.backup.cleanup_old_backups")
    def test_collect_creates_backup(self, mock_cleanup, mock_create):
        mock_create.return_value = "docsight_backup_2026-03-15.tar.gz"
        c, _ = self._make_collector()
        result = c.collect()
        assert result.success is True
        mock_create.assert_called_once()
        mock_cleanup.assert_called_once()


# ── BQMCollector Tests ──


def _clock(hm):
    """Fix the collector's configured-zone clock at ``hm`` on 2026-02-19."""
    return patch("app.modules.bqm.collector.local_now", return_value=datetime.fromisoformat(f"2026-02-19T{hm}"))


@pytest.mark.usefixtures("class_mock_storage")
class TestBQMCollector:
    def _make_collector(self, configured=True, collect_time="02:00", bqm_url="https://www.thinkbroadband.com/broadband/monitoring/quality/share/bd77751689f2f7b8d47d99899335aef060c9e768-2-y.csv"):
        config_mgr = MagicMock()
        config_mgr.is_bqm_configured.return_value = configured
        config_mgr.get.side_effect = lambda k, *a: {
            "bqm_collect_time": collect_time,
            "bqm_url": bqm_url,
        }.get(k, a[0] if a else None)

        c = BQMCollector(config_mgr=config_mgr, storage=self.storage, poll_interval=86400)
        return c, config_mgr, self.storage

    def test_is_enabled_true(self):
        c, *_ = self._make_collector(configured=True)
        assert c.is_enabled() is True

    def test_is_enabled_false(self):
        c, *_ = self._make_collector(configured=False)
        assert c.is_enabled() is False

    @patch("app.modules.bqm.collector.parse_bqm_csv")
    @patch("app.modules.bqm.collector.fetch_share_csv")
    def test_collect_success(self, mock_fetch, mock_parse):
        mock_fetch.return_value = '"Timestamp",...\n'
        mock_parse.return_value = [{
            "timestamp": "2026-03-15T19:00:00+00:00",
            "date": "2026-03-15",
            "sent_polls": 100,
            "lost_polls": 0,
            "latency_min_ms": 30.0,
            "latency_avg_ms": 35.0,
            "latency_max_ms": 40.0,
            "score": 1,
        }]
        c, _, storage = self._make_collector()
        result = c.collect()
        assert result.success is True
        assert c._last_date is not None
        assert c._storage.get_csv_dates() == ["2026-03-15"]

    @patch("app.modules.bqm.collector.parse_bqm_csv", return_value=[{
        "timestamp": "2026-03-15T19:00:00+00:00",
        "date": "2026-03-15",
        "sent_polls": 100,
        "lost_polls": 0,
        "latency_min_ms": 30.0,
        "latency_avg_ms": 35.0,
        "latency_max_ms": 40.0,
        "score": 1,
    }])
    @patch("app.modules.bqm.collector.fetch_share_csv")
    def test_collect_stores_yesterday_when_before_noon(self, mock_fetch, _mock_parse):
        """Collect always fetches yesterday CSV via share URL."""
        mock_fetch.return_value = '"Timestamp",...\n'
        c, _, storage = self._make_collector(collect_time="02:00")
        c.collect()
        mock_fetch.assert_called_once_with("bd77751689f2f7b8d47d99899335aef060c9e768-2", variant="y")

    @patch("app.modules.bqm.collector.parse_bqm_csv", return_value=[{
        "timestamp": "2026-03-15T19:00:00+00:00",
        "date": "2026-03-15",
        "sent_polls": 100,
        "lost_polls": 0,
        "latency_min_ms": 30.0,
        "latency_avg_ms": 35.0,
        "latency_max_ms": 40.0,
        "score": 1,
    }])
    @patch("app.modules.bqm.collector.fetch_share_csv")
    def test_collect_stores_today_when_after_noon(self, mock_fetch, _mock_parse):
        """Collect time doesn't affect share URL — always fetches yesterday variant."""
        mock_fetch.return_value = '"Timestamp",...\n'
        c, _, storage = self._make_collector(collect_time="14:00")
        c.collect()
        mock_fetch.assert_called_once_with("bd77751689f2f7b8d47d99899335aef060c9e768-2", variant="y")

    @patch("app.modules.bqm.collector.parse_bqm_csv", return_value=[{
        "timestamp": "2026-03-15T19:00:00+00:00",
        "date": "2026-03-15",
        "sent_polls": 100,
        "lost_polls": 0,
        "latency_min_ms": 30.0,
        "latency_avg_ms": 35.0,
        "latency_max_ms": 40.0,
        "score": 1,
    }])
    @patch("app.modules.bqm.collector.fetch_share_csv")
    def test_collect_skips_same_day(self, mock_fetch, _mock_parse):
        mock_fetch.return_value = '"Timestamp",...\n'
        c, _, storage = self._make_collector()
        c.collect()
        result = c.collect()
        assert result.data == {"skipped": True, "reason": "already_collected"}
        assert mock_fetch.call_count == 1

    @patch("app.modules.bqm.collector.fetch_share_csv")
    def test_collect_fetch_failure(self, mock_fetch):
        mock_fetch.return_value = ""
        c, _, storage = self._make_collector()
        result = c.collect()
        assert result.success is False
        assert "download" in result.error
        assert c._storage.get_csv_dates() == []

    @patch("app.modules.bqm.collector.collect_bqm", return_value={"success": True, "mode": "png", "date": "2026-02-18"})
    def test_collect_delegates_to_collect_bqm(self, mock_collect):
        url = "https://www.thinkbroadband.com/broadband/monitoring/quality/share/bd77751689f2f7b8d47d99899335aef060c9e768-2.png"
        c, *_ = self._make_collector(bqm_url=url)
        with _clock("02:00"):
            result = c.collect()
        assert result.data["mode"] == "png"
        mock_collect.assert_called_once_with(c._storage, url, "2026-02-19", "2026-02-18")

    @patch("app.modules.bqm.collector.collect_bqm")
    def test_collect_skips_csv_url_without_share_id(self, mock_collect):
        c, *_ = self._make_collector(bqm_url="https://example.com/graph-y.csv")
        assert c.collect().data == {"skipped": True, "reason": "no_share_id"}
        mock_collect.assert_not_called()

    def test_name(self):
        c, *_ = self._make_collector()
        assert c.name == "bqm"

    @patch("app.modules.bqm.collector.random")
    def test_should_poll_before_target(self, mock_random):
        """Should not poll if current time is before target + spread offset."""
        mock_random.randint.return_value = 30  # 30 min offset -> target 02:30
        c, *_ = self._make_collector(collect_time="02:00")
        with _clock("02:25"):
            assert c.should_poll() is False

    @patch("app.modules.bqm.collector.random")
    def test_should_poll_after_target(self, mock_random):
        """Should poll if current time is at/after target + spread offset."""
        mock_random.randint.return_value = 30  # 30 min offset -> target 02:30
        c, *_ = self._make_collector(collect_time="02:00")
        with _clock("02:30"):
            assert c.should_poll() is True

    @patch("app.modules.bqm.collector.random")
    def test_should_poll_not_twice_same_day(self, mock_random):
        """Should not poll again after collecting today."""
        mock_random.randint.return_value = 0
        c, *_ = self._make_collector(collect_time="02:00")
        c._last_date = "2026-02-19"
        with _clock("03:00"):
            assert c.should_poll() is False

    @pytest.mark.parametrize("failures", [1, 3])
    @patch("app.modules.bqm.collector.random")
    def test_should_poll_waits_for_backoff_after_failure(self, mock_random, failures):
        """A failed fetch past the scheduled time is retried only after the backoff penalty."""
        mock_random.randint.return_value = 0
        c, *_ = self._make_collector(collect_time="02:00")
        for _ in range(failures):
            c.record_failure()
        penalty = c._penalty_seconds_unlocked()
        with _clock("03:00"):
            c._last_poll -= penalty - 1
            assert c.should_poll() is False
            c._last_poll -= 1
            assert c.should_poll() is True

    @patch("app.modules.bqm.collector.random")
    def test_spread_offset_within_range(self, mock_random):
        """Spread offset should be between 0 and 120 minutes."""
        mock_random.randint.return_value = 42
        c, *_ = self._make_collector()
        assert c._spread_offset == 42
        mock_random.randint.assert_called_with(0, 120)

    @patch("app.modules.bqm.collector.random")
    def test_spread_clamped_to_0030(self, mock_random):
        """Spread must never schedule collection before 00:30."""
        mock_random.randint.return_value = 0  # 00:20 + 0 = 00:20 -> clamp 00:30
        c, *_ = self._make_collector(collect_time="00:20")
        with _clock("00:25"):
            assert c.should_poll() is False  # 00:25 < 00:30

        with _clock("00:30"):
            assert c.should_poll() is True  # 00:30 >= 00:30

    @patch("app.modules.bqm.collector.random")
    def test_spread_offset_capped_at_2359(self, mock_random):
        """Spread offset is capped at 23:59, never wraps past midnight."""
        mock_random.randint.return_value = 120  # 22:00 + 120 min = 24:00 -> cap 23:59
        c, *_ = self._make_collector(collect_time="22:00")
        with _clock("23:59"):
            assert c.should_poll() is True


# ── build_collectors Tests ──

