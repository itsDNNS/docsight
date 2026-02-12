"""Tests for event detection, storage, and API endpoints."""

import json
import pytest
from datetime import datetime, timedelta

from app.storage import SnapshotStorage
from app.event_detector import EventDetector
from app.web import app, init_config, init_storage
from app.config import ConfigManager


# ── Fixtures ──

@pytest.fixture
def storage(tmp_path):
    db_path = str(tmp_path / "test.db")
    return SnapshotStorage(db_path, max_days=7)


@pytest.fixture
def detector():
    return EventDetector()


def _make_analysis(health="good", ds_power_avg=2.5, us_power_avg=42.0,
                   ds_snr_min=35.0, ds_total=33, us_total=4,
                   ds_uncorrectable_errors=100, ds_channels=None, us_channels=None):
    if ds_channels is None:
        ds_channels = [{"channel_id": i, "power": 3.0, "modulation": "256QAM",
                        "snr": 35.0, "correctable_errors": 10,
                        "uncorrectable_errors": 5, "docsis_version": "3.0",
                        "health": "good", "health_detail": "", "frequency": "602 MHz"}
                       for i in range(1, ds_total + 1)]
    if us_channels is None:
        us_channels = [{"channel_id": i, "power": 42.0, "modulation": "64QAM",
                        "multiplex": "ATDMA", "docsis_version": "3.0",
                        "health": "good", "health_detail": "", "frequency": "37 MHz"}
                       for i in range(1, us_total + 1)]
    return {
        "summary": {
            "health": health,
            "health_issues": [],
            "ds_power_avg": ds_power_avg,
            "ds_power_min": ds_power_avg - 1,
            "ds_power_max": ds_power_avg + 1,
            "us_power_avg": us_power_avg,
            "us_power_min": us_power_avg - 1,
            "us_power_max": us_power_avg + 1,
            "ds_snr_min": ds_snr_min,
            "ds_snr_avg": ds_snr_min + 2,
            "ds_total": ds_total,
            "us_total": us_total,
            "ds_correctable_errors": 1000,
            "ds_uncorrectable_errors": ds_uncorrectable_errors,
        },
        "ds_channels": ds_channels,
        "us_channels": us_channels,
    }


# ── Storage Tests ──

class TestEventStorage:
    def test_save_and_get_events(self, storage):
        ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        eid = storage.save_event(ts, "warning", "power_change", "Power shifted", {"delta": 3.5})
        assert eid is not None
        events = storage.get_events()
        assert len(events) == 1
        assert events[0]["severity"] == "warning"
        assert events[0]["event_type"] == "power_change"
        assert events[0]["details"]["delta"] == 3.5
        assert events[0]["acknowledged"] == 0

    def test_save_events_bulk(self, storage):
        ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        events_list = [
            {"timestamp": ts, "severity": "info", "event_type": "channel_change",
             "message": "DS channels changed", "details": None},
            {"timestamp": ts, "severity": "critical", "event_type": "health_change",
             "message": "Health degraded", "details": {"prev": "good", "current": "poor"}},
        ]
        count = storage.save_events(events_list)
        assert count == 2
        assert len(storage.get_events()) == 2

    def test_get_events_with_filters(self, storage):
        ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        storage.save_event(ts, "info", "channel_change", "Msg 1")
        storage.save_event(ts, "warning", "power_change", "Msg 2")
        storage.save_event(ts, "critical", "health_change", "Msg 3")

        assert len(storage.get_events(severity="warning")) == 1
        assert len(storage.get_events(event_type="health_change")) == 1
        assert len(storage.get_events(severity="info")) == 1

    def test_event_count(self, storage):
        ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        storage.save_event(ts, "info", "channel_change", "Msg")
        storage.save_event(ts, "warning", "power_change", "Msg")
        assert storage.get_event_count() == 2
        assert storage.get_event_count(acknowledged=0) == 2
        assert storage.get_event_count(acknowledged=1) == 0

    def test_acknowledge_event(self, storage):
        ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        eid = storage.save_event(ts, "warning", "power_change", "Msg")
        assert storage.acknowledge_event(eid)
        events = storage.get_events()
        assert events[0]["acknowledged"] == 1
        assert storage.get_event_count(acknowledged=0) == 0
        assert storage.get_event_count(acknowledged=1) == 1

    def test_acknowledge_nonexistent(self, storage):
        assert not storage.acknowledge_event(9999)

    def test_acknowledge_all(self, storage):
        ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        storage.save_event(ts, "info", "channel_change", "Msg 1")
        storage.save_event(ts, "warning", "power_change", "Msg 2")
        count = storage.acknowledge_all_events()
        assert count == 2
        assert storage.get_event_count(acknowledged=0) == 0

    def test_event_cleanup(self, tmp_path):
        db_path = str(tmp_path / "cleanup.db")
        s = SnapshotStorage(db_path, max_days=1)
        old_ts = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S")
        new_ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        s.save_event(old_ts, "info", "channel_change", "Old event")
        s.save_event(new_ts, "info", "channel_change", "New event")
        deleted = s.delete_old_events(1)
        assert deleted == 1
        assert len(s.get_events()) == 1

    def test_events_newest_first(self, storage):
        ts1 = "2026-01-01T00:00:00"
        ts2 = "2026-01-02T00:00:00"
        storage.save_event(ts1, "info", "channel_change", "Older")
        storage.save_event(ts2, "info", "channel_change", "Newer")
        events = storage.get_events()
        assert events[0]["timestamp"] == ts2
        assert events[1]["timestamp"] == ts1

    def test_save_events_empty_list(self, storage):
        assert storage.save_events([]) == 0


# ── EventDetector Tests ──

class TestEventDetector:
    def test_first_poll_monitoring_started(self, detector):
        analysis = _make_analysis()
        events = detector.check(analysis)
        assert len(events) == 1
        assert events[0]["event_type"] == "monitoring_started"
        assert events[0]["severity"] == "info"
        assert "Health:" in events[0]["message"]

    def test_no_change_no_events(self, detector):
        analysis = _make_analysis()
        detector.check(analysis)
        events = detector.check(analysis)
        assert events == []

    def test_health_change_detected(self, detector):
        detector.check(_make_analysis(health="good"))
        events = detector.check(_make_analysis(health="poor"))
        assert len(events) == 1
        assert events[0]["event_type"] == "health_change"
        assert events[0]["severity"] == "critical"
        assert "good" in events[0]["message"]
        assert "poor" in events[0]["message"]

    def test_health_recovery_detected(self, detector):
        detector.check(_make_analysis(health="poor"))
        events = detector.check(_make_analysis(health="good"))
        assert len(events) == 1
        assert events[0]["event_type"] == "health_change"
        assert events[0]["severity"] == "info"

    def test_health_marginal_warning(self, detector):
        detector.check(_make_analysis(health="good"))
        events = detector.check(_make_analysis(health="marginal"))
        assert len(events) == 1
        assert events[0]["severity"] == "warning"

    def test_power_change_detected(self, detector):
        detector.check(_make_analysis(ds_power_avg=2.5))
        events = detector.check(_make_analysis(ds_power_avg=5.0))
        power_events = [e for e in events if e["event_type"] == "power_change"]
        assert len(power_events) == 1
        assert power_events[0]["severity"] == "warning"
        assert "DS" in power_events[0]["message"]

    def test_us_power_change_detected(self, detector):
        detector.check(_make_analysis(us_power_avg=42.0))
        events = detector.check(_make_analysis(us_power_avg=45.5))
        power_events = [e for e in events if e["event_type"] == "power_change"]
        assert len(power_events) == 1
        assert "US" in power_events[0]["message"]

    def test_power_no_event_small_shift(self, detector):
        detector.check(_make_analysis(ds_power_avg=2.5))
        events = detector.check(_make_analysis(ds_power_avg=3.0))
        power_events = [e for e in events if e["event_type"] == "power_change"]
        assert len(power_events) == 0

    def test_snr_drop_warning(self, detector):
        detector.check(_make_analysis(ds_snr_min=32.0))
        events = detector.check(_make_analysis(ds_snr_min=28.0))
        snr_events = [e for e in events if e["event_type"] == "snr_change"]
        assert len(snr_events) == 1
        assert snr_events[0]["severity"] == "warning"

    def test_snr_drop_critical(self, detector):
        detector.check(_make_analysis(ds_snr_min=28.0))
        events = detector.check(_make_analysis(ds_snr_min=23.0))
        snr_events = [e for e in events if e["event_type"] == "snr_change"]
        assert len(snr_events) == 1
        assert snr_events[0]["severity"] == "critical"

    def test_channel_count_change(self, detector):
        detector.check(_make_analysis(ds_total=33, us_total=4))
        events = detector.check(_make_analysis(ds_total=30, us_total=4))
        ch_events = [e for e in events if e["event_type"] == "channel_change"]
        assert len(ch_events) == 1
        assert "DS" in ch_events[0]["message"]

    def test_us_channel_count_change(self, detector):
        detector.check(_make_analysis(ds_total=33, us_total=4))
        events = detector.check(_make_analysis(ds_total=33, us_total=3))
        ch_events = [e for e in events if e["event_type"] == "channel_change"]
        assert len(ch_events) == 1
        assert "US" in ch_events[0]["message"]

    def test_modulation_change(self, detector):
        ds1 = [{"channel_id": 1, "modulation": "256QAM", "power": 3.0, "snr": 35.0,
                "correctable_errors": 10, "uncorrectable_errors": 5,
                "docsis_version": "3.0", "health": "good", "health_detail": "", "frequency": "602 MHz"}]
        ds2 = [{"channel_id": 1, "modulation": "64QAM", "power": 3.0, "snr": 35.0,
                "correctable_errors": 10, "uncorrectable_errors": 5,
                "docsis_version": "3.0", "health": "good", "health_detail": "", "frequency": "602 MHz"}]
        detector.check(_make_analysis(ds_total=1, ds_channels=ds1))
        events = detector.check(_make_analysis(ds_total=1, ds_channels=ds2))
        mod_events = [e for e in events if e["event_type"] == "modulation_change"]
        assert len(mod_events) == 1
        assert mod_events[0]["severity"] == "info"

    def test_error_spike(self, detector):
        detector.check(_make_analysis(ds_uncorrectable_errors=100))
        events = detector.check(_make_analysis(ds_uncorrectable_errors=2000))
        err_events = [e for e in events if e["event_type"] == "error_spike"]
        assert len(err_events) == 1
        assert err_events[0]["severity"] == "warning"

    def test_error_no_spike_small_increase(self, detector):
        detector.check(_make_analysis(ds_uncorrectable_errors=100))
        events = detector.check(_make_analysis(ds_uncorrectable_errors=500))
        err_events = [e for e in events if e["event_type"] == "error_spike"]
        assert len(err_events) == 0


# ── API Tests ──

@pytest.fixture
def api_storage(tmp_path):
    db_path = str(tmp_path / "api_test.db")
    return SnapshotStorage(db_path, max_days=7)


@pytest.fixture
def client(tmp_path, api_storage):
    data_dir = str(tmp_path / "data")
    mgr = ConfigManager(data_dir)
    mgr.save({"modem_password": "test"})
    init_config(mgr)
    init_storage(api_storage)
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


class TestEventsAPI:
    def test_get_events_empty(self, client):
        resp = client.get("/api/events")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["events"] == []
        assert data["unacknowledged_count"] == 0

    def test_get_events_with_data(self, client, api_storage):
        ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        api_storage.save_event(ts, "warning", "power_change", "Power shifted")
        resp = client.get("/api/events")
        data = json.loads(resp.data)
        assert len(data["events"]) == 1
        assert data["unacknowledged_count"] == 1

    def test_get_events_with_filters(self, client, api_storage):
        ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        api_storage.save_event(ts, "info", "channel_change", "Msg 1")
        api_storage.save_event(ts, "warning", "power_change", "Msg 2")
        resp = client.get("/api/events?severity=warning")
        data = json.loads(resp.data)
        assert len(data["events"]) == 1
        assert data["events"][0]["severity"] == "warning"

    def test_acknowledge_event(self, client, api_storage):
        ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        eid = api_storage.save_event(ts, "warning", "power_change", "Msg")
        resp = client.post(f"/api/events/{eid}/acknowledge")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["success"] is True

    def test_acknowledge_nonexistent(self, client):
        resp = client.post("/api/events/9999/acknowledge")
        assert resp.status_code == 404

    def test_acknowledge_all(self, client, api_storage):
        ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        api_storage.save_event(ts, "info", "channel_change", "Msg 1")
        api_storage.save_event(ts, "warning", "power_change", "Msg 2")
        resp = client.post("/api/events/acknowledge-all")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["success"] is True
        assert data["count"] == 2

    def test_events_count(self, client, api_storage):
        ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        api_storage.save_event(ts, "warning", "power_change", "Msg")
        resp = client.get("/api/events/count")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["count"] == 1

    def test_events_count_empty(self, client):
        resp = client.get("/api/events/count")
        data = json.loads(resp.data)
        assert data["count"] == 0
