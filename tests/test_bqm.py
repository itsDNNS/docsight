"""Tests for ThinkBroadband BQM graph fetching, storage, and API."""

import sqlite3
import pytest
from unittest.mock import patch, MagicMock

from app.modules.bqm.thinkbroadband import fetch_graph
from app.modules.bqm.storage import BqmStorage
from app.storage import SnapshotStorage
from app.web import app, init_config, init_storage
from app.config import ConfigManager


# ── Fetcher Tests ──


class TestBQMFetcher:
    @patch("app.modules.bqm.thinkbroadband.urllib.request.urlopen")
    def test_fetch_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"\x89PNG" + b"\x00" * 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = fetch_graph("https://example.com/graph.png")
        assert result is not None
        assert len(result) > 100

    @patch("app.modules.bqm.thinkbroadband.urllib.request.urlopen")
    def test_fetch_empty_response(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b""
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = fetch_graph("https://example.com/graph.png")
        assert result is None

    @patch("app.modules.bqm.thinkbroadband.urllib.request.urlopen")
    def test_fetch_too_small(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"tiny"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = fetch_graph("https://example.com/graph.png")
        assert result is None

    @patch("app.modules.bqm.thinkbroadband.urllib.request.urlopen")
    def test_fetch_network_error(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("Connection refused")
        result = fetch_graph("https://example.com/graph.png")
        assert result is None

    @pytest.mark.parametrize("url", ["", None])
    def test_fetch_invalid_url(self, url):
        result = fetch_graph(url)
        assert result is None


# ── Storage Tests ──


@pytest.fixture
def bqm_storage(tmp_path):
    db_path = str(tmp_path / "test.db")
    return BqmStorage(db_path)


@pytest.fixture
def sample_png():
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 200


@pytest.fixture
def sample_csv_rows():
    return [
        {
            "timestamp": "2026-03-15T19:00:00+00:00",
            "date": "2026-03-15",
            "sent_polls": 100,
            "lost_polls": 0,
            "latency_min_ms": 30.43,
            "latency_avg_ms": 33.85,
            "latency_max_ms": 52.69,
            "score": 1,
        },
        {
            "timestamp": "2026-03-15T19:01:40+00:00",
            "date": "2026-03-15",
            "sent_polls": 100,
            "lost_polls": 2,
            "latency_min_ms": 30.62,
            "latency_avg_ms": 34.38,
            "latency_max_ms": 54.41,
            "score": 201,
        },
        {
            "timestamp": "2026-03-16T19:00:00+00:00",
            "date": "2026-03-16",
            "sent_polls": 100,
            "lost_polls": 1,
            "latency_min_ms": 28.12,
            "latency_avg_ms": 31.56,
            "latency_max_ms": 49.87,
            "score": 201,
        },
    ]


class TestBQMStorage:
    def test_save_and_get(self, bqm_storage, sample_png):
        bqm_storage.save_bqm_graph(sample_png)
        dates = bqm_storage.get_bqm_dates()
        assert len(dates) == 1
        image = bqm_storage.get_bqm_graph(dates[0])
        assert image == sample_png

    def test_duplicate_same_day(self, bqm_storage, sample_png):
        bqm_storage.save_bqm_graph(sample_png)
        bqm_storage.save_bqm_graph(sample_png)
        dates = bqm_storage.get_bqm_dates()
        assert len(dates) == 1

    def test_get_nonexistent_date(self, bqm_storage):
        assert bqm_storage.get_bqm_graph("2099-01-01") is None

    def test_empty_dates(self, bqm_storage):
        assert bqm_storage.get_bqm_dates() == []

    def test_dates_order(self, bqm_storage, sample_png):
        """Dates should be newest first."""
        import sqlite3
        # Insert manually with different dates
        with sqlite3.connect(bqm_storage.db_path) as conn:
            conn.execute(
                "INSERT INTO bqm_graphs (date, timestamp, image_blob) VALUES (?, ?, ?)",
                ("2025-01-01", "2025-01-01T12:00:00", sample_png),
            )
            conn.execute(
                "INSERT INTO bqm_graphs (date, timestamp, image_blob) VALUES (?, ?, ?)",
                ("2025-01-03", "2025-01-03T12:00:00", sample_png),
            )
            conn.execute(
                "INSERT INTO bqm_graphs (date, timestamp, image_blob) VALUES (?, ?, ?)",
                ("2025-01-02", "2025-01-02T12:00:00", sample_png),
            )
        dates = bqm_storage.get_bqm_dates()
        assert dates == ["2025-01-03", "2025-01-02", "2025-01-01"]

    def test_cleanup_removes_old_bqm(self, tmp_path, sample_png):
        """Cleanup should remove BQM graphs older than max_days."""
        import sqlite3
        db_path = str(tmp_path / "cleanup.db")
        # SnapshotStorage still handles cleanup for backward compat
        s = SnapshotStorage(db_path, max_days=1)
        # BqmStorage creates the table
        bs = BqmStorage(db_path)
        # Insert a graph dated far in the past
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO bqm_graphs (date, timestamp, image_blob) VALUES (?, ?, ?)",
                ("2020-01-01", "2020-01-01T12:00:00", sample_png),
            )
        assert len(bs.get_bqm_dates()) == 1
        s._cleanup()
        assert len(bs.get_bqm_dates()) == 0

    def test_unlimited_retention(self, tmp_path, sample_png):
        """max_days=0 should keep all BQM graphs."""
        import sqlite3
        db_path = str(tmp_path / "unlimited.db")
        s = SnapshotStorage(db_path, max_days=0)
        bs = BqmStorage(db_path)
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO bqm_graphs (date, timestamp, image_blob) VALUES (?, ?, ?)",
                ("2020-01-01", "2020-01-01T12:00:00", sample_png),
            )
        s._cleanup()
        assert len(bs.get_bqm_dates()) == 1

    def test_store_and_get_csv_data(self, bqm_storage, sample_csv_rows):
        bqm_storage.store_csv_data(sample_csv_rows)
        rows = bqm_storage.get_data_for_date("2026-03-15")
        assert len(rows) == 2
        assert rows[0]["latency_avg_ms"] == 33.85
        assert rows[1]["lost_polls"] == 2

    def test_csv_data_duplicate_timestamps_ignored(self, bqm_storage, sample_csv_rows):
        bqm_storage.store_csv_data(sample_csv_rows[:2])
        bqm_storage.store_csv_data(sample_csv_rows[:2])
        rows = bqm_storage.get_data_for_date("2026-03-15")
        assert len(rows) == 2

    def test_get_data_for_range_and_dates(self, bqm_storage, sample_csv_rows):
        bqm_storage.store_csv_data(sample_csv_rows)
        rows = bqm_storage.get_data_for_range("2026-03-15", "2026-03-16")
        assert len(rows) == 3
        assert bqm_storage.get_csv_dates() == ["2026-03-16", "2026-03-15"]
        assert bqm_storage.has_csv_data("2026-03-16") is True
        assert bqm_storage.has_csv_data("2026-03-14") is False

    def test_store_csv_data_reraises_storage_errors(self, bqm_storage, sample_csv_rows, monkeypatch):
        def boom(*args, **kwargs):
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr("app.modules.bqm.storage.sqlite3.connect", boom)

        with pytest.raises(sqlite3.OperationalError, match="database is locked"):
            bqm_storage.store_csv_data(sample_csv_rows)


# ── API Tests ──


def _reset_bqm_module_storage():
    """Reset the BQM module's lazy-initialized storage between tests."""
    import app.modules.bqm.routes as bqm_routes
    bqm_routes._storage = None


@pytest.fixture
def bqm_api_storage(tmp_path, sample_png, sample_csv_rows):
    """Storage pre-loaded with a BQM graph for today."""
    import sqlite3
    from datetime import datetime
    db_path = str(tmp_path / "bqm_api.db")
    s = SnapshotStorage(db_path, max_days=7)
    bs = BqmStorage(db_path)
    today = datetime.now().strftime("%Y-%m-%d")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO bqm_graphs (date, timestamp, image_blob) VALUES (?, ?, ?)",
            (today, datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), sample_png),
        )
    bs.store_csv_data(sample_csv_rows)
    return s, today


@pytest.fixture
def bqm_client(tmp_path, bqm_api_storage):
    s, today = bqm_api_storage
    data_dir = str(tmp_path / "data")
    mgr = ConfigManager(data_dir)
    mgr.save({"modem_password": "test", "modem_type": "fritzbox", "bqm_url": "https://example.com/graph.png"})
    init_config(mgr)
    init_storage(s)
    _reset_bqm_module_storage()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client, today
    _reset_bqm_module_storage()


class TestBQMAPI:
    def test_bqm_dates(self, bqm_client):
        client, today = bqm_client
        resp = client.get("/api/bqm/dates")
        assert resp.status_code == 200
        data = resp.get_json()
        assert today in data

    def test_bqm_image(self, bqm_client, sample_png):
        client, today = bqm_client
        resp = client.get(f"/api/bqm/image/{today}")
        assert resp.status_code == 200
        assert resp.content_type == "image/png"
        assert resp.data == sample_png

    def test_bqm_image_not_found(self, bqm_client):
        client, _ = bqm_client
        resp = client.get("/api/bqm/image/2099-01-01")
        assert resp.status_code == 404

    def test_bqm_image_invalid_date(self, bqm_client):
        client, _ = bqm_client
        resp = client.get("/api/bqm/image/invalid")
        assert resp.status_code == 400

    def test_bqm_dates_empty(self, tmp_path):
        data_dir = str(tmp_path / "data3")
        mgr = ConfigManager(data_dir)
        mgr.save({"modem_password": "test", "modem_type": "fritzbox"})
        init_config(mgr)
        init_storage(None)
        _reset_bqm_module_storage()
        app.config["TESTING"] = True
        with app.test_client() as client:
            resp = client.get("/api/bqm/dates")
            assert resp.status_code == 200
            assert resp.get_json() == []

    def test_bqm_csv_data_day(self, bqm_client):
        client, _ = bqm_client
        resp = client.get("/api/bqm/data/2026-03-15")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["date"] == "2026-03-15"
        assert data["points"] == 2
        assert data["data"]["timestamps"][0] == "2026-03-15T19:00:00+00:00"
        assert data["data"]["lost_polls"] == [0, 2]

    def test_bqm_csv_data_range(self, bqm_client):
        client, _ = bqm_client
        resp = client.get("/api/bqm/data/range?start=2026-03-15&end=2026-03-16")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["days"] == 2
        assert data["points"] == 3
        assert data["data"]["latency_avg"][-1] == 31.56

    def test_bqm_csv_data_range_cap(self, bqm_client):
        client, _ = bqm_client
        resp = client.get("/api/bqm/data/range?start=2026-01-01&end=2026-04-15")
        assert resp.status_code == 400

    def test_bqm_data_dates(self, bqm_client):
        client, today = bqm_client
        resp = client.get("/api/bqm/data/dates")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["csv_dates"] == ["2026-03-16", "2026-03-15"]
        assert today in data["png_dates"]

    @patch("app.modules.bqm.routes.validate_share_id")
    @patch("app.modules.bqm.routes.extract_share_id")
    def test_validate_monitor_success(self, mock_extract, mock_validate, bqm_client):
        client, _ = bqm_client
        mock_extract.return_value = "abc123-2"
        mock_validate.return_value = True
        resp = client.post("/api/bqm/validate-monitor", json={
            "url": "https://www.thinkbroadband.com/broadband/monitoring/quality/share/abc123def456789012345678901234567890abcd-2-y.csv",
        })
        assert resp.status_code == 200
        assert resp.get_json() == {"valid": True}

    @patch("app.modules.bqm.routes.validate_share_id")
    @patch("app.modules.bqm.routes.extract_share_id")
    def test_validate_monitor_login_failed(self, mock_extract, mock_validate, bqm_client):
        client, _ = bqm_client
        mock_extract.return_value = "abc123-2"
        mock_validate.return_value = False
        resp = client.post("/api/bqm/validate-monitor", json={
            "url": "https://www.thinkbroadband.com/broadband/monitoring/quality/share/abc123def456789012345678901234567890abcd-2-y.csv",
        })
        assert resp.status_code == 200
        assert resp.get_json()["valid"] is False

    def test_validate_monitor_missing_fields(self, bqm_client):
        client, _ = bqm_client
        resp = client.post("/api/bqm/validate-monitor", json={})
        assert resp.status_code == 400


class TestBQMLive:
    """Tests for the /api/bqm/live endpoint."""

    @patch("app.modules.bqm.thinkbroadband.urllib.request.urlopen")
    def test_live_success(self, mock_urlopen, bqm_client, sample_png):
        """Live fetch succeeds: returns fresh PNG with live source header."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = sample_png
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        client, _ = bqm_client
        resp = client.get("/api/bqm/live")
        assert resp.status_code == 200
        assert resp.content_type == "image/png"
        assert resp.headers.get("X-BQM-Source") == "live"
        assert resp.headers.get("X-BQM-Timestamp") is not None
        assert resp.data == sample_png

    @patch("app.modules.bqm.thinkbroadband.urllib.request.urlopen")
    def test_live_fallback_to_cached(self, mock_urlopen, bqm_client, sample_png):
        """Live fetch fails: falls back to today's cached image."""
        mock_urlopen.side_effect = Exception("Network error")

        client, _ = bqm_client
        resp = client.get("/api/bqm/live")
        assert resp.status_code == 200
        assert resp.content_type == "image/png"
        assert resp.headers.get("X-BQM-Source") == "cached"
        assert resp.data == sample_png

    @patch("app.modules.bqm.thinkbroadband.urllib.request.urlopen")
    def test_live_both_fail(self, mock_urlopen, tmp_path):
        """Both live and cached fail: returns 404."""
        mock_urlopen.side_effect = Exception("Network error")

        data_dir = str(tmp_path / "data_live")
        mgr = ConfigManager(data_dir)
        mgr.save({"modem_password": "test", "modem_type": "fritzbox", "bqm_url": "https://example.com/graph.png"})
        init_config(mgr)
        init_storage(None)
        _reset_bqm_module_storage()
        app.config["TESTING"] = True
        with app.test_client() as client:
            resp = client.get("/api/bqm/live")
            assert resp.status_code == 404


class TestBqmUiRender:
    def test_index_renders_chart_container_and_quick_ranges(self, bqm_client):
        client, _ = bqm_client
        resp = client.get("/")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'id="bqm-chart-container"' in html
        assert 'id="bqm-7d-btn"' in html
        assert 'id="bqm-30d-btn"' in html
        assert '/modules/docsight.bqm/static/js/bqm-chart.js' in html

    def test_index_renders_view_toggle(self, bqm_client):
        """Toggle buttons for uPlot/PNG must exist in the BQM card header."""
        client, _ = bqm_client
        resp = client.get("/")
        html = resp.get_data(as_text=True)
        assert 'id="bqm-view-toggle"' in html
        assert 'id="bqm-toggle-uplot"' in html
        assert 'id="bqm-toggle-png"' in html

    def test_index_no_slideshow_controls(self, bqm_client):
        """Slideshow controls must no longer be rendered."""
        client, _ = bqm_client
        resp = client.get("/")
        html = resp.get_data(as_text=True)
        assert 'id="bqm-slideshow-controls"' not in html
        assert 'id="bqm-play-btn"' not in html
        assert 'id="bqm-stop-btn"' not in html
        assert 'id="bqm-speed-tabs"' not in html

    def test_settings_renders_bqm_csv_fields(self, bqm_client):
        with open("app/modules/bqm/templates/bqm_settings.html", "r", encoding="utf-8") as f:
            html = f.read()
        assert 'id="bqm_url"' in html
        assert 'id="bqm_collect_time"' in html


class TestBqmChartConfig:
    """Verify bqm-chart.js has correct scale and toggle config."""

    def test_loss_scale_inverted(self):
        """Loss Y-axis must be inverted: range returns [sentMax, 0]."""
        with open("app/modules/bqm/static/js/bqm-chart.js", "r") as f:
            js = f.read()
        # The scale range must return [sentMax, 0] (inverted), not [0, sentMax]
        assert "return [sentMax, 0]" in js
        assert "return [0, sentMax]" not in js

    def test_toggle_logic_in_bqm_js(self):
        """bqm.js must contain toggle handler wiring."""
        with open("app/static/js/bqm.js", "r") as f:
            js = f.read()
        assert "bqm-toggle-uplot" in js
        assert "bqm-toggle-png" in js
        assert "updateBqmViewToggle" in js

    def test_no_slideshow_in_bqm_js(self):
        """bqm.js must not contain any slideshow references."""
        with open("app/static/js/bqm.js", "r") as f:
            js = f.read()
        assert "slideshow" not in js.lower()
        assert "bqm-play" not in js
        assert "bqm-stop-btn" not in js
