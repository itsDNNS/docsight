"""Tests for Connection Monitor API routes."""

import csv
import io
import time
from unittest.mock import MagicMock, patch
import pytest

from app.modules.connection_monitor.routes import bp
from app.modules.connection_monitor.storage import ConnectionMonitorStorage


@pytest.fixture
def app(tmp_path):
    from flask import Flask
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test"
    app.register_blueprint(bp)

    db_path = str(tmp_path / "test_cm.db")
    storage = ConnectionMonitorStorage(db_path)

    mock_probe = MagicMock()
    mock_probe.capability_info.return_value = {"method": "tcp", "reason": "no ICMP permission"}

    # Set the module-level lazy storage directly
    import app.modules.connection_monitor.routes as routes_mod
    routes_mod._storage = storage

    with patch("app.modules.connection_monitor.routes._get_probe_engine", return_value=mock_probe), \
         patch("app.modules.connection_monitor.routes._get_tz", return_value="UTC"):
        yield app, storage

    # Clean up
    routes_mod._storage = None


@pytest.fixture
def client(app):
    flask_app, storage = app
    return flask_app.test_client(), storage


def _auth_session(c):
    """Set authenticated session for protected routes."""
    with c.session_transaction() as sess:
        sess["authenticated"] = True


class TestTargetsAPI:
    def test_get_empty_targets(self, client):
        c, _ = client
        resp = c.get("/api/connection-monitor/targets")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_create_target(self, client):
        c, _ = client
        _auth_session(c)
        resp = c.post(
            "/api/connection-monitor/targets",
            json={"label": "Test", "host": "1.1.1.1"},
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["id"] == 1

    def test_create_target_without_host_is_disabled(self, client):
        c, storage = client
        _auth_session(c)
        resp = c.post(
            "/api/connection-monitor/targets",
            json={"label": "New target"},
        )
        assert resp.status_code == 201
        target = storage.get_target(resp.get_json()["id"])
        assert not target["enabled"]

    def test_create_target_with_host_is_enabled(self, client):
        c, storage = client
        _auth_session(c)
        resp = c.post(
            "/api/connection-monitor/targets",
            json={"label": "Test", "host": "1.1.1.1"},
        )
        assert resp.status_code == 201
        target = storage.get_target(resp.get_json()["id"])
        assert target["enabled"]

    def test_update_host_auto_enables_target(self, client):
        c, storage = client
        _auth_session(c)
        # Create disabled target (no host)
        resp = c.post(
            "/api/connection-monitor/targets",
            json={"label": "New target"},
        )
        tid = resp.get_json()["id"]
        assert not storage.get_target(tid)["enabled"]
        # Update with host - should auto-enable
        resp = c.put(
            f"/api/connection-monitor/targets/{tid}",
            json={"host": "8.8.8.8"},
        )
        assert resp.status_code == 200
        assert storage.get_target(tid)["enabled"]

    def test_update_target(self, client):
        c, storage = client
        storage.create_target("Test", "1.1.1.1")
        _auth_session(c)
        resp = c.put(
            "/api/connection-monitor/targets/1",
            json={"label": "Updated"},
        )
        assert resp.status_code == 200

    def test_delete_target(self, client):
        c, storage = client
        storage.create_target("Test", "1.1.1.1")
        _auth_session(c)
        resp = c.delete("/api/connection-monitor/targets/1")
        assert resp.status_code == 200


class TestSamplesAPI:
    def test_get_samples(self, client):
        c, storage = client
        tid = storage.create_target("Test", "1.1.1.1")
        storage.save_samples([
            {"target_id": tid, "timestamp": time.time(), "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"},
        ])
        resp = c.get(f"/api/connection-monitor/samples/{tid}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["samples"]) == 1

    def test_get_samples_with_time_range(self, client):
        c, storage = client
        tid = storage.create_target("Test", "1.1.1.1")
        now = time.time()
        storage.save_samples([
            {"target_id": tid, "timestamp": now - 200, "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"},
            {"target_id": tid, "timestamp": now - 50, "latency_ms": 20.0, "timeout": False, "probe_method": "tcp"},
        ])
        resp = c.get(f"/api/connection-monitor/samples/{tid}?start={now - 100}")
        data = resp.get_json()
        assert len(data["samples"]) == 1


class TestSamplesResolution:
    def test_raw_returns_envelope_format(self, client):
        """Samples endpoint should return {meta, samples} envelope."""
        c, storage = client
        tid = storage.create_target("Test", "1.1.1.1")
        now = time.time()
        storage.save_samples([
            {"target_id": tid, "timestamp": now, "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"},
        ])
        resp = c.get(f"/api/connection-monitor/samples/{tid}?start={now - 60}&end={now + 60}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "meta" in data
        assert "samples" in data
        assert data["meta"]["resolution"] == "raw"
        assert data["meta"]["bucket_seconds"] is None
        assert data["meta"]["blended"] is False
        assert data["meta"]["mixed"] is False
        assert data["meta"]["tiers_used"] == ["raw"]
        s = data["samples"][0]
        assert "latency_ms" in s
        assert "packet_loss_pct" in s
        assert "sample_count" in s
        assert s["sample_count"] == 1
        assert s["min_latency_ms"] is None
        assert s["max_latency_ms"] is None
        assert s["p95_latency_ms"] is None
        assert "timeout" not in s

    def test_raw_timeout_has_100_loss(self, client):
        """Raw timeout samples should have packet_loss_pct=100.0."""
        c, storage = client
        tid = storage.create_target("Test", "1.1.1.1")
        now = time.time()
        storage.save_samples([
            {"target_id": tid, "timestamp": now, "latency_ms": None, "timeout": True, "probe_method": "tcp"},
        ])
        resp = c.get(f"/api/connection-monitor/samples/{tid}?start={now - 60}&end={now + 60}")
        data = resp.get_json()
        s = data["samples"][0]
        assert s["packet_loss_pct"] == 100.0
        assert s["latency_ms"] is None

    def test_forced_resolution(self, client):
        """Explicit resolution param should force that tier."""
        c, storage = client
        tid = storage.create_target("Test", "1.1.1.1")
        now = time.time()
        with storage._connect() as conn:
            conn.execute(
                """INSERT INTO connection_samples_aggregated
                   (target_id, bucket_start, bucket_seconds,
                    avg_latency_ms, min_latency_ms, max_latency_ms,
                    p95_latency_ms, packet_loss_pct, sample_count)
                   VALUES (?, ?, 60, 15.0, 10.0, 20.0, 18.0, 0.0, 12)""",
                (tid, now - 500),
            )
        resp = c.get(f"/api/connection-monitor/samples/{tid}?resolution=1min&start={now - 600}&end={now}")
        data = resp.get_json()
        assert data["meta"]["resolution"] == "1min"
        assert data["meta"]["bucket_seconds"] == 60
        assert len(data["samples"]) == 1
        s = data["samples"][0]
        assert s["min_latency_ms"] == 10.0
        assert s["max_latency_ms"] == 20.0
        assert s["sample_count"] == 12

    def test_auto_7d_range_is_blended(self, client):
        """A 7d range with auto resolution should blend raw + aggregated data."""
        c, storage = client
        tid = storage.create_target("Test", "1.1.1.1")
        now = time.time()
        storage.save_samples([
            {"target_id": tid, "timestamp": now - 3600, "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"},
        ])
        with storage._connect() as conn:
            conn.execute(
                """INSERT INTO connection_samples_aggregated
                   (target_id, bucket_start, bucket_seconds,
                    avg_latency_ms, min_latency_ms, max_latency_ms,
                    p95_latency_ms, packet_loss_pct, sample_count)
                   VALUES (?, ?, 60, 15.0, 10.0, 20.0, 18.0, 0.0, 12)""",
                (tid, now - 8 * 86400),
            )
        start = now - 9 * 86400
        end = now
        resp = c.get(f"/api/connection-monitor/samples/{tid}?start={start}&end={end}")
        data = resp.get_json()
        assert data["meta"]["blended"] is True
        assert data["meta"]["mixed"] is True
        assert data["meta"]["tiers_used"] == ["raw", "1min"]
        assert len(data["samples"]) == 2
        assert data["samples"][0]["timestamp"] < data["samples"][1]["timestamp"]
        assert data["samples"][0]["min_latency_ms"] is not None
        assert data["samples"][1]["min_latency_ms"] is None

    def test_auto_90d_range_keeps_recent_raw_data(self, client):
        """A 90d range should still show current raw data even before older buckets exist."""
        c, storage = client
        tid = storage.create_target("Test", "1.1.1.1")
        now = time.time()
        storage.save_samples([
            {"target_id": tid, "timestamp": now - 3600, "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"},
        ])
        resp = c.get(f"/api/connection-monitor/samples/{tid}?start={now - 90 * 86400}&end={now}")
        data = resp.get_json()
        assert data["meta"]["resolution"] == "5min"
        assert data["meta"]["blended"] is True
        assert data["meta"]["mixed"] is False
        assert data["meta"]["tiers_used"] == ["raw"]
        assert len(data["samples"]) == 1
        assert data["samples"][0]["latency_ms"] == 10.0
        assert data["samples"][0]["min_latency_ms"] is None

    def test_auto_90d_range_blends_raw_60s_and_300s(self, client):
        """A 90d range should combine recent raw data with 60s and 300s buckets."""
        c, storage = client
        tid = storage.create_target("Test", "1.1.1.1")
        now = time.time()
        storage.save_samples([
            {"target_id": tid, "timestamp": now - 3600, "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"},
        ])
        with storage._connect() as conn:
            conn.execute(
                """INSERT INTO connection_samples_aggregated
                   (target_id, bucket_start, bucket_seconds,
                    avg_latency_ms, min_latency_ms, max_latency_ms,
                    p95_latency_ms, packet_loss_pct, sample_count)
                   VALUES (?, ?, 60, 15.0, 10.0, 20.0, 18.0, 0.0, 12)""",
                (tid, now - 14 * 86400),
            )
            conn.execute(
                """INSERT INTO connection_samples_aggregated
                   (target_id, bucket_start, bucket_seconds,
                    avg_latency_ms, min_latency_ms, max_latency_ms,
                    p95_latency_ms, packet_loss_pct, sample_count)
                   VALUES (?, ?, 300, 25.0, 20.0, 30.0, 28.0, 1.0, 60)""",
                (tid, now - 45 * 86400),
            )
        resp = c.get(f"/api/connection-monitor/samples/{tid}?start={now - 90 * 86400}&end={now}")
        data = resp.get_json()
        assert data["meta"]["resolution"] == "5min"
        assert data["meta"]["blended"] is True
        assert data["meta"]["mixed"] is True
        assert data["meta"]["tiers_used"] == ["raw", "1min", "5min"]
        assert len(data["samples"]) == 3
        assert data["samples"][0]["timestamp"] < data["samples"][1]["timestamp"] < data["samples"][2]["timestamp"]
        assert data["samples"][0]["min_latency_ms"] is not None
        assert data["samples"][1]["min_latency_ms"] is not None
        assert data["samples"][2]["min_latency_ms"] is None

    def test_auto_without_explicit_range_stays_raw_only(self, client):
        """Without start/end, auto resolution should keep the legacy raw-only behavior."""
        c, storage = client
        tid = storage.create_target("Test", "1.1.1.1")
        now = time.time()
        storage.save_samples([
            {"target_id": tid, "timestamp": now - 60, "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"},
        ])
        with storage._connect() as conn:
            conn.execute(
                """INSERT INTO connection_samples_aggregated
                   (target_id, bucket_start, bucket_seconds,
                    avg_latency_ms, min_latency_ms, max_latency_ms,
                    p95_latency_ms, packet_loss_pct, sample_count)
                   VALUES (?, ?, 60, 15.0, 10.0, 20.0, 18.0, 0.0, 12)""",
                (tid, now - 14 * 86400),
            )
        resp = c.get(f"/api/connection-monitor/samples/{tid}")
        data = resp.get_json()
        assert data["meta"]["resolution"] == "raw"
        assert data["meta"]["blended"] is False
        assert data["meta"]["mixed"] is False
        assert data["meta"]["tiers_used"] == ["raw"]
        assert len(data["samples"]) == 1
        assert data["samples"][0]["latency_ms"] == 10.0
        assert data["samples"][0]["min_latency_ms"] is None

    def test_auto_range_uses_exclusive_tier_boundaries(self, client):
        """Tier boundaries should keep near-cutoff samples in exactly one tier."""
        c, storage = client
        tid = storage.create_target("Test", "1.1.1.1")
        now = time.time()
        raw_ts = now - 7 * 86400 + 5
        agg60_near_raw_ts = now - 7 * 86400 - 5
        agg60_near_300_ts = now - 30 * 86400 + 5
        agg300_ts = now - 30 * 86400 - 5
        storage.save_samples([
            {"target_id": tid, "timestamp": raw_ts, "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"},
        ])
        with storage._connect() as conn:
            conn.execute(
                """INSERT INTO connection_samples_aggregated
                   (target_id, bucket_start, bucket_seconds,
                    avg_latency_ms, min_latency_ms, max_latency_ms,
                    p95_latency_ms, packet_loss_pct, sample_count)
                   VALUES (?, ?, 60, 15.0, 10.0, 20.0, 18.0, 0.0, 12)""",
                (tid, agg60_near_raw_ts),
            )
            conn.execute(
                """INSERT INTO connection_samples_aggregated
                   (target_id, bucket_start, bucket_seconds,
                    avg_latency_ms, min_latency_ms, max_latency_ms,
                    p95_latency_ms, packet_loss_pct, sample_count)
                   VALUES (?, ?, 60, 17.0, 12.0, 22.0, 19.0, 0.0, 12)""",
                (tid, agg60_near_300_ts),
            )
            conn.execute(
                """INSERT INTO connection_samples_aggregated
                   (target_id, bucket_start, bucket_seconds,
                    avg_latency_ms, min_latency_ms, max_latency_ms,
                    p95_latency_ms, packet_loss_pct, sample_count)
                   VALUES (?, ?, 300, 25.0, 20.0, 30.0, 28.0, 1.0, 60)""",
                (tid, agg300_ts),
            )
        resp = c.get(f"/api/connection-monitor/samples/{tid}?start={now - 90 * 86400}&end={now}")
        data = resp.get_json()
        timestamps = [sample["timestamp"] for sample in data["samples"]]
        assert len(data["samples"]) == 4
        assert timestamps.count(raw_ts) == 1
        assert timestamps.count(agg60_near_raw_ts) == 1
        assert timestamps.count(agg60_near_300_ts) == 1
        assert timestamps.count(agg300_ts) == 1

    def test_get_samples_with_max_points(self, client):
        c, storage = client
        tid = storage.create_target("Test", "1.1.1.1")
        now = time.time()
        storage.save_samples([
            {
                "target_id": tid,
                "timestamp": now - (120 - i),
                "latency_ms": float(10 + (i % 5)),
                "timeout": i % 17 == 0,
                "probe_method": "tcp",
            }
            for i in range(120)
        ])
        resp = c.get(
            f"/api/connection-monitor/samples/{tid}?start={now - 120}&end={now}&limit=0&max_points=10"
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["samples"]) <= 10
        assert "sample_count" in data["samples"][0]
        assert "packet_loss_pct" in data["samples"][0]
        assert sum(sample["sample_count"] for sample in data["samples"]) == 120


class TestPinnedDaysAPI:
    def test_list_pinned_days_empty(self, client):
        c, _ = client
        resp = c.get("/api/connection-monitor/pinned-days")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_pin_day(self, client):
        c, _ = client
        _auth_session(c)
        resp = c.post(
            "/api/connection-monitor/pinned-days",
            json={"date": "2026-03-10"},
        )
        assert resp.status_code == 201
        days = c.get("/api/connection-monitor/pinned-days").get_json()
        assert len(days) == 1
        assert days[0]["date"] == "2026-03-10"
        assert "utc_start" in days[0]
        assert "utc_end" in days[0]

    def test_pin_day_via_timestamp(self, client):
        """POST with timestamp instead of date derives date server-side."""
        c, _ = client
        _auth_session(c)
        from datetime import datetime, timezone
        # 2026-03-10 12:00:00 UTC
        ts = datetime(2026, 3, 10, 12, 0, 0, tzinfo=timezone.utc).timestamp()
        resp = c.post(
            "/api/connection-monitor/pinned-days",
            json={"timestamp": ts},
        )
        assert resp.status_code == 201
        days = c.get("/api/connection-monitor/pinned-days").get_json()
        assert len(days) == 1
        assert days[0]["date"] == "2026-03-10"

    def test_pin_day_with_label(self, client):
        c, _ = client
        _auth_session(c)
        resp = c.post(
            "/api/connection-monitor/pinned-days",
            json={"date": "2026-03-10", "label": "Outage"},
        )
        assert resp.status_code == 201
        days = c.get("/api/connection-monitor/pinned-days").get_json()
        assert days[0]["label"] == "Outage"

    def test_pin_day_invalid_date(self, client):
        c, _ = client
        _auth_session(c)
        resp = c.post(
            "/api/connection-monitor/pinned-days",
            json={"date": "not-a-date"},
        )
        assert resp.status_code == 400

    def test_pin_day_future_date(self, client):
        c, _ = client
        _auth_session(c)
        resp = c.post(
            "/api/connection-monitor/pinned-days",
            json={"date": "2099-01-01"},
        )
        assert resp.status_code == 400

    def test_pin_day_missing_date_and_timestamp(self, client):
        c, _ = client
        _auth_session(c)
        resp = c.post(
            "/api/connection-monitor/pinned-days",
            json={},
        )
        assert resp.status_code == 400

    def test_unpin_day(self, client):
        c, _ = client
        _auth_session(c)
        c.post("/api/connection-monitor/pinned-days", json={"date": "2026-03-10"})
        resp = c.delete("/api/connection-monitor/pinned-days/2026-03-10")
        assert resp.status_code == 200
        days = c.get("/api/connection-monitor/pinned-days").get_json()
        assert len(days) == 0

    def test_unpin_nonexistent(self, client):
        c, _ = client
        _auth_session(c)
        resp = c.delete("/api/connection-monitor/pinned-days/2026-01-01")
        assert resp.status_code == 404

    def test_pinned_day_older_than_7d_returns_raw(self, client):
        """Pinned day raw data should be served when resolution=raw, even beyond the 7d window."""
        c, storage = client
        _auth_session(c)
        tid = storage.create_target("Test", "1.1.1.1")
        now = time.time()
        old_ts = now - 10 * 86400  # 10 days ago
        from datetime import datetime
        old_date = datetime.fromtimestamp(old_ts).strftime("%Y-%m-%d")
        storage.pin_day(old_date)
        storage.save_samples([
            {"target_id": tid, "timestamp": old_ts, "latency_ms": 42.0, "timeout": False, "probe_method": "tcp"},
            {"target_id": tid, "timestamp": old_ts + 5, "latency_ms": 43.0, "timeout": False, "probe_method": "tcp"},
        ])
        # Simulate what the JS does for pinned days: resolution=raw
        resp = c.get(
            f"/api/connection-monitor/samples/{tid}"
            f"?start={old_ts - 3600}&end={old_ts + 86400}&limit=0&resolution=raw"
        )
        data = resp.get_json()
        assert data["meta"]["resolution"] == "raw"
        assert len(data["samples"]) == 2
        assert data["samples"][0]["latency_ms"] == 42.0
        assert data["samples"][0]["sample_count"] == 1

    def test_pinned_day_older_than_7d_export_returns_raw(self, client):
        """CSV export of a pinned day should return raw samples."""
        c, storage = client
        _auth_session(c)
        tid = storage.create_target("Test", "1.1.1.1")
        now = time.time()
        old_ts = now - 10 * 86400
        from datetime import datetime
        old_date = datetime.fromtimestamp(old_ts).strftime("%Y-%m-%d")
        storage.pin_day(old_date)
        storage.save_samples([
            {"target_id": tid, "timestamp": old_ts, "latency_ms": 42.0, "timeout": False, "probe_method": "tcp"},
        ])
        resp = c.get(f"/api/connection-monitor/export/{tid}?start={old_ts - 3600}&end={old_ts + 86400}&resolution=raw")
        assert resp.status_code == 200
        import csv, io
        rows = list(csv.reader(io.StringIO(resp.data.decode())))
        assert len(rows) == 2  # header + 1 data row
        assert "latency_ms" in rows[0]


class TestSummaryAPI:
    def test_get_summary(self, client):
        c, storage = client
        tid = storage.create_target("Test", "1.1.1.1")
        now = time.time()
        storage.save_samples([
            {"target_id": tid, "timestamp": now - 5, "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"},
        ])
        resp = c.get("/api/connection-monitor/summary")
        assert resp.status_code == 200

    def test_get_range_stats(self, client):
        c, storage = client
        tid = storage.create_target("Test", "1.1.1.1")
        now = time.time()
        storage.save_samples([
            {"target_id": tid, "timestamp": now - 40, "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"},
            {"target_id": tid, "timestamp": now - 30, "latency_ms": 20.0, "timeout": False, "probe_method": "tcp"},
            {"target_id": tid, "timestamp": now - 20, "latency_ms": 30.0, "timeout": False, "probe_method": "tcp"},
            {"target_id": tid, "timestamp": now - 10, "latency_ms": None, "timeout": True, "probe_method": "tcp"},
        ])
        resp = c.get(f"/api/connection-monitor/stats?start={now - 60}&end={now}")
        assert resp.status_code == 200
        data = resp.get_json()
        stats = data[str(tid)]
        assert stats["sample_count"] == 4
        assert stats["latency_count"] == 3
        assert stats["p95_latency_ms"] == 30.0


class TestOutagesAPI:
    def test_get_outages(self, client):
        c, storage = client
        tid = storage.create_target("Test", "1.1.1.1")
        now = time.time()
        samples = [{"target_id": tid, "timestamp": now - 10, "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"}]
        for i in range(6):
            samples.append({"target_id": tid, "timestamp": now - 9 + i, "latency_ms": None, "timeout": True, "probe_method": "tcp"})
        samples.append({"target_id": tid, "timestamp": now, "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"})
        storage.save_samples(samples)
        resp = c.get(f"/api/connection-monitor/outages/{tid}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) >= 1


class TestExportAPI:
    def test_csv_export(self, client):
        c, storage = client
        tid = storage.create_target("Test", "1.1.1.1")
        now = time.time()
        storage.save_samples([
            {"target_id": tid, "timestamp": now, "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"},
        ])
        resp = c.get(f"/api/connection-monitor/export/{tid}")
        assert resp.status_code == 200
        assert "text/csv" in resp.content_type
        content = resp.data.decode()
        reader = csv.reader(io.StringIO(content))
        rows = list(reader)
        assert len(rows) == 2  # header + 1 data row

    def test_csv_export_aggregated(self, client):
        c, storage = client
        tid = storage.create_target("Test", "1.1.1.1")
        now = time.time()
        with storage._connect() as conn:
            conn.execute(
                """INSERT INTO connection_samples_aggregated
                   (target_id, bucket_start, bucket_seconds,
                    avg_latency_ms, min_latency_ms, max_latency_ms,
                    p95_latency_ms, packet_loss_pct, sample_count)
                   VALUES (?, ?, 60, 15.0, 10.0, 20.0, 18.0, 5.0, 12)""",
                (tid, now - 500),
            )
        resp = c.get(f"/api/connection-monitor/export/{tid}?resolution=1min")
        assert resp.status_code == 200
        assert "text/csv" in resp.content_type
        content = resp.data.decode()
        reader = csv.reader(io.StringIO(content))
        rows = list(reader)
        assert len(rows) == 2  # header + 1 data row
        assert "avg_latency_ms" in rows[0]
        assert "packet_loss_pct" in rows[0]


class TestCapabilityAPI:
    def test_capability(self, client):
        c, _ = client
        resp = c.get("/api/connection-monitor/capability")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["method"] == "tcp"


class TestAuthProtection:
    """Verify all endpoints return 401 when auth is enabled but not provided."""

    @pytest.fixture
    def auth_client(self, app):
        """Client with auth enforcement enabled via a mock config manager."""
        flask_app, storage = app
        mock_cfg = MagicMock()
        mock_cfg.get.side_effect = lambda key, default=None: {
            "admin_password": "hashed_pw",
        }.get(key, default)
        with patch("app.web._config_manager", mock_cfg):
            yield flask_app.test_client(), storage

    def test_targets_get_requires_auth(self, auth_client):
        c, _ = auth_client
        assert c.get("/api/connection-monitor/targets").status_code == 401

    def test_targets_post_requires_auth(self, auth_client):
        c, _ = auth_client
        resp = c.post("/api/connection-monitor/targets", json={"label": "X", "host": "1.1.1.1"})
        assert resp.status_code == 401

    def test_samples_requires_auth(self, auth_client):
        c, _ = auth_client
        assert c.get("/api/connection-monitor/samples/1").status_code == 401

    def test_summary_requires_auth(self, auth_client):
        c, _ = auth_client
        assert c.get("/api/connection-monitor/summary").status_code == 401

    def test_outages_requires_auth(self, auth_client):
        c, _ = auth_client
        assert c.get("/api/connection-monitor/outages/1").status_code == 401

    def test_export_requires_auth(self, auth_client):
        c, _ = auth_client
        assert c.get("/api/connection-monitor/export/1").status_code == 401

    def test_capability_requires_auth(self, auth_client):
        c, _ = auth_client
        assert c.get("/api/connection-monitor/capability").status_code == 401

    def test_pinned_days_get_requires_auth(self, auth_client):
        c, _ = auth_client
        assert c.get("/api/connection-monitor/pinned-days").status_code == 401

    def test_pinned_days_post_requires_auth(self, auth_client):
        c, _ = auth_client
        resp = c.post("/api/connection-monitor/pinned-days", json={"date": "2026-03-10"})
        assert resp.status_code == 401

    def test_pinned_days_delete_requires_auth(self, auth_client):
        c, _ = auth_client
        assert c.delete("/api/connection-monitor/pinned-days/2026-03-10").status_code == 401

    def test_authenticated_request_passes(self, auth_client):
        c, _ = auth_client
        _auth_session(c)
        assert c.get("/api/connection-monitor/targets").status_code == 200
