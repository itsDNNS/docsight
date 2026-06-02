"""Tests for Signal Trends range normalization."""

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app.config import ConfigManager
from app.storage import SnapshotStorage
from app.web import app, init_config, init_storage


def _utc_ts(delta: timedelta) -> str:
    return (datetime.now(timezone.utc) - delta).strftime("%Y-%m-%dT%H:%M:%SZ")


def _analysis(
    ds_power_avg: float,
    *,
    ds_correctable_errors: int | None = None,
    ds_uncorrectable_errors: int | None = None,
):
    summary = {
        "ds_total": 1,
        "us_total": 1,
        "health": "good",
        "health_issues": [],
        "ds_power_avg": ds_power_avg,
        "ds_snr_avg": 38.0,
        "us_power_avg": 42.0,
    }
    if ds_correctable_errors is not None:
        summary["ds_correctable_errors"] = ds_correctable_errors
    if ds_uncorrectable_errors is not None:
        summary["ds_uncorrectable_errors"] = ds_uncorrectable_errors
    return {
        "summary": summary,
        "ds_channels": [],
        "us_channels": [],
    }


def _insert_snapshot(storage, analysis, timestamp):
    with sqlite3.connect(storage.db_path) as conn:
        conn.execute(
            "INSERT INTO snapshots (timestamp, summary_json, ds_channels_json, us_channels_json) VALUES (?, ?, ?, ?)",
            (
                timestamp,
                json.dumps(analysis["summary"]),
                json.dumps(analysis["ds_channels"]),
                json.dumps(analysis["us_channels"]),
            ),
        )


@pytest.fixture
def client(tmp_path):
    db_path = str(tmp_path / "api.db")
    storage = SnapshotStorage(db_path, max_days=120)
    data_dir = str(tmp_path / "data")
    manager = ConfigManager(data_dir)
    manager.save({"modem_password": "test", "modem_type": "fritzbox"})
    init_config(manager)
    init_storage(storage)
    app.config["TESTING"] = True
    with app.test_client() as flask_client:
        yield flask_client, storage


class TestTrendsRangeEndpoint:
    def test_range_param_supports_one_hour_window(self, client):
        flask_client, storage = client
        _insert_snapshot(storage, _analysis(1.0), _utc_ts(timedelta(hours=2)))
        _insert_snapshot(storage, _analysis(2.0), _utc_ts(timedelta(minutes=20)))

        resp = flask_client.get("/api/trends?range=1h")

        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert len(data) == 1
        assert data[0]["ds_power_avg"] == 2.0

    def test_range_param_supports_normalized_day_window(self, client):
        flask_client, storage = client
        _insert_snapshot(storage, _analysis(1.0), _utc_ts(timedelta(days=2)))
        _insert_snapshot(storage, _analysis(2.0), _utc_ts(timedelta(hours=2)))

        resp = flask_client.get("/api/trends?range=1d")

        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert len(data) == 1
        assert data[0]["ds_power_avg"] == 2.0

    def test_legacy_trend_ranges_still_work(self, client):
        flask_client, storage = client
        storage.save_snapshot(_analysis(2.0))

        for range_name in ("day", "week", "month"):
            resp = flask_client.get(f"/api/trends?range={range_name}")
            assert resp.status_code == 200, range_name

    def test_normalized_ranges_ignore_legacy_date_parameter(self, client):
        flask_client, storage = client
        storage.save_snapshot(_analysis(2.0))

        resp = flask_client.get("/api/trends?range=1d&date=not-a-date")

        assert resp.status_code == 200

    def test_legacy_ranges_still_validate_date_parameter(self, client):
        flask_client, storage = client
        storage.save_snapshot(_analysis(2.0))

        resp = flask_client.get("/api/trends?range=week&date=not-a-date")

        assert resp.status_code == 400

    def test_invalid_range_param_is_rejected(self, client):
        flask_client, storage = client
        storage.save_snapshot(_analysis(2.0))

        resp = flask_client.get("/api/trends?range=4h")

        assert resp.status_code == 400

    def test_trends_unwrap_32bit_error_counter_rollover(self, client):
        flask_client, storage = client
        _insert_snapshot(
            storage,
            _analysis(
                1.0,
                ds_correctable_errors=4_294_495_351,
                ds_uncorrectable_errors=0,
            ),
            _utc_ts(timedelta(minutes=2)),
        )
        _insert_snapshot(
            storage,
            _analysis(
                2.0,
                ds_correctable_errors=692_254,
                ds_uncorrectable_errors=0,
            ),
            _utc_ts(timedelta(minutes=1)),
        )

        resp = flask_client.get("/api/trends?range=1d")

        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert [row["ds_correctable_errors"] for row in data] == [
            4_294_495_351,
            4_295_659_550,
        ]

    def test_trend_error_counter_unwrap_is_stable_across_ranges(self, client):
        flask_client, storage = client
        _insert_snapshot(
            storage,
            _analysis(
                1.0,
                ds_correctable_errors=4_200_000_000,
                ds_uncorrectable_errors=4_100_000_000,
            ),
            _utc_ts(timedelta(days=91)),
        )
        _insert_snapshot(
            storage,
            _analysis(
                2.0,
                ds_correctable_errors=500_000_000,
                ds_uncorrectable_errors=200_000_000,
            ),
            _utc_ts(timedelta(hours=5)),
        )
        _insert_snapshot(
            storage,
            _analysis(
                3.0,
                ds_correctable_errors=700_000_000,
                ds_uncorrectable_errors=300_000_000,
            ),
            _utc_ts(timedelta(minutes=20)),
        )

        values_by_range = {}
        middle_values_by_range = {}
        raw_summaries_before_api = []
        with sqlite3.connect(storage.db_path) as conn:
            raw_summaries_before_api = [
                row[0]
                for row in conn.execute(
                    "SELECT summary_json FROM snapshots ORDER BY timestamp"
                ).fetchall()
            ]
        for range_name in ("1h", "6h", "1d", "30d", "90d"):
            resp = flask_client.get(f"/api/trends?range={range_name}")
            assert resp.status_code == 200, range_name
            data = json.loads(resp.data)
            latest = data[-1]
            assert latest["ds_power_avg"] == 3.0
            values_by_range[range_name] = (
                latest["ds_correctable_errors"],
                latest["ds_uncorrectable_errors"],
            )
            for row in data:
                if row["ds_power_avg"] == 2.0:
                    middle_values_by_range[range_name] = (
                        row["ds_correctable_errors"],
                        row["ds_uncorrectable_errors"],
                    )

        assert values_by_range == {
            "1h": (4_994_967_296, 4_594_967_296),
            "6h": (4_994_967_296, 4_594_967_296),
            "1d": (4_994_967_296, 4_594_967_296),
            "30d": (4_994_967_296, 4_594_967_296),
            "90d": (4_994_967_296, 4_594_967_296),
        }
        assert middle_values_by_range == {
            "6h": (4_794_967_296, 4_494_967_296),
            "1d": (4_794_967_296, 4_494_967_296),
            "30d": (4_794_967_296, 4_494_967_296),
            "90d": (4_794_967_296, 4_494_967_296),
        }
        with sqlite3.connect(storage.db_path) as conn:
            raw_summaries_after_api = [
                row[0]
                for row in conn.execute(
                    "SELECT summary_json FROM snapshots ORDER BY timestamp"
                ).fetchall()
            ]
        assert raw_summaries_after_api == raw_summaries_before_api
