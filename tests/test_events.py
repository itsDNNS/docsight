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
        assert storage.get_event_count(acknowledged=0) == 2
        assert storage.get_event_count(acknowledged=1) == 0

    def test_event_count_with_severity(self, storage):
        ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        storage.save_event(ts, "info", "channel_change", "Msg")
        storage.save_event(ts, "warning", "power_change", "Msg")
        assert storage.get_event_count(severity="warning") == 1
        assert storage.get_event_count(severity="info") == 1
        assert storage.get_event_count(severity="critical") == 0

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

    def test_get_latest_spike_timestamp_empty(self, storage):
        """No spike events — returns None."""
        assert storage.get_latest_spike_timestamp() is None

    def test_get_latest_spike_timestamp(self, storage):
        """Returns timestamp of most recent error_spike event."""
        storage.save_event("2026-02-26T10:00:00Z", "warning", "power_change", "Power shifted")
        storage.save_event("2026-02-27T14:00:00Z", "warning", "error_spike", "Uncorr spike")
        storage.save_event("2026-02-27T16:00:00Z", "warning", "error_spike", "Uncorr spike 2")
        result = storage.get_latest_spike_timestamp()
        assert result == "2026-02-27T16:00:00Z"

    def test_get_latest_spike_ignores_other_types(self, storage):
        """Only considers error_spike events."""
        storage.save_event("2026-02-28T12:00:00Z", "warning", "power_change", "Power shifted")
        assert storage.get_latest_spike_timestamp() is None


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
        events = detector.check(_make_analysis(health="critical"))
        assert len(events) == 1
        assert events[0]["event_type"] == "health_change"
        assert events[0]["severity"] == "critical"
        assert "good" in events[0]["message"]
        assert "critical" in events[0]["message"]

    def test_health_recovery_detected(self, detector):
        detector.check(_make_analysis(health="critical"))
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
        detector.check(_make_analysis(ds_snr_min=35.0))
        events = detector.check(_make_analysis(ds_snr_min=31.0))
        snr_events = [e for e in events if e["event_type"] == "snr_change"]
        assert len(snr_events) == 1
        assert snr_events[0]["severity"] == "warning"

    def test_snr_drop_critical(self, detector):
        detector.check(_make_analysis(ds_snr_min=31.0))
        events = detector.check(_make_analysis(ds_snr_min=27.0))
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

    def test_modulation_downgrade_warning(self, detector):
        """256QAM → 64QAM = 2-level drop = warning"""
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
        assert mod_events[0]["severity"] == "warning"
        assert "dropped" in mod_events[0]["message"]
        assert mod_events[0]["details"]["direction"] == "downgrade"

    def test_modulation_downgrade_critical(self, detector):
        """256QAM → 16QAM = 4-level drop = critical"""
        ds1 = [{"channel_id": 1, "modulation": "256QAM", "power": 3.0, "snr": 35.0,
                "correctable_errors": 10, "uncorrectable_errors": 5,
                "docsis_version": "3.0", "health": "good", "health_detail": "", "frequency": "602 MHz"}]
        ds2 = [{"channel_id": 1, "modulation": "16QAM", "power": 3.0, "snr": 35.0,
                "correctable_errors": 10, "uncorrectable_errors": 5,
                "docsis_version": "3.0", "health": "good", "health_detail": "", "frequency": "602 MHz"}]
        detector.check(_make_analysis(ds_total=1, ds_channels=ds1))
        events = detector.check(_make_analysis(ds_total=1, ds_channels=ds2))
        mod_events = [e for e in events if e["event_type"] == "modulation_change"]
        assert len(mod_events) == 1
        assert mod_events[0]["severity"] == "critical"
        assert "dropped" in mod_events[0]["message"]

    def test_modulation_upgrade_info(self, detector):
        """64QAM → 256QAM = upgrade = info"""
        ds1 = [{"channel_id": 1, "modulation": "64QAM", "power": 3.0, "snr": 35.0,
                "correctable_errors": 10, "uncorrectable_errors": 5,
                "docsis_version": "3.0", "health": "good", "health_detail": "", "frequency": "602 MHz"}]
        ds2 = [{"channel_id": 1, "modulation": "256QAM", "power": 3.0, "snr": 35.0,
                "correctable_errors": 10, "uncorrectable_errors": 5,
                "docsis_version": "3.0", "health": "good", "health_detail": "", "frequency": "602 MHz"}]
        detector.check(_make_analysis(ds_total=1, ds_channels=ds1))
        events = detector.check(_make_analysis(ds_total=1, ds_channels=ds2))
        mod_events = [e for e in events if e["event_type"] == "modulation_change"]
        assert len(mod_events) == 1
        assert mod_events[0]["severity"] == "info"
        assert "improved" in mod_events[0]["message"]
        assert mod_events[0]["details"]["direction"] == "upgrade"

    def test_modulation_downgrade_qam_underscore_format(self, detector):
        """qam_64 → qam_16 = downgrade (Vodafone Station / CH7465 / TC4400 format) - Issue #85"""
        us1 = [{"channel_id": 1, "modulation": "qam_64", "power": 42.0,
                "multiplex": "ATDMA", "docsis_version": "3.0",
                "health": "good", "health_detail": "", "frequency": "37 MHz"}]
        us2 = [{"channel_id": 1, "modulation": "qam_16", "power": 42.0,
                "multiplex": "ATDMA", "docsis_version": "3.0",
                "health": "good", "health_detail": "", "frequency": "37 MHz"}]
        detector.check(_make_analysis(us_total=1, us_channels=us1))
        events = detector.check(_make_analysis(us_total=1, us_channels=us2))
        mod_events = [e for e in events if e["event_type"] == "modulation_change"]
        assert len(mod_events) == 1
        assert mod_events[0]["severity"] == "warning"
        assert "dropped" in mod_events[0]["message"]
        assert mod_events[0]["details"]["direction"] == "downgrade"
        assert mod_events[0]["details"]["changes"][0]["rank_drop"] == 2

    def test_modulation_upgrade_qam_underscore_format(self, detector):
        """qam_64 → qam_256 = upgrade (Vodafone Station format)"""
        ds1 = [{"channel_id": 1, "modulation": "qam_64", "power": 3.0, "snr": 35.0,
                "correctable_errors": 10, "uncorrectable_errors": 5,
                "docsis_version": "3.0", "health": "good", "health_detail": "", "frequency": "602 MHz"}]
        ds2 = [{"channel_id": 1, "modulation": "qam_256", "power": 3.0, "snr": 35.0,
                "correctable_errors": 10, "uncorrectable_errors": 5,
                "docsis_version": "3.0", "health": "good", "health_detail": "", "frequency": "602 MHz"}]
        detector.check(_make_analysis(ds_total=1, ds_channels=ds1))
        events = detector.check(_make_analysis(ds_total=1, ds_channels=ds2))
        mod_events = [e for e in events if e["event_type"] == "modulation_change"]
        assert len(mod_events) == 1
        assert mod_events[0]["severity"] == "info"
        assert "improved" in mod_events[0]["message"]
        assert mod_events[0]["details"]["direction"] == "upgrade"

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


class TestHealthHysteresis:
    """Tests for opt-in health hysteresis (flapping prevention)."""

    def test_hysteresis_disabled_by_default(self):
        """hysteresis=0 behaves like original: immediate state changes."""
        d = EventDetector(hysteresis=0)
        d.check(_make_analysis(health="good"))
        events = d.check(_make_analysis(health="marginal"))
        health_events = [e for e in events if e["event_type"] == "health_change"]
        assert len(health_events) == 1

    def test_hysteresis_suppresses_single_poll(self):
        """With hysteresis=3, a single poll below threshold does not emit."""
        d = EventDetector(hysteresis=3)
        d.check(_make_analysis(health="good"))
        events = d.check(_make_analysis(health="marginal"))
        health_events = [e for e in events if e["event_type"] == "health_change"]
        assert len(health_events) == 0

    def test_hysteresis_confirms_after_n_polls(self):
        """After N consecutive polls with same health, event is emitted."""
        d = EventDetector(hysteresis=3)
        d.check(_make_analysis(health="good"))
        # Polls 1, 2: no event
        d.check(_make_analysis(health="marginal"))
        d.check(_make_analysis(health="marginal"))
        # Poll 3: confirmed
        events = d.check(_make_analysis(health="marginal"))
        health_events = [e for e in events if e["event_type"] == "health_change"]
        assert len(health_events) == 1
        assert health_events[0]["details"]["prev"] == "good"
        assert health_events[0]["details"]["current"] == "marginal"

    def test_hysteresis_resets_on_bounce_back(self):
        """If health bounces back to confirmed, counter resets."""
        d = EventDetector(hysteresis=3)
        d.check(_make_analysis(health="good"))
        d.check(_make_analysis(health="marginal"))
        d.check(_make_analysis(health="marginal"))
        # Bounce back to good — resets counter
        d.check(_make_analysis(health="good"))
        # Start over: 1 poll at marginal is not enough
        events = d.check(_make_analysis(health="marginal"))
        health_events = [e for e in events if e["event_type"] == "health_change"]
        assert len(health_events) == 0

    def test_hysteresis_resets_on_different_pending(self):
        """If pending health changes direction, counter restarts."""
        d = EventDetector(hysteresis=3)
        d.check(_make_analysis(health="good"))
        d.check(_make_analysis(health="marginal"))
        d.check(_make_analysis(health="marginal"))
        # Different pending health: critical instead of marginal
        d.check(_make_analysis(health="critical"))
        d.check(_make_analysis(health="critical"))
        # Only 2 polls at critical, not 3 yet
        events = d.check(_make_analysis(health="critical"))
        health_events = [e for e in events if e["event_type"] == "health_change"]
        assert len(health_events) == 1
        assert health_events[0]["details"]["current"] == "critical"

    def test_hysteresis_recovery(self):
        """Recovery also requires N consecutive polls."""
        d = EventDetector(hysteresis=2)
        d.check(_make_analysis(health="marginal"))
        # Confirm degradation stays (already at marginal from baseline)
        # Now try recovery
        d.check(_make_analysis(health="good"))
        events = d.check(_make_analysis(health="good"))
        health_events = [e for e in events if e["event_type"] == "health_change"]
        assert len(health_events) == 1
        assert health_events[0]["severity"] == "info"
        assert health_events[0]["details"]["current"] == "good"

    def test_hysteresis_one_is_immediate(self):
        """hysteresis=1 is effectively disabled (1 poll = instant)."""
        d = EventDetector(hysteresis=1)
        d.check(_make_analysis(health="good"))
        events = d.check(_make_analysis(health="marginal"))
        health_events = [e for e in events if e["event_type"] == "health_change"]
        assert len(health_events) == 1


# ── API Tests ──

@pytest.fixture
def api_storage(tmp_path):
    db_path = str(tmp_path / "api_test.db")
    return SnapshotStorage(db_path, max_days=7)


@pytest.fixture
def client(tmp_path, api_storage):
    data_dir = str(tmp_path / "data")
    mgr = ConfigManager(data_dir)
    mgr.save({"modem_password": "test", "modem_type": "fritzbox"})
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

    def test_get_events_with_prefix(self, client, api_storage):
        ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        api_storage.save_event(ts, "info", "device_reboot", "Device rebooted")
        api_storage.save_event(ts, "info", "power_change", "Power change")
        
        # Test filtering by prefix
        resp = client.get("/api/events?event_prefix=device_")
        data = json.loads(resp.data)
        assert len(data["events"]) == 1
        assert data["events"][0]["event_type"] == "device_reboot"
        assert data["unacknowledged_count"] == 1

    def test_events_count_with_prefix(self, client, api_storage):
        ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        api_storage.save_event(ts, "info", "device_reboot", "Device rebooted")
        api_storage.save_event(ts, "info", "power_change", "Power change")
        
        # Test count filtering by prefix
        resp = client.get("/api/events/count?event_prefix=device_")
        data = json.loads(resp.data)
        assert data["count"] == 1


# ── save_events_with_ids ──

class TestSaveEventsWithIds:
    def test_returns_list_of_ids(self, storage):
        events = [
            {"timestamp": "2026-03-15T10:00:00Z", "severity": "warning",
             "event_type": "modulation_change", "message": "drop"},
            {"timestamp": "2026-03-15T10:00:00Z", "severity": "info",
             "event_type": "health_change", "message": "degraded"},
        ]
        ids = storage.save_events_with_ids(events)
        assert len(ids) == 2
        assert all(isinstance(i, int) for i in ids)
        assert ids[0] != ids[1]

    def test_events_retrievable_by_id(self, storage):
        events = [
            {"timestamp": "2026-03-15T10:00:00Z", "severity": "warning",
             "event_type": "modulation_change", "message": "drop",
             "details": {"direction": "downgrade"}},
        ]
        ids = storage.save_events_with_ids(events)
        rows = storage.get_events()
        assert rows[0]["id"] == ids[0]
        assert rows[0]["event_type"] == "modulation_change"

    def test_empty_list_returns_empty(self, storage):
        assert storage.save_events_with_ids([]) == []

    def test_annotates_events_with_id(self, storage):
        events = [
            {"timestamp": "2026-03-15T10:00:00Z", "severity": "warning",
             "event_type": "modulation_change", "message": "drop"},
        ]
        ids = storage.save_events_with_ids(events)
        assert events[0]["_id"] == ids[0]


# ── Restart Detection Tests ──

class TestRestartDetection:
    def _make_restart_pair(self, prev_corr=100, prev_uncorr=5,
                           cur_corr=0, cur_uncorr=0, n_channels=16):
        prev_channels = [
            {"channel_id": i, "power": 3.0, "modulation": "256QAM",
             "snr": 35.0, "correctable_errors": prev_corr,
             "uncorrectable_errors": prev_uncorr, "docsis_version": "3.0",
             "health": "good", "health_detail": "", "frequency": "602 MHz"}
            for i in range(1, n_channels + 1)
        ]
        cur_channels = [
            {"channel_id": i, "power": 3.0, "modulation": "256QAM",
             "snr": 35.0, "correctable_errors": cur_corr,
             "uncorrectable_errors": cur_uncorr, "docsis_version": "3.0",
             "health": "good", "health_detail": "", "frequency": "602 MHz"}
            for i in range(1, n_channels + 1)
        ]
        prev = _make_analysis(ds_channels=prev_channels, ds_total=n_channels,
                              ds_uncorrectable_errors=prev_uncorr * n_channels)
        prev["summary"]["ds_correctable_errors"] = prev_corr * n_channels
        cur = _make_analysis(ds_channels=cur_channels, ds_total=n_channels,
                             ds_uncorrectable_errors=cur_uncorr * n_channels)
        cur["summary"]["ds_correctable_errors"] = cur_corr * n_channels
        return prev, cur

    def test_restart_detected(self, detector):
        """All 16 channels reset from (500,20) to (0,0) — restart detected."""
        prev, cur = self._make_restart_pair(prev_corr=500, prev_uncorr=20,
                                            cur_corr=0, cur_uncorr=0, n_channels=16)
        detector.check(prev)
        events = detector.check(cur)
        restart_events = [e for e in events if e["event_type"] == "modem_restart_detected"]
        assert len(restart_events) == 1
        assert restart_events[0]["details"]["affected_channels"] == 16

    def test_restart_partial_channels(self, detector):
        """14/16 channels decline, 2 unchanged — still detected."""
        prev_channels = [
            {"channel_id": i, "power": 3.0, "modulation": "256QAM",
             "snr": 35.0, "correctable_errors": 100,
             "uncorrectable_errors": 5, "docsis_version": "3.0",
             "health": "good", "health_detail": "", "frequency": "602 MHz"}
            for i in range(1, 17)
        ]
        cur_channels = [
            {"channel_id": i, "power": 3.0, "modulation": "256QAM",
             "snr": 35.0,
             "correctable_errors": 0 if i <= 14 else 100,
             "uncorrectable_errors": 0 if i <= 14 else 5,
             "docsis_version": "3.0",
             "health": "good", "health_detail": "", "frequency": "602 MHz"}
            for i in range(1, 17)
        ]
        prev = _make_analysis(ds_channels=prev_channels, ds_total=16,
                              ds_uncorrectable_errors=5 * 16)
        prev["summary"]["ds_correctable_errors"] = 100 * 16
        cur = _make_analysis(ds_channels=cur_channels, ds_total=16,
                             ds_uncorrectable_errors=0 * 14 + 5 * 2)
        cur["summary"]["ds_correctable_errors"] = 0 * 14 + 100 * 2
        detector.check(prev)
        events = detector.check(cur)
        restart_events = [e for e in events if e["event_type"] == "modem_restart_detected"]
        assert len(restart_events) == 1
        assert restart_events[0]["details"]["affected_channels"] == 14

    def test_no_restart_below_threshold(self, detector):
        """7/10 channels decline (70%) — below 80% threshold, not detected."""
        prev_channels = [
            {"channel_id": i, "power": 3.0, "modulation": "256QAM",
             "snr": 35.0, "correctable_errors": 100,
             "uncorrectable_errors": 5, "docsis_version": "3.0",
             "health": "good", "health_detail": "", "frequency": "602 MHz"}
            for i in range(1, 11)
        ]
        cur_channels = [
            {"channel_id": i, "power": 3.0, "modulation": "256QAM",
             "snr": 35.0,
             "correctable_errors": 0 if i <= 7 else 100,
             "uncorrectable_errors": 0 if i <= 7 else 5,
             "docsis_version": "3.0",
             "health": "good", "health_detail": "", "frequency": "602 MHz"}
            for i in range(1, 11)
        ]
        prev = _make_analysis(ds_channels=prev_channels, ds_total=10,
                              ds_uncorrectable_errors=5 * 10)
        prev["summary"]["ds_correctable_errors"] = 100 * 10
        cur = _make_analysis(ds_channels=cur_channels, ds_total=10,
                             ds_uncorrectable_errors=0 * 7 + 5 * 3)
        cur["summary"]["ds_correctable_errors"] = 0 * 7 + 100 * 3
        detector.check(prev)
        events = detector.check(cur)
        restart_events = [e for e in events if e["event_type"] == "modem_restart_detected"]
        assert len(restart_events) == 0

    def test_no_restart_first_poll(self, detector):
        """First poll (no prev) — no restart event, only monitoring_started."""
        _, cur = self._make_restart_pair()
        events = detector.check(cur)
        restart_events = [e for e in events if e["event_type"] == "modem_restart_detected"]
        assert len(restart_events) == 0

    def test_no_restart_counters_increasing(self, detector):
        """Counters go up — normal operation, no restart."""
        prev, cur = self._make_restart_pair(prev_corr=100, prev_uncorr=5,
                                            cur_corr=200, cur_uncorr=10)
        detector.check(prev)
        events = detector.check(cur)
        restart_events = [e for e in events if e["event_type"] == "modem_restart_detected"]
        assert len(restart_events) == 0

    def test_no_restart_insufficient_overlap(self, detector):
        """Current has completely different channel IDs — no overlap."""
        prev_channels = [
            {"channel_id": i, "power": 3.0, "modulation": "256QAM",
             "snr": 35.0, "correctable_errors": 100,
             "uncorrectable_errors": 5, "docsis_version": "3.0",
             "health": "good", "health_detail": "", "frequency": "602 MHz"}
            for i in range(1, 17)
        ]
        cur_channels = [
            {"channel_id": i, "power": 3.0, "modulation": "256QAM",
             "snr": 35.0, "correctable_errors": 0,
             "uncorrectable_errors": 0, "docsis_version": "3.0",
             "health": "good", "health_detail": "", "frequency": "602 MHz"}
            for i in range(101, 117)
        ]
        prev = _make_analysis(ds_channels=prev_channels, ds_total=16,
                              ds_uncorrectable_errors=80)
        prev["summary"]["ds_correctable_errors"] = 1600
        cur = _make_analysis(ds_channels=cur_channels, ds_total=16,
                             ds_uncorrectable_errors=0)
        cur["summary"]["ds_correctable_errors"] = 0
        detector.check(prev)
        events = detector.check(cur)
        restart_events = [e for e in events if e["event_type"] == "modem_restart_detected"]
        assert len(restart_events) == 0

    def test_no_restart_too_few_channels(self, detector):
        """Only 3 channels — below RESTART_MIN_OVERLAP (4)."""
        prev, cur = self._make_restart_pair(prev_corr=100, prev_uncorr=5,
                                            cur_corr=0, cur_uncorr=0, n_channels=3)
        detector.check(prev)
        events = detector.check(cur)
        restart_events = [e for e in events if e["event_type"] == "modem_restart_detected"]
        assert len(restart_events) == 0

    def test_no_restart_totals_not_declining(self, detector):
        """Per-channel declining but summary totals overridden high — no event."""
        prev, cur = self._make_restart_pair(prev_corr=100, prev_uncorr=5,
                                            cur_corr=0, cur_uncorr=0)
        # Override totals so they don't decline
        cur["summary"]["ds_correctable_errors"] = 99999
        cur["summary"]["ds_uncorrectable_errors"] = 99999
        detector.check(prev)
        events = detector.check(cur)
        restart_events = [e for e in events if e["event_type"] == "modem_restart_detected"]
        assert len(restart_events) == 0

    def test_no_restart_none_counters(self, detector):
        """Prev channels have None correctable_errors — skipped, no event."""
        prev_channels = [
            {"channel_id": i, "power": 3.0, "modulation": "256QAM",
             "snr": 35.0, "correctable_errors": None,
             "uncorrectable_errors": None, "docsis_version": "3.0",
             "health": "good", "health_detail": "", "frequency": "602 MHz"}
            for i in range(1, 17)
        ]
        cur_channels = [
            {"channel_id": i, "power": 3.0, "modulation": "256QAM",
             "snr": 35.0, "correctable_errors": 0,
             "uncorrectable_errors": 0, "docsis_version": "3.0",
             "health": "good", "health_detail": "", "frequency": "602 MHz"}
            for i in range(1, 17)
        ]
        prev = _make_analysis(ds_channels=prev_channels, ds_total=16,
                              ds_uncorrectable_errors=80)
        prev["summary"]["ds_correctable_errors"] = 1600
        cur = _make_analysis(ds_channels=cur_channels, ds_total=16,
                             ds_uncorrectable_errors=0)
        cur["summary"]["ds_correctable_errors"] = 0
        detector.check(prev)
        events = detector.check(cur)
        restart_events = [e for e in events if e["event_type"] == "modem_restart_detected"]
        assert len(restart_events) == 0

    def test_restart_with_some_channel_change(self, detector):
        """12/16 overlap and declining — detected despite channel churn."""
        prev_channels = [
            {"channel_id": i, "power": 3.0, "modulation": "256QAM",
             "snr": 35.0, "correctable_errors": 100,
             "uncorrectable_errors": 5, "docsis_version": "3.0",
             "health": "good", "health_detail": "", "frequency": "602 MHz"}
            for i in range(1, 17)
        ]
        # Channels 1-12 overlap (declining), channels 101-104 are new
        cur_channels = [
            {"channel_id": i, "power": 3.0, "modulation": "256QAM",
             "snr": 35.0, "correctable_errors": 0,
             "uncorrectable_errors": 0, "docsis_version": "3.0",
             "health": "good", "health_detail": "", "frequency": "602 MHz"}
            for i in range(1, 13)
        ] + [
            {"channel_id": i, "power": 3.0, "modulation": "256QAM",
             "snr": 35.0, "correctable_errors": 0,
             "uncorrectable_errors": 0, "docsis_version": "3.0",
             "health": "good", "health_detail": "", "frequency": "602 MHz"}
            for i in range(101, 105)
        ]
        prev = _make_analysis(ds_channels=prev_channels, ds_total=16,
                              ds_uncorrectable_errors=80)
        prev["summary"]["ds_correctable_errors"] = 1600
        cur = _make_analysis(ds_channels=cur_channels, ds_total=16,
                             ds_uncorrectable_errors=0)
        cur["summary"]["ds_correctable_errors"] = 0
        detector.check(prev)
        events = detector.check(cur)
        restart_events = [e for e in events if e["event_type"] == "modem_restart_detected"]
        assert len(restart_events) == 1

    def test_channels_already_zero(self, detector):
        """(0,0) to (0,0) — nothing actually declined, no event."""
        prev, cur = self._make_restart_pair(prev_corr=0, prev_uncorr=0,
                                            cur_corr=0, cur_uncorr=0)
        detector.check(prev)
        events = detector.check(cur)
        restart_events = [e for e in events if e["event_type"] == "modem_restart_detected"]
        assert len(restart_events) == 0

    def test_restart_does_not_trigger_error_spike(self, detector):
        """Restart pattern must NOT also emit an error_spike event."""
        prev, cur = self._make_restart_pair(prev_corr=500, prev_uncorr=20,
                                            cur_corr=0, cur_uncorr=0)
        detector.check(prev)
        events = detector.check(cur)
        restart_events = [e for e in events if e["event_type"] == "modem_restart_detected"]
        spike_events = [e for e in events if e["event_type"] == "error_spike"]
        assert len(restart_events) == 1
        assert len(spike_events) == 0

    def test_channel_with_zero_uncorr_before_restart(self, detector):
        """(500,0) to (0,0) — corr declined, uncorr same — detected."""
        prev, cur = self._make_restart_pair(prev_corr=500, prev_uncorr=0,
                                            cur_corr=0, cur_uncorr=0)
        detector.check(prev)
        events = detector.check(cur)
        restart_events = [e for e in events if e["event_type"] == "modem_restart_detected"]
        assert len(restart_events) == 1

    def test_partial_none_counters_still_detected(self, detector):
        """(corr=None, uncorr=5) → (None, 0) — uncorr declined, corr N/A — detected."""
        prev, cur = self._make_restart_pair(n_channels=16)
        # Set correctable to None on all channels, keep uncorrectable
        for ch in prev["ds_channels"]:
            ch["correctable_errors"] = None
            ch["uncorrectable_errors"] = 50
        for ch in cur["ds_channels"]:
            ch["correctable_errors"] = None
            ch["uncorrectable_errors"] = 0
        prev["summary"]["ds_correctable_errors"] = None
        prev["summary"]["ds_uncorrectable_errors"] = 50 * 16
        cur["summary"]["ds_correctable_errors"] = None
        cur["summary"]["ds_uncorrectable_errors"] = 0
        detector.check(prev)
        events = detector.check(cur)
        restart_events = [e for e in events if e["event_type"] == "modem_restart_detected"]
        assert len(restart_events) == 1

    def test_no_false_positive_missing_summary_keys(self, detector):
        """Missing cur summary keys: sanity check skipped, per-channel signal sufficient."""
        prev, cur = self._make_restart_pair()
        # Remove summary error keys entirely from cur
        del cur["summary"]["ds_correctable_errors"]
        del cur["summary"]["ds_uncorrectable_errors"]
        detector.check(prev)
        events = detector.check(cur)
        restart_events = [e for e in events if e["event_type"] == "modem_restart_detected"]
        # Per-channel signal is strong (all channels declined), sanity check
        # skipped because cur summary keys are missing — detection still works.
        assert len(restart_events) == 1

    def test_no_false_positive_prev_missing_summary(self, detector):
        """If prev has no summary error keys, sanity check skipped, no false positive from 0-default."""
        prev, cur = self._make_restart_pair(prev_corr=100, prev_uncorr=5,
                                             cur_corr=200, cur_uncorr=10)
        cur["summary"]["ds_correctable_errors"] = 200 * 16
        cur["summary"]["ds_uncorrectable_errors"] = 10 * 16
        # Remove summary error keys from prev — old default(0) would falsely trigger
        del prev["summary"]["ds_correctable_errors"]
        del prev["summary"]["ds_uncorrectable_errors"]
        detector.check(prev)
        events = detector.check(cur)
        restart_events = [e for e in events if e["event_type"] == "modem_restart_detected"]
        # Counters are increasing per-channel → no restart regardless of summary
        assert len(restart_events) == 0
