"""Tests for demo mode: is_demo marking, purge, double-seed idempotency, and migration."""

import json
import sqlite3
import pytest
from unittest.mock import MagicMock, patch

import app.analyzer as analyzer
from app.collectors.demo import (
    DEMO_BNETZ_CAMPAIGN_OFFSETS_DAYS,
    DEMO_BQM_DAYS,
    DEMO_CONNECTION_MONITOR_DAYS,
    DEMO_CONNECTION_MONITOR_INTERVAL_SECONDS,
    DEMO_CONNECTION_MONITOR_TARGETS,
    DEMO_HISTORY_DAYS,
    DEMO_HISTORY_INTERVAL_MINUTES,
    DEMO_SPEEDTEST_HOURS,
    DEMO_TRACEROUTE_TRACE_CONFIGS,
    DEMO_WEATHER_DAYS,
    DemoCollector,
)
from app.storage import SnapshotStorage
from app.modules.speedtest.storage import SpeedtestStorage
from app.modules.bqm.storage import BqmStorage
from app.modules.bnetz.storage import BnetzStorage
from app.modules.journal.storage import JournalStorage
from app.web import app, init_config, init_storage
from app.config import ConfigManager


@pytest.fixture
def storage(tmp_path):
    db_path = str(tmp_path / "test.db")
    return SnapshotStorage(db_path, max_days=0)


@pytest.fixture
def journal_storage(storage):
    return JournalStorage(storage.db_path)


@pytest.fixture
def config_mgr(tmp_path):
    data_dir = str(tmp_path / "data")
    mgr = ConfigManager(data_dir)
    mgr.save({"demo_mode": True})
    return mgr


@pytest.fixture
def sample_analysis():
    return {
        "summary": {
            "ds_total": 1,
            "us_total": 1,
            "health": "good",
            "health_issues": [],
        },
        "ds_channels": [{
            "channel_id": 1,
            "frequency": "602 MHz",
            "power": 3.0,
            "snr": 35.0,
            "modulation": "256QAM",
            "correctable_errors": 100,
            "uncorrectable_errors": 5,
            "docsis_version": "3.0",
            "health": "good",
            "health_detail": "",
        }],
        "us_channels": [{
            "channel_id": 1,
            "frequency": "37 MHz",
            "power": 42.0,
            "modulation": "64QAM",
            "multiplex": "ATDMA",
            "docsis_version": "3.0",
            "health": "good",
            "health_detail": "",
        }],
    }


@pytest.fixture
def client(config_mgr, storage):
    init_config(config_mgr)
    init_storage(storage)
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


# ── Helper: seed some demo rows via storage directly ──

def _seed_demo_rows(storage):
    """Insert demo-flagged rows into all 7 tables."""
    # Ensure module tables exist
    SpeedtestStorage(storage.db_path)
    BqmStorage(storage.db_path)
    BnetzStorage(storage.db_path)
    _js = JournalStorage(storage.db_path)
    with sqlite3.connect(storage.db_path) as conn:
        conn.execute(
            "INSERT INTO snapshots (timestamp, summary_json, ds_channels_json, us_channels_json, is_demo) "
            "VALUES ('2025-01-01T00:00:00', '{}', '[]', '[]', 1)"
        )
        conn.execute(
            "INSERT INTO events (timestamp, severity, event_type, message, is_demo) "
            "VALUES ('2025-01-01T00:00:00', 'info', 'test', 'demo event', 1)"
        )
    _js.save_entry("2025-01-01", "Demo Entry", "demo desc", is_demo=True)
    _js.save_incident(name="Demo Incident", description="demo", is_demo=True)
    with sqlite3.connect(storage.db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO speedtest_results "
            "(id, timestamp, download_mbps, upload_mbps, download_human, upload_human, "
            "ping_ms, jitter_ms, packet_loss_pct, is_demo) "
            "VALUES (9999, '2025-01-01T00:00:00', 100, 40, '100 Mbps', '40 Mbps', 10, 2, 0, 1)"
        )
        conn.execute(
            "INSERT OR IGNORE INTO bqm_graphs (date, timestamp, image_blob, is_demo) "
            "VALUES ('2025-01-01', '2025-01-01T00:00:00', X'89504E47', 1)"
        )
        conn.execute(
            "INSERT INTO bnetz_measurements "
            "(date, timestamp, provider, tariff, download_max_tariff, download_normal_tariff, "
            "download_min_tariff, upload_max_tariff, upload_normal_tariff, upload_min_tariff, "
            "download_measured_avg, upload_measured_avg, measurement_count, "
            "verdict_download, verdict_upload, measurements_json, source, is_demo) "
            "VALUES ('2025-01-01', '2025-01-01T00:00:00', 'Vodafone Kabel', 'Cable 250', "
            "250, 200, 150, 40, 30, 10, 220, 35, 5, 'ok', 'ok', '{}', 'upload', 1)"
        )


def _seed_user_rows(storage):
    """Insert user-created rows (is_demo=0) into key tables."""
    _js = JournalStorage(storage.db_path)
    with sqlite3.connect(storage.db_path) as conn:
        conn.execute(
            "INSERT INTO snapshots (timestamp, summary_json, ds_channels_json, us_channels_json, is_demo) "
            "VALUES ('2025-06-01T12:00:00', '{\"health\":\"good\"}', '[]', '[]', 0)"
        )
        conn.execute(
            "INSERT INTO events (timestamp, severity, event_type, message, is_demo) "
            "VALUES ('2025-06-01T12:00:00', 'warning', 'test', 'user event', 0)"
        )
    _js.save_entry("2025-06-01", "User Entry", "user desc", is_demo=False)
    _js.save_incident(name="User Incident", description="user inc", is_demo=False)


def _count_rows(storage, table, is_demo=None):
    """Count rows in a table, optionally filtered by is_demo."""
    with sqlite3.connect(storage.db_path) as conn:
        if is_demo is not None:
            return conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE is_demo = ?", (int(is_demo),)
            ).fetchone()[0]
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# ── Schema Migration Tests ──


class TestIsDemoColumn:
    def test_is_demo_column_exists(self, storage):
        """All 7 demo-seeded tables should have an is_demo column."""
        # Ensure module tables exist
        SpeedtestStorage(storage.db_path)
        BqmStorage(storage.db_path)
        BnetzStorage(storage.db_path)
        JournalStorage(storage.db_path)
        tables = ["snapshots", "events", "journal_entries", "incidents",
                   "speedtest_results", "bqm_graphs", "bnetz_measurements"]
        with sqlite3.connect(storage.db_path) as conn:
            for tbl in tables:
                cols = [r[1] for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()]
                assert "is_demo" in cols, f"is_demo column missing from {tbl}"

    def test_is_demo_defaults_to_zero(self, storage, journal_storage):
        """Normal inserts should default is_demo to 0."""
        journal_storage.save_entry("2025-01-01", "Normal", "desc")
        with sqlite3.connect(storage.db_path) as conn:
            row = conn.execute(
                "SELECT is_demo FROM journal_entries ORDER BY id DESC LIMIT 1"
            ).fetchone()
        assert row[0] == 0


# ── Demo Marking Tests ──


class TestDemoMarking:
    def test_save_entry_marks_demo(self, storage, journal_storage):
        entry_id = journal_storage.save_entry("2025-01-01", "Demo", "desc", is_demo=True)
        with sqlite3.connect(storage.db_path) as conn:
            row = conn.execute(
                "SELECT is_demo FROM journal_entries WHERE id = ?", (entry_id,)
            ).fetchone()
        assert row[0] == 1

    def test_save_incident_marks_demo(self, storage, journal_storage):
        inc_id = journal_storage.save_incident(name="Demo Inc", is_demo=True)
        with sqlite3.connect(storage.db_path) as conn:
            row = conn.execute(
                "SELECT is_demo FROM incidents WHERE id = ?", (inc_id,)
            ).fetchone()
        assert row[0] == 1

    def test_save_snapshot_default_not_demo(self, storage, sample_analysis):
        storage.save_snapshot(sample_analysis)
        with sqlite3.connect(storage.db_path) as conn:
            row = conn.execute(
                "SELECT is_demo FROM snapshots ORDER BY id DESC LIMIT 1"
            ).fetchone()
        assert row[0] == 0

    def test_save_snapshot_marks_demo(self, storage, sample_analysis):
        storage.save_snapshot(sample_analysis, is_demo=True)
        with sqlite3.connect(storage.db_path) as conn:
            row = conn.execute(
                "SELECT is_demo FROM snapshots ORDER BY id DESC LIMIT 1"
            ).fetchone()
        assert row[0] == 1

    def test_demo_collector_live_poll_rows_are_demo_and_purgeable(self, storage, sample_analysis):
        web = MagicMock()
        web._state = {}
        detector = MagicMock()
        detector.check.return_value = [{
            "timestamp": "2026-07-02T00:00:00Z",
            "severity": "info",
            "event_type": "demo_event",
            "message": "demo event",
        }]
        collector = DemoCollector(
            analyzer_fn=MagicMock(return_value=sample_analysis),
            event_detector=detector,
            storage=storage,
            mqtt_pub=None,
            web=web,
            poll_interval=900,
        )

        with patch.object(collector, "_seed_demo_data"), \
             patch.object(collector, "_generate_data", return_value={}):
            collector.collect()

        with sqlite3.connect(storage.db_path) as conn:
            snapshot_row = conn.execute(
                "SELECT is_demo FROM snapshots ORDER BY id DESC LIMIT 1"
            ).fetchone()
            event_row = conn.execute(
                "SELECT is_demo FROM events ORDER BY id DESC LIMIT 1"
            ).fetchone()
        assert snapshot_row[0] == 1
        assert event_row[0] == 1

        storage.purge_demo_data()
        assert _count_rows(storage, "snapshots", is_demo=1) == 0
        assert _count_rows(storage, "events", is_demo=1) == 0

    def test_save_events_marks_demo(self, storage):
        events = [
            {"timestamp": "2025-01-01T00:00:00", "severity": "info",
             "event_type": "test", "message": "demo event"},
        ]
        storage.save_events(events, is_demo=True)
        with sqlite3.connect(storage.db_path) as conn:
            row = conn.execute(
                "SELECT is_demo FROM events ORDER BY id DESC LIMIT 1"
            ).fetchone()
        assert row[0] == 1

    def test_save_events_default_not_demo(self, storage):
        events = [
            {"timestamp": "2025-01-01T00:00:00", "severity": "info",
             "event_type": "test", "message": "real event"},
        ]
        storage.save_events(events)
        with sqlite3.connect(storage.db_path) as conn:
            row = conn.execute(
                "SELECT is_demo FROM events ORDER BY id DESC LIMIT 1"
            ).fetchone()
        assert row[0] == 0


# ── Purge Tests ──


class TestPurgeDemoData:
    def test_purge_removes_only_demo(self, storage):
        """Purge should delete is_demo=1 rows and keep is_demo=0 rows."""
        _seed_demo_rows(storage)
        _seed_user_rows(storage)

        # Verify both exist
        assert _count_rows(storage, "journal_entries", is_demo=1) > 0
        assert _count_rows(storage, "journal_entries", is_demo=0) > 0

        storage.purge_demo_data()

        # Demo rows gone
        assert _count_rows(storage, "snapshots", is_demo=1) == 0
        assert _count_rows(storage, "events", is_demo=1) == 0
        assert _count_rows(storage, "journal_entries", is_demo=1) == 0
        assert _count_rows(storage, "incidents", is_demo=1) == 0
        assert _count_rows(storage, "speedtest_results", is_demo=1) == 0
        assert _count_rows(storage, "bqm_graphs", is_demo=1) == 0
        assert _count_rows(storage, "bnetz_measurements", is_demo=1) == 0

        # User rows survive
        assert _count_rows(storage, "snapshots", is_demo=0) == 1
        assert _count_rows(storage, "events", is_demo=0) == 1
        assert _count_rows(storage, "journal_entries", is_demo=0) == 1
        assert _count_rows(storage, "incidents", is_demo=0) == 1

    def test_purge_returns_count(self, storage):
        _seed_demo_rows(storage)
        total = storage.purge_demo_data()
        assert total >= 7  # at least one row per table

    def test_purge_on_empty_db(self, storage):
        """Purge on empty DB should not error."""
        total = storage.purge_demo_data()
        assert total == 0

    def test_purge_handles_demo_incident_entries(self, storage):
        """Entries assigned to a demo incident should be unassigned, not deleted (if user-created)."""
        _js = JournalStorage(storage.db_path)
        inc_id = _js.save_incident(name="Demo Inc", is_demo=True)
        # User entry assigned to demo incident
        entry_id = _js.save_entry("2025-01-01", "User Entry", "desc", incident_id=inc_id, is_demo=False)

        storage.purge_demo_data()

        # User entry survives with incident_id cleared
        with sqlite3.connect(storage.db_path) as conn:
            row = conn.execute(
                "SELECT incident_id, is_demo FROM journal_entries WHERE id = ?", (entry_id,)
            ).fetchone()
        assert row is not None
        assert row[0] is None  # incident_id unassigned
        assert row[1] == 0  # still user-created


# ── Double Seed Idempotency ──


class TestDoubleSeedIdempotency:
    def test_double_seed_no_duplicates(self, storage):
        """Calling _seed_demo_data twice should not duplicate rows (purge before seed)."""
        # Simulate what DemoCollector._seed_demo_data does
        _seed_demo_rows(storage)
        count_before = _count_rows(storage, "journal_entries", is_demo=1)

        # Second seed: purge + re-seed
        storage.purge_demo_data()
        _seed_demo_rows(storage)
        count_after = _count_rows(storage, "journal_entries", is_demo=1)

        assert count_after == count_before


class TestDemoCollectorOFDMA:
    def _collector(self, storage):
        return DemoCollector(
            analyzer_fn=analyzer.analyze,
            event_detector=MagicMock(),
            storage=storage,
            mqtt_pub=None,
            web=MagicMock(),
            poll_interval=300,
        )

    def test_generate_data_includes_docsis31_upstream_ofdma(self, storage):
        collector = self._collector(storage)
        collector._poll_count = 1

        data = collector._generate_data()

        assert len(data["channelUs"]["docsis31"]) == 1
        ch = data["channelUs"]["docsis31"][0]
        assert ch["type"] == "OFDMA"
        assert ch["modulation"] == "OFDMA"
        assert ch["profile_modulation"] == "256QAM"
        assert ch["powerLevel"] < 44.1

    def test_historical_bad_period_makes_ofdma_problematic(self, storage):
        collector = self._collector(storage)

        analysis = collector._generate_historical_analysis(
            index=0,
            diurnal=0,
            seasonal=0,
            bad_period=True,
            hour=4,
            day_of_year=10,
        )

        ofdma = next(ch for ch in analysis["us_channels"] if ch["docsis_version"] == "3.1")
        assert analysis["summary"]["us_total"] == 5
        assert ofdma["modulation"] == "OFDMA"
        assert ofdma["profile_modulation"] == "128QAM"
        assert ofdma["health"] != "good"
        assert "power" in ofdma["health_detail"]

    def test_historical_normal_period_keeps_ofdma_healthy(self, storage):
        collector = self._collector(storage)

        analysis = collector._generate_historical_analysis(
            index=0,
            diurnal=0,
            seasonal=0,
            bad_period=False,
            hour=12,
            day_of_year=11,
        )

        ofdma = next(ch for ch in analysis["us_channels"] if ch["docsis_version"] == "3.1")
        assert ofdma["modulation"] == "OFDMA"
        assert ofdma["profile_modulation"] == "1024QAM"
        assert ofdma["health"] == "good"

    def test_historical_ofdma_profile_varies_by_time_of_day(self, storage):
        collector = self._collector(storage)

        early = collector._generate_historical_analysis(
            index=0,
            diurnal=0,
            seasonal=0,
            bad_period=False,
            hour=2,
            day_of_year=11,
        )
        midday = collector._generate_historical_analysis(
            index=0,
            diurnal=0,
            seasonal=0,
            bad_period=False,
            hour=12,
            day_of_year=11,
        )
        evening = collector._generate_historical_analysis(
            index=0,
            diurnal=0,
            seasonal=0,
            bad_period=False,
            hour=20,
            day_of_year=11,
        )

        early_ofdma = next(ch for ch in early["us_channels"] if ch["docsis_version"] == "3.1")
        midday_ofdma = next(ch for ch in midday["us_channels"] if ch["docsis_version"] == "3.1")
        evening_ofdma = next(ch for ch in evening["us_channels"] if ch["docsis_version"] == "3.1")

        assert early_ofdma["profile_modulation"] == "512QAM"
        assert midday_ofdma["profile_modulation"] == "1024QAM"
        assert evening_ofdma["profile_modulation"] == "512QAM"


class TestDemoSeedContract:
    def test_demo_seed_contract_keeps_public_journey_surface(self):
        """Demo mode should keep the onboarding/proof data surfaces stable."""
        assert DEMO_HISTORY_DAYS == 270
        assert DEMO_HISTORY_DAYS * 24 * 60 // DEMO_HISTORY_INTERVAL_MINUTES == 25920
        assert DEMO_SPEEDTEST_HOURS == (8, 14, 21)
        assert DEMO_BQM_DAYS == 30
        assert len(DEMO_BNETZ_CAMPAIGN_OFFSETS_DAYS) == 9
        assert DEMO_WEATHER_DAYS == 270
        assert DEMO_CONNECTION_MONITOR_DAYS == 7
        assert DEMO_CONNECTION_MONITOR_INTERVAL_SECONDS == 10
        assert [target[1] for target in DEMO_CONNECTION_MONITOR_TARGETS] == [
            "Gateway",
            "Cloudflare DNS",
            "Google DNS",
        ]
        assert len(DEMO_TRACEROUTE_TRACE_CONFIGS) == 5

    def test_seed_demo_data_invokes_all_supported_demo_surfaces(self, storage, monkeypatch):
        collector = DemoCollector(
            analyzer_fn=analyzer.analyze,
            event_detector=MagicMock(),
            storage=storage,
            mqtt_pub=None,
            web=MagicMock(),
            poll_interval=300,
        )
        calls = []

        for method in (
            "_seed_history",
            "_seed_events",
            "_seed_journal_entries",
            "_seed_speedtest_results",
            "_seed_bqm_graphs",
            "_seed_incident_containers",
            "_seed_bnetz_measurements",
            "_seed_weather_data",
            "_seed_connection_monitor_data",
        ):
            monkeypatch.setattr(collector, method, lambda now, name=method: calls.append(name))

        collector._seed_demo_data()

        assert calls == [
            "_seed_history",
            "_seed_events",
            "_seed_journal_entries",
            "_seed_speedtest_results",
            "_seed_bqm_graphs",
            "_seed_incident_containers",
            "_seed_bnetz_measurements",
            "_seed_weather_data",
            "_seed_connection_monitor_data",
        ]
        assert storage.max_days == 0


# ── Migration Endpoint Tests ──


class TestMigrateEndpoint:
    def test_migrate_purges_demo_and_disables_mode(self, client, storage, config_mgr):
        _seed_demo_rows(storage)
        _seed_user_rows(storage)

        resp = client.post("/api/demo/migrate", content_type="application/json", data="{}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["purged"] >= 6

        # Demo mode disabled
        assert config_mgr.get("demo_mode") is False

        # Demo rows gone, user rows kept
        assert _count_rows(storage, "journal_entries", is_demo=1) == 0
        assert _count_rows(storage, "journal_entries", is_demo=0) == 1

    def test_migrate_rejects_non_demo(self, client, config_mgr):
        config_mgr.save({"demo_mode": False})
        resp = client.post("/api/demo/migrate", content_type="application/json", data="{}")
        assert resp.status_code == 400
        assert "Not in demo mode" in resp.get_json()["error"]

    def test_user_entries_survive_migration(self, client, storage, config_mgr):
        """User-created entries and incidents should survive migration."""
        _seed_demo_rows(storage)
        _seed_user_rows(storage)

        resp = client.post("/api/demo/migrate", content_type="application/json", data="{}")
        assert resp.status_code == 200

        # Verify user data intact
        _js = JournalStorage(storage.db_path)
        entries = _js.get_entries()
        assert len(entries) == 1
        assert entries[0]["title"] == "User Entry"

        incidents = _js.get_incidents()
        assert len(incidents) == 1
        assert incidents[0]["name"] == "User Incident"
