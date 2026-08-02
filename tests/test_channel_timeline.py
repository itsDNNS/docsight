"""Tests for per-channel timeline: storage, /api/channels, /api/channel-history."""

import json
import sqlite3
import time
import pytest
from datetime import datetime, timedelta, timezone

from app.storage import SnapshotStorage
from app.web import app, init_config, init_storage
from app.config import ConfigManager


# ── Fixtures ──

def _utc_ts(delta: timedelta) -> str:
    return (datetime.now(timezone.utc) - delta).strftime("%Y-%m-%dT%H:%M:%SZ")


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


def _make_analysis(ds_channels=None, us_channels=None):
    if ds_channels is None:
        ds_channels = [
            {"channel_id": 1, "frequency": "114.0 MHz", "power": 5.2,
             "modulation": "256QAM", "snr": 38.1, "correctable_errors": 10,
             "uncorrectable_errors": 2, "docsis_version": "3.0",
             "health": "good", "health_detail": ""},
            {"channel_id": 2, "frequency": "130.0 MHz", "power": 4.8,
             "modulation": "256QAM", "snr": 37.5, "correctable_errors": 20,
             "uncorrectable_errors": 0, "docsis_version": "3.0",
             "health": "good", "health_detail": ""},
        ]
    if us_channels is None:
        us_channels = [
            {"channel_id": 1, "frequency": "37 MHz", "power": 42.0,
             "modulation": "64QAM", "multiplex": "ATDMA",
             "docsis_version": "3.0", "health": "good", "health_detail": ""},
        ]
    return {
        "summary": {"ds_total": len(ds_channels), "us_total": len(us_channels),
                     "health": "good", "health_issues": []},
        "ds_channels": ds_channels,
        "us_channels": us_channels,
    }


def _duplicate_id_analysis(first_frequency="634 MHz", second_frequency="738 MHz"):
    return _make_analysis(ds_channels=[
        {"channel_id": 0, "frequency": first_frequency, "power": 4.8,
         "modulation": "256QAM", "snr": 38.1, "correctable_errors": 10,
         "uncorrectable_errors": 2, "docsis_version": "3.0",
         "health": "good", "health_detail": ""},
        {"channel_id": 0, "frequency": second_frequency, "power": -1.7,
         "modulation": "OFDM", "snr": 41.2, "correctable_errors": 20,
         "uncorrectable_errors": 3, "docsis_version": "3.1",
         "health": "warning", "health_detail": "power warning low"},
    ])


@pytest.fixture
def storage(tmp_path):
    db_path = str(tmp_path / "test.db")
    return SnapshotStorage(db_path, max_days=30)


@pytest.fixture
def client(tmp_path):
    db_path = str(tmp_path / "api.db")
    s = SnapshotStorage(db_path, max_days=30)
    data_dir = str(tmp_path / "data")
    mgr = ConfigManager(data_dir)
    mgr.save({"modem_password": "test", "modem_type": "fritzbox"})
    init_config(mgr)
    init_storage(s)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c, s


# ── Storage Tests ──

class TestGetChannelHistory:
    def test_returns_time_series(self, storage):
        storage.save_snapshot(_make_analysis())
        storage.save_snapshot(_make_analysis())
        result = storage.get_channel_history(1, "ds", days=7)
        assert len(result) == 2
        assert result[0]["power"] == 5.2
        assert result[0]["snr"] == 38.1
        assert result[0]["correctable_errors"] == 10
        assert result[0]["uncorrectable_errors"] == 2
        assert result[0]["modulation"] == "256QAM"
        assert result[0]["health"] == "good"
        assert "timestamp" in result[0]

    def test_filters_by_channel_id(self, storage):
        storage.save_snapshot(_make_analysis())
        result_ch1 = storage.get_channel_history(1, "ds", days=7)
        result_ch2 = storage.get_channel_history(2, "ds", days=7)
        assert len(result_ch1) == 1
        assert result_ch1[0]["power"] == 5.2
        assert len(result_ch2) == 1
        assert result_ch2[0]["power"] == 4.8

    def test_upstream_channel(self, storage):
        storage.save_snapshot(_make_analysis())
        result = storage.get_channel_history(1, "us", days=7)
        assert len(result) == 1
        assert result[0]["power"] == 42.0

    def test_nonexistent_channel(self, storage):
        storage.save_snapshot(_make_analysis())
        result = storage.get_channel_history(99, "ds", days=7)
        assert result == []

    def test_empty_storage(self, storage):
        result = storage.get_channel_history(1, "ds", days=7)
        assert result == []

    def test_respects_days_param(self, storage):
        # Save snapshot with a timestamp in the past
        old_ts = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%S")
        analysis = _make_analysis()
        _insert_snapshot(storage, analysis, old_ts)
        # Recent snapshot
        storage.save_snapshot(_make_analysis())
        # 7-day window should only get the recent one
        result = storage.get_channel_history(1, "ds", days=7)
        assert len(result) == 1
        # 30-day window should get both
        result_30 = storage.get_channel_history(1, "ds", days=30)
        assert len(result_30) == 2

    def test_respects_hours_param_for_subday_ranges(self, storage):
        analysis = _make_analysis()
        _insert_snapshot(storage, analysis, _utc_ts(timedelta(hours=2)))
        _insert_snapshot(storage, analysis, _utc_ts(timedelta(minutes=20)))

        result = storage.get_channel_history(1, "ds", hours=1)

        assert len(result) == 1
        assert result[0]["timestamp"] >= _utc_ts(timedelta(hours=1))

    def test_multi_channel_respects_hours_param_for_subday_ranges(self, storage):
        analysis = _make_analysis()
        _insert_snapshot(storage, analysis, _utc_ts(timedelta(hours=2)))
        _insert_snapshot(storage, analysis, _utc_ts(timedelta(minutes=20)))

        result = storage.get_multi_channel_history([1, 2], "ds", hours=1)

        assert len(result[1]) == 1
        assert len(result[2]) == 1

    def test_preserves_unsupported_error_values(self, storage):
        ds = [
            {"channel_id": 1, "frequency": "114.0 MHz", "power": 5.2,
             "modulation": "256QAM", "snr": 38.1, "correctable_errors": None,
             "uncorrectable_errors": None, "docsis_version": "3.0",
             "health": "good", "health_detail": ""},
        ]
        storage.save_snapshot(_make_analysis(ds_channels=ds))

        result = storage.get_channel_history(1, "ds", days=7)

        assert result[0]["correctable_errors"] is None
        assert result[0]["uncorrectable_errors"] is None

    def test_multi_channel_preserves_unsupported_error_values(self, storage):
        ds = [
            {"channel_id": 1, "frequency": "114.0 MHz", "power": 5.2,
             "modulation": "256QAM", "snr": 38.1, "correctable_errors": None,
             "uncorrectable_errors": None, "docsis_version": "3.0",
             "health": "good", "health_detail": ""},
        ]
        storage.save_snapshot(_make_analysis(ds_channels=ds))

        result = storage.get_multi_channel_history([1], "ds", days=7)

        assert result[1][0]["correctable_errors"] is None
        assert result[1][0]["uncorrectable_errors"] is None

    def test_missing_error_values_are_unsupported(self, storage):
        ds = [
            {"channel_id": 1, "frequency": "114.0 MHz", "power": 5.2,
             "modulation": "256QAM", "snr": 38.1, "docsis_version": "3.0",
             "health": "good", "health_detail": ""},
        ]
        storage.save_snapshot(_make_analysis(ds_channels=ds))

        result = storage.get_channel_history(1, "ds", days=7)

        assert result[0]["correctable_errors"] is None
        assert result[0]["uncorrectable_errors"] is None

    def test_multi_channel_missing_error_values_are_unsupported(self, storage):
        ds = [
            {"channel_id": 1, "frequency": "114.0 MHz", "power": 5.2,
             "modulation": "256QAM", "snr": 38.1, "docsis_version": "3.0",
             "health": "good", "health_detail": ""},
        ]
        storage.save_snapshot(_make_analysis(ds_channels=ds))

        result = storage.get_multi_channel_history([1], "ds", days=7)

        assert result[1][0]["correctable_errors"] is None
        assert result[1][0]["uncorrectable_errors"] is None

    def test_unwraps_32bit_downstream_error_counter_wrap(self, storage):
        ds_near_wrap = [
            {"channel_id": 1, "frequency": "114.0 MHz", "power": 5.2,
             "modulation": "OFDM", "snr": 38.1, "correctable_errors": 4_294_495_351,
             "uncorrectable_errors": 0, "docsis_version": "3.1",
             "health": "good", "health_detail": ""},
        ]
        ds_after_wrap = [
            {"channel_id": 1, "frequency": "114.0 MHz", "power": 5.2,
             "modulation": "OFDM", "snr": 38.1, "correctable_errors": 692_254,
             "uncorrectable_errors": 0, "docsis_version": "3.1",
             "health": "good", "health_detail": ""},
        ]
        _insert_snapshot(storage, _make_analysis(ds_channels=ds_near_wrap), _utc_ts(timedelta(minutes=2)))
        _insert_snapshot(storage, _make_analysis(ds_channels=ds_after_wrap), _utc_ts(timedelta(minutes=1)))

        result = storage.get_channel_history(1, "ds", days=7)

        assert [row["correctable_errors"] for row in result] == [
            4_294_495_351,
            4_295_659_550,
        ]

    def test_multi_channel_unwraps_error_counters_per_channel(self, storage):
        first = [
            {"channel_id": 1, "frequency": "114.0 MHz", "power": 5.2,
             "modulation": "OFDM", "snr": 38.1, "correctable_errors": 4_294_495_351,
             "uncorrectable_errors": 10, "docsis_version": "3.1",
             "health": "good", "health_detail": ""},
            {"channel_id": 2, "frequency": "130.0 MHz", "power": 4.8,
             "modulation": "256QAM", "snr": 37.5, "correctable_errors": 20,
             "uncorrectable_errors": 0, "docsis_version": "3.0",
             "health": "good", "health_detail": ""},
        ]
        second = [
            {"channel_id": 1, "frequency": "114.0 MHz", "power": 5.2,
             "modulation": "OFDM", "snr": 38.1, "correctable_errors": 692_254,
             "uncorrectable_errors": 11, "docsis_version": "3.1",
             "health": "good", "health_detail": ""},
            {"channel_id": 2, "frequency": "130.0 MHz", "power": 4.8,
             "modulation": "256QAM", "snr": 37.5, "correctable_errors": 25,
             "uncorrectable_errors": 0, "docsis_version": "3.0",
             "health": "good", "health_detail": ""},
        ]
        _insert_snapshot(storage, _make_analysis(ds_channels=first), _utc_ts(timedelta(minutes=2)))
        _insert_snapshot(storage, _make_analysis(ds_channels=second), _utc_ts(timedelta(minutes=1)))

        result = storage.get_multi_channel_history([1, 2], "ds", days=7)

        assert [row["correctable_errors"] for row in result[1]] == [
            4_294_495_351,
            4_295_659_550,
        ]
        assert [row["correctable_errors"] for row in result[2]] == [20, 25]

    def test_string_channel_id_matches(self, storage):
        """Drivers like Vodafone Station store channelID as string.
        Ensure channel history still matches when channel_id is stored as str."""
        ds = [
            {"channel_id": "1", "frequency": "114.0 MHz", "power": 5.2,
             "modulation": "256QAM", "snr": 38.1, "correctable_errors": 10,
             "uncorrectable_errors": 2, "docsis_version": "3.0",
             "health": "good", "health_detail": ""},
        ]
        us = [
            {"channel_id": "1", "frequency": "37 MHz", "power": 42.0,
             "modulation": "64QAM", "multiplex": "ATDMA",
             "docsis_version": "3.0", "health": "good", "health_detail": ""},
        ]
        storage.save_snapshot(_make_analysis(ds_channels=ds, us_channels=us))
        result = storage.get_channel_history(1, "ds", days=7)
        assert len(result) == 1
        assert result[0]["power"] == 5.2

    def test_float_string_channel_id_matches(self, storage):
        """CGA driver stored channel_id as '1.0' via str(parse_number()).
        Ensure channel history handles float-string IDs from existing data."""
        ds = [
            {"channel_id": "1.0", "frequency": "114.0 MHz", "power": 5.2,
             "modulation": "256QAM", "snr": 38.1, "correctable_errors": 10,
             "uncorrectable_errors": 2, "docsis_version": "3.0",
             "health": "good", "health_detail": ""},
        ]
        storage.save_snapshot(_make_analysis(ds_channels=ds))
        result = storage.get_channel_history(1, "ds", days=7)
        assert len(result) == 1
        assert result[0]["power"] == 5.2

    def test_multi_channel_float_string_id(self, storage):
        """get_multi_channel_history must also handle '1.0' style IDs."""
        ds = [
            {"channel_id": "1.0", "frequency": "114.0 MHz", "power": 5.2,
             "modulation": "256QAM", "snr": 38.1, "correctable_errors": 10,
             "uncorrectable_errors": 2, "docsis_version": "3.0",
             "health": "good", "health_detail": ""},
        ]
        storage.save_snapshot(_make_analysis(ds_channels=ds))
        result = storage.get_multi_channel_history([1], "ds", days=7)
        assert len(result[1]) == 1
        assert result[1][0]["power"] == 5.2

    def test_ambiguous_legacy_id_returns_no_unrelated_first_match(self, storage):
        storage.save_snapshot(_duplicate_id_analysis())

        assert storage.get_channel_history(0, "ds", days=7) == []

    def test_selector_keeps_duplicate_ids_independent_and_normalizes_frequency(self, storage):
        older = _duplicate_id_analysis(634, "738.0 MHz")
        newer = _duplicate_id_analysis("634.0 MHz", 738)
        newer["ds_channels"][0]["power"] = 5.1
        newer["ds_channels"][1]["power"] = -2.0
        _insert_snapshot(storage, older, _utc_ts(timedelta(minutes=2)))
        _insert_snapshot(storage, newer, _utc_ts(timedelta(minutes=1)))
        current = storage.get_current_channels()["ds_channels"]
        first_selector = current[0]["selector"]
        second_selector = current[1]["selector"]

        first = storage.get_channel_history(
            0, "ds", days=7, selector=first_selector
        )
        second = storage.get_channel_history(
            0, "ds", days=7, selector=second_selector
        )

        assert [row["power"] for row in first] == [4.8, 5.1]
        assert [row["power"] for row in second] == [-1.7, -2.0]

    def test_selector_supports_duplicate_invalid_ids(self, storage):
        analysis = _duplicate_id_analysis()
        analysis["ds_channels"][0]["channel_id"] = None
        analysis["ds_channels"][1]["channel_id"] = None
        storage.save_snapshot(analysis)
        current = storage.get_current_channels()["ds_channels"]

        first = storage.get_channel_history(
            None, "ds", days=7, selector=current[0]["selector"]
        )
        second = storage.get_channel_history(
            None, "ds", days=7, selector=current[1]["selector"]
        )

        assert first[0]["power"] == 4.8
        assert second[0]["power"] == -1.7

    def test_explicit_unmatched_selector_returns_empty(self, storage):
        storage.save_snapshot(_duplicate_id_analysis())

        assert storage.get_channel_history(
            0, "ds", days=7, selector="not-a-channel"
        ) == []

    def test_ambiguous_selector_returns_empty(self, storage):
        storage.save_snapshot(_duplicate_id_analysis("634 MHz", 634.0))
        selector = storage.get_current_channels()["ds_channels"][0]["selector"]

        assert storage.get_channel_history(
            0, "ds", days=7, selector=selector
        ) == []

    def test_multi_selector_history_does_not_merge_duplicate_ids(self, storage):
        storage.save_snapshot(_duplicate_id_analysis())
        current = storage.get_current_channels()["ds_channels"]
        selectors = [channel["selector"] for channel in current]

        result = storage.get_multi_channel_history(
            [], "ds", days=7, selectors=selectors
        )

        assert result[selectors[0]][0]["power"] == 4.8
        assert result[selectors[1]][0]["power"] == -1.7

    def test_multi_selector_history_indexes_each_snapshot_channel_once(
        self, storage, monkeypatch
    ):
        analysis = _make_analysis(ds_channels=[
            {"channel_id": 0, "frequency": f"{600 + index} MHz", "power": index}
            for index in range(32)
        ])
        storage.save_snapshot(analysis)
        selectors = [
            channel["selector"]
            for channel in storage.get_current_channels()["ds_channels"]
        ]
        from app import channel_selector as selector_module

        original = selector_module.channel_selector
        calls = 0

        def counted_selector(channel):
            nonlocal calls
            calls += 1
            return original(channel)

        monkeypatch.setattr(selector_module, "channel_selector", counted_selector)

        result = storage.get_multi_channel_history(
            [], "ds", days=7, selectors=selectors
        )

        assert all(len(result[selector]) == 1 for selector in selectors)
        assert calls == 32


class TestGetCurrentChannels:
    def test_returns_channels(self, storage):
        storage.save_snapshot(_make_analysis())
        result = storage.get_current_channels()
        assert len(result["ds_channels"]) == 2
        assert len(result["us_channels"]) == 1
        assert result["ds_channels"][0]["channel_id"] == 1

    def test_empty_storage(self, storage):
        result = storage.get_current_channels()
        assert result == {"ds_channels": [], "us_channels": []}

    def test_exposes_stable_distinct_selectors_for_duplicate_ids(self, storage):
        storage.save_snapshot(_duplicate_id_analysis())

        result = storage.get_current_channels()["ds_channels"]

        assert result[0]["selector"] != result[1]["selector"]
        assert result[0]["selector_required"] is True
        assert result[1]["selector_required"] is True


# ── API Tests ──

class TestChannelsEndpoint:
    def test_returns_channels(self, client):
        c, s = client
        s.save_snapshot(_make_analysis())
        resp = c.get("/api/channels")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert len(data["ds_channels"]) == 2
        assert len(data["us_channels"]) == 1

    def test_empty(self, client):
        c, s = client
        resp = c.get("/api/channels")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["ds_channels"] == []
        assert data["us_channels"] == []


class TestChannelHistoryEndpoint:
    def test_returns_history(self, client):
        c, s = client
        s.save_snapshot(_make_analysis())
        resp = c.get("/api/channel-history?channel_id=1&direction=ds&days=7")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert len(data) == 1
        assert data[0]["power"] == 5.2

    def test_missing_channel_id(self, client):
        c, s = client
        resp = c.get("/api/channel-history?direction=ds&days=7")
        assert resp.status_code == 400

    def test_invalid_direction(self, client):
        c, s = client
        resp = c.get("/api/channel-history?channel_id=1&direction=invalid")
        assert resp.status_code == 400

    def test_upstream_channel(self, client):
        c, s = client
        s.save_snapshot(_make_analysis())
        resp = c.get("/api/channel-history?channel_id=1&direction=us&days=7")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert len(data) == 1
        assert data[0]["power"] == 42.0

    def test_no_storage(self, tmp_path):
        data_dir = str(tmp_path / "data2")
        mgr = ConfigManager(data_dir)
        mgr.save({"modem_password": "test", "modem_type": "fritzbox"})
        init_config(mgr)
        init_storage(None)
        app.config["TESTING"] = True
        with app.test_client() as c:
            resp = c.get("/api/channel-history?channel_id=1&direction=ds")
            assert resp.status_code == 200
            assert json.loads(resp.data) == []

    def test_days_clamped(self, client):
        c, s = client
        s.save_snapshot(_make_analysis())
        # days=0 should be clamped to 1
        resp = c.get("/api/channel-history?channel_id=1&direction=ds&days=0")
        assert resp.status_code == 200
        # days=200 should be clamped to 90
        resp2 = c.get("/api/channel-history?channel_id=1&direction=ds&days=200")
        assert resp2.status_code == 200

    def test_range_param_supports_one_hour_window(self, client):
        c, s = client
        analysis = _make_analysis()
        _insert_snapshot(s, analysis, _utc_ts(timedelta(hours=2)))
        _insert_snapshot(s, analysis, _utc_ts(timedelta(minutes=20)))

        resp = c.get("/api/channel-history?channel_id=1&direction=ds&range=1h")

        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert len(data) == 1

    def test_invalid_range_param_is_rejected(self, client):
        c, s = client
        s.save_snapshot(_make_analysis())

        resp = c.get("/api/channel-history?channel_id=1&direction=ds&range=4h")

        assert resp.status_code == 400

    def test_selector_returns_exact_duplicate_channel(self, client):
        c, s = client
        s.save_snapshot(_duplicate_id_analysis())
        selector = json.loads(c.get("/api/channels").data)["ds_channels"][1]["selector"]

        resp = c.get(
            "/api/channel-history",
            query_string={"selector": selector, "direction": "ds", "range": "1d"},
        )

        assert resp.status_code == 200
        assert json.loads(resp.data)[0]["power"] == -1.7

    def test_ambiguous_legacy_api_request_returns_empty(self, client):
        c, s = client
        s.save_snapshot(_duplicate_id_analysis())

        resp = c.get("/api/channel-history?channel_id=0&direction=ds&range=1d")

        assert resp.status_code == 200
        assert json.loads(resp.data) == []

    def test_explicit_unmatched_api_selector_returns_empty(self, client):
        c, s = client
        s.save_snapshot(_duplicate_id_analysis())

        resp = c.get(
            "/api/channel-history?selector=not-a-channel&direction=ds&range=1d"
        )

        assert resp.status_code == 200
        assert json.loads(resp.data) == []


class TestChannelCompareEndpoint:
    def test_returns_multiple_channels(self, client):
        c, s = client
        ds_channels = []
        for channel_id in range(1, 9):
            ds_channels.append({
                "channel_id": channel_id,
                "frequency": f"{114 + channel_id}.0 MHz",
                "power": 5.0 + channel_id,
                "modulation": "256QAM",
                "snr": 38.0,
                "correctable_errors": channel_id,
                "uncorrectable_errors": 0,
                "docsis_version": "3.0",
                "health": "good",
                "health_detail": "",
            })
        s.save_snapshot(_make_analysis(ds_channels=ds_channels))
        resp = c.get("/api/channel-compare?channels=1,2,3,4,5,6,7,8&direction=ds&days=7")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert set(data.keys()) == {"1", "2", "3", "4", "5", "6", "7", "8"}
        assert data["8"][0]["power"] == 13.0

    def test_range_param_supports_one_hour_window(self, client):
        c, s = client
        analysis = _make_analysis()
        _insert_snapshot(s, analysis, _utc_ts(timedelta(hours=2)))
        _insert_snapshot(s, analysis, _utc_ts(timedelta(minutes=20)))

        resp = c.get("/api/channel-compare?channels=1,2&direction=ds&range=1h")

        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert len(data["1"]) == 1
        assert len(data["2"]) == 1

    def test_rejects_more_than_64_channels(self, client):
        c, s = client
        s.save_snapshot(_make_analysis())
        ids = ",".join(str(i) for i in range(1, 66))
        resp = c.get(f"/api/channel-compare?channels={ids}&direction=ds&days=7")
        assert resp.status_code == 400
        data = json.loads(resp.data)
        assert data["error"] == "maximum 64 channels"

    def test_selectors_keep_duplicate_id_channels_separate(self, client):
        c, s = client
        s.save_snapshot(_duplicate_id_analysis())
        channels = json.loads(c.get("/api/channels").data)["ds_channels"]
        selectors = [channel["selector"] for channel in channels]

        resp = c.get(
            "/api/channel-compare",
            query_string={
                "selectors": ",".join(selectors),
                "direction": "ds",
                "range": "1d",
            },
        )

        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data[selectors[0]][0]["power"] == 4.8
        assert data[selectors[1]][0]["power"] == -1.7
