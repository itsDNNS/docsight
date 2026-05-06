"""Tests for modulation performance API routes (v2)."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.web import app, init_config, init_storage
from app.config import ConfigManager
from app.storage import SnapshotStorage


def _ts_days_ago(days):
    """Return a UTC ISO timestamp for N days ago at 10:00."""
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.replace(hour=10, minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_blueprint():
    """Register the modulation blueprint if not already registered."""
    existing = {b.name for b in app.blueprints.values()}
    if "modulation_bp" not in existing:
        from app.modules.modulation.routes import bp
        app.register_blueprint(bp)


_ensure_blueprint()


@pytest.fixture
def config_mgr(tmp_path):
    data_dir = str(tmp_path / "data")
    mgr = ConfigManager(data_dir)
    mgr.save({"modem_password": "test", "modem_type": "fritzbox", "timezone": "UTC"})
    return mgr


@pytest.fixture
def client_no_storage(config_mgr):
    init_config(config_mgr)
    init_storage(None)
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client
    init_storage(None)


@pytest.fixture
def client_with_storage(tmp_path, config_mgr):
    db_path = str(tmp_path / "modulation_test.db")
    storage = SnapshotStorage(db_path, max_days=7)
    storage.set_timezone("UTC")
    init_config(config_mgr)
    init_storage(storage)
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client, storage
    init_storage(None)


def _store_snapshot(storage, timestamp, us_channels=None, ds_channels=None):
    """Insert a snapshot directly into the database with a specific timestamp."""
    import sqlite3
    summary = {"ds_total": len(ds_channels or []), "us_total": len(us_channels or [])}
    with sqlite3.connect(storage.db_path) as conn:
        conn.execute(
            "INSERT INTO snapshots (timestamp, summary_json, ds_channels_json, us_channels_json) VALUES (?, ?, ?, ?)",
            (timestamp, json.dumps(summary), json.dumps(ds_channels or []), json.dumps(us_channels or [])),
        )


# ── Distribution endpoint (v2) ──

class TestDistributionEndpoint:
    def test_no_storage_returns_503(self, client_no_storage):
        resp = client_no_storage.get("/api/modulation/distribution")
        assert resp.status_code == 503

    def test_empty_storage_returns_empty(self, client_with_storage):
        client, _ = client_with_storage
        resp = client.get("/api/modulation/distribution")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["sample_count"] == 0
        assert data["protocol_groups"] == []

    def test_default_params(self, client_with_storage):
        client, storage = client_with_storage
        _store_snapshot(storage, _ts_days_ago(1),
                        us_channels=[{"modulation": "64QAM", "channel_id": 1, "docsis_version": "3.0"}])
        resp = client.get("/api/modulation/distribution")
        data = resp.get_json()
        assert data["direction"] == "us"

    def test_direction_param_ds(self, client_with_storage):
        client, storage = client_with_storage
        _store_snapshot(storage, _ts_days_ago(1),
                        us_channels=[{"modulation": "64QAM", "channel_id": 1, "docsis_version": "3.0"}],
                        ds_channels=[{"modulation": "256QAM", "channel_id": 1, "docsis_version": "3.0"}])
        resp = client.get("/api/modulation/distribution?direction=ds")
        data = resp.get_json()
        assert data["direction"] == "ds"
        assert len(data["protocol_groups"]) > 0
        pg = data["protocol_groups"][0]
        assert "256QAM" in pg["distribution"]

    def test_invalid_direction_defaults_to_us(self, client_with_storage):
        client, _ = client_with_storage
        resp = client.get("/api/modulation/distribution?direction=invalid")
        data = resp.get_json()
        assert data["direction"] == "us"

    def test_days_param(self, client_with_storage):
        client, _ = client_with_storage
        resp = client.get("/api/modulation/distribution?days=1")
        assert resp.status_code == 200

    def test_response_has_protocol_groups(self, client_with_storage):
        client, storage = client_with_storage
        _store_snapshot(storage, _ts_days_ago(1),
                        us_channels=[{"modulation": "64QAM", "channel_id": 1, "docsis_version": "3.0"}])
        resp = client.get("/api/modulation/distribution")
        data = resp.get_json()
        assert "protocol_groups" in data
        assert "aggregate" in data
        assert "sample_count" in data
        assert "expected_samples" in data
        assert "sample_density" in data
        assert "disclaimer" in data


    def test_aggregate_low_qam_pct_weighted_across_protocol_sample_counts(self, client_with_storage):
        client, storage = client_with_storage
        day = _ts_days_ago(1)[:10]
        _store_snapshot(
            storage,
            f"{day}T08:00:00Z",
            us_channels=[{"modulation": "16QAM", "channel_id": 1, "docsis_version": "3.0"}],
        )
        for idx in range(100):
            _store_snapshot(
                storage,
                f"{day}T09:{idx % 60:02d}:00Z",
                us_channels=[
                    {"modulation": "1024QAM", "channel_id": 10, "docsis_version": "3.1"},
                ],
            )

        resp = client.get("/api/modulation/distribution?days=7&direction=us")
        data = resp.get_json()

        assert data["aggregate"]["low_qam_pct"] == 1.0
        assert data["aggregate"]["low_qam_pct"] != 50.0

    def test_protocol_group_structure(self, client_with_storage):
        client, storage = client_with_storage
        _store_snapshot(storage, _ts_days_ago(1),
                        us_channels=[{"modulation": "64QAM", "channel_id": 1, "docsis_version": "3.0"}])
        resp = client.get("/api/modulation/distribution")
        data = resp.get_json()
        pg = data["protocol_groups"][0]
        assert "docsis_version" in pg
        assert "max_qam" in pg
        assert "channel_count" in pg
        assert "health_index" in pg
        assert "distribution" in pg
        assert "days" in pg
        assert "degraded_channel_count" in pg

    def test_disclaimer_present(self, client_with_storage):
        client, _ = client_with_storage
        resp = client.get("/api/modulation/distribution")
        data = resp.get_json()
        assert "disclaimer" in data
        assert len(data["disclaimer"]) > 0


# ── Intraday endpoint ──

class TestIntradayEndpoint:
    def test_no_storage_returns_503(self, client_no_storage):
        resp = client_no_storage.get("/api/modulation/intraday")
        assert resp.status_code == 503

    def test_empty_storage_returns_empty(self, client_with_storage):
        client, _ = client_with_storage
        resp = client.get("/api/modulation/intraday?date=2026-03-01")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["protocol_groups"] == []
        assert data["date"] == "2026-03-01"

    def test_returns_channel_timeline(self, client_with_storage):
        client, storage = client_with_storage
        _store_snapshot(storage, "2026-03-05T10:00:00Z",
                        us_channels=[{"modulation": "64QAM", "channel_id": 1,
                                      "docsis_version": "3.0", "frequency": "51.000"}])
        _store_snapshot(storage, "2026-03-05T14:00:00Z",
                        us_channels=[{"modulation": "16QAM", "channel_id": 1,
                                      "docsis_version": "3.0", "frequency": "51.000"}])
        resp = client.get("/api/modulation/intraday?direction=us&date=2026-03-05")
        data = resp.get_json()
        assert len(data["protocol_groups"]) == 1
        pg = data["protocol_groups"][0]
        assert len(pg["channels"]) == 1
        ch = pg["channels"][0]
        assert ch["channel_id"] == 1
        assert len(ch["timeline"]) >= 1

    def test_direction_param(self, client_with_storage):
        client, storage = client_with_storage
        _store_snapshot(storage, "2026-03-05T10:00:00Z",
                        ds_channels=[{"modulation": "256QAM", "channel_id": 1,
                                      "docsis_version": "3.0", "frequency": "114.000"}])
        resp = client.get("/api/modulation/intraday?direction=ds&date=2026-03-05")
        data = resp.get_json()
        assert data["direction"] == "ds"
        assert len(data["protocol_groups"]) > 0

    def test_disclaimer_present(self, client_with_storage):
        client, _ = client_with_storage
        resp = client.get("/api/modulation/intraday?date=2026-03-01")
        data = resp.get_json()
        assert "disclaimer" in data


# ── Trend endpoint (legacy) ──

class TestTrendEndpoint:
    def test_no_storage_returns_503(self, client_no_storage):
        resp = client_no_storage.get("/api/modulation/trend")
        assert resp.status_code == 503

    def test_empty_storage_returns_empty_list(self, client_with_storage):
        client, _ = client_with_storage
        resp = client.get("/api/modulation/trend")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_returns_per_day_entries(self, client_with_storage):
        client, storage = client_with_storage
        ts_2 = _ts_days_ago(2)
        ts_1 = _ts_days_ago(1)
        _store_snapshot(storage, ts_2,
                        us_channels=[{"modulation": "64QAM", "channel_id": 1, "docsis_version": "3.0"}])
        _store_snapshot(storage, ts_1,
                        us_channels=[{"modulation": "256QAM", "channel_id": 1, "docsis_version": "3.0"}])
        resp = client.get("/api/modulation/trend?days=7")
        data = resp.get_json()
        assert len(data) == 2
        assert data[0]["date"] == ts_2[:10]
        assert data[1]["date"] == ts_1[:10]

    def test_trend_entry_fields(self, client_with_storage):
        client, storage = client_with_storage
        _store_snapshot(storage, _ts_days_ago(1),
                        us_channels=[{"modulation": "64QAM", "channel_id": 1, "docsis_version": "3.0"}])
        resp = client.get("/api/modulation/trend")
        data = resp.get_json()
        assert len(data) == 1
        entry = data[0]
        assert "date" in entry
        assert "health_index" in entry
        assert "low_qam_pct" in entry
        assert "dominant_modulation" in entry
        assert "sample_count" in entry

    def test_weighted_low_qam_pct_preserved_for_partial_exposure(self, client_with_storage):
        client, storage = client_with_storage
        day = _ts_days_ago(1)[:10]
        for hour in range(10, 14):
            _store_snapshot(
                storage,
                f"{day}T{hour:02d}:00:00Z",
                us_channels=[
                    {"modulation": "64QAM", "channel_id": 1, "docsis_version": "3.0"},
                    {"modulation": "64QAM", "channel_id": 2, "docsis_version": "3.0"},
                ],
            )
        _store_snapshot(
            storage,
            f"{day}T14:00:00Z",
            us_channels=[
                {"modulation": "16QAM", "channel_id": 1, "docsis_version": "3.0"},
                {"modulation": "64QAM", "channel_id": 2, "docsis_version": "3.0"},
            ],
        )

        resp = client.get("/api/modulation/trend?days=7&direction=us")
        data = resp.get_json()

        assert len(data) == 1
        assert data[0]["low_qam_pct"] == 10.0
        assert data[0]["low_qam_pct"] != 100.0



# ── JSON response format ──

class TestResponseFormat:
    def test_content_type_json(self, client_with_storage):
        client, _ = client_with_storage
        resp = client.get("/api/modulation/distribution")
        assert resp.content_type.startswith("application/json")

    def test_trend_content_type_json(self, client_with_storage):
        client, _ = client_with_storage
        resp = client.get("/api/modulation/trend")
        assert resp.content_type.startswith("application/json")

    def test_intraday_content_type_json(self, client_with_storage):
        client, _ = client_with_storage
        resp = client.get("/api/modulation/intraday?date=2026-03-01")
        assert resp.content_type.startswith("application/json")
