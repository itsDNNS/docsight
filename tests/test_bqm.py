"""Tests for ThinkBroadband BQM graph fetching, storage, and API."""

import pytest
from unittest.mock import patch, MagicMock

from app.thinkbroadband import fetch_graph
from app.storage import SnapshotStorage
from app.web import app, init_config, init_storage
from app.config import ConfigManager


# ── Fetcher Tests ──


class TestBQMFetcher:
    @patch("app.thinkbroadband.urllib.request.urlopen")
    def test_fetch_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"\x89PNG" + b"\x00" * 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = fetch_graph("https://example.com/graph.png")
        assert result is not None
        assert len(result) > 100

    @patch("app.thinkbroadband.urllib.request.urlopen")
    def test_fetch_empty_response(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b""
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = fetch_graph("https://example.com/graph.png")
        assert result is None

    @patch("app.thinkbroadband.urllib.request.urlopen")
    def test_fetch_too_small(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"tiny"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = fetch_graph("https://example.com/graph.png")
        assert result is None

    @patch("app.thinkbroadband.urllib.request.urlopen")
    def test_fetch_network_error(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("Connection refused")
        result = fetch_graph("https://example.com/graph.png")
        assert result is None

    def test_fetch_empty_url(self):
        result = fetch_graph("")
        assert result is None

    def test_fetch_none_url(self):
        result = fetch_graph(None)
        assert result is None


# ── Storage Tests ──


@pytest.fixture
def storage(tmp_path):
    db_path = str(tmp_path / "test.db")
    return SnapshotStorage(db_path, max_days=7)


@pytest.fixture
def sample_png():
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 200


class TestBQMStorage:
    def test_save_and_get(self, storage, sample_png):
        storage.save_bqm_graph(sample_png)
        dates = storage.get_bqm_dates()
        assert len(dates) == 1
        image = storage.get_bqm_graph(dates[0])
        assert image == sample_png

    def test_duplicate_same_day(self, storage, sample_png):
        storage.save_bqm_graph(sample_png)
        storage.save_bqm_graph(sample_png)
        dates = storage.get_bqm_dates()
        assert len(dates) == 1

    def test_get_nonexistent_date(self, storage):
        assert storage.get_bqm_graph("2099-01-01") is None

    def test_empty_dates(self, storage):
        assert storage.get_bqm_dates() == []

    def test_dates_order(self, storage, sample_png):
        """Dates should be newest first."""
        import sqlite3
        from datetime import datetime
        # Insert manually with different dates
        with sqlite3.connect(storage.db_path) as conn:
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
        dates = storage.get_bqm_dates()
        assert dates == ["2025-01-03", "2025-01-02", "2025-01-01"]

    def test_cleanup_removes_old_bqm(self, tmp_path, sample_png):
        """Cleanup should remove BQM graphs older than max_days."""
        import sqlite3
        db_path = str(tmp_path / "cleanup.db")
        s = SnapshotStorage(db_path, max_days=1)
        # Insert a graph dated 10 days ago
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO bqm_graphs (date, timestamp, image_blob) VALUES (?, ?, ?)",
                ("2020-01-01", "2020-01-01T12:00:00", sample_png),
            )
        assert len(s.get_bqm_dates()) == 1
        s._cleanup()
        assert len(s.get_bqm_dates()) == 0

    def test_unlimited_retention(self, tmp_path, sample_png):
        """max_days=0 should keep all BQM graphs."""
        import sqlite3
        db_path = str(tmp_path / "unlimited.db")
        s = SnapshotStorage(db_path, max_days=0)
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO bqm_graphs (date, timestamp, image_blob) VALUES (?, ?, ?)",
                ("2020-01-01", "2020-01-01T12:00:00", sample_png),
            )
        s._cleanup()
        assert len(s.get_bqm_dates()) == 1


# ── API Tests ──


@pytest.fixture
def bqm_storage(tmp_path, sample_png):
    """Storage pre-loaded with a BQM graph for today."""
    import sqlite3
    from datetime import datetime
    db_path = str(tmp_path / "bqm_api.db")
    s = SnapshotStorage(db_path, max_days=7)
    today = datetime.now().strftime("%Y-%m-%d")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO bqm_graphs (date, timestamp, image_blob) VALUES (?, ?, ?)",
            (today, datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), sample_png),
        )
    return s, today


@pytest.fixture
def bqm_client(tmp_path, bqm_storage):
    s, today = bqm_storage
    data_dir = str(tmp_path / "data")
    mgr = ConfigManager(data_dir)
    mgr.save({"modem_password": "test", "bqm_url": "https://example.com/graph.png"})
    init_config(mgr)
    init_storage(s)
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client, today


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
        mgr.save({"modem_password": "test"})
        init_config(mgr)
        init_storage(None)
        app.config["TESTING"] = True
        with app.test_client() as client:
            resp = client.get("/api/bqm/dates")
            assert resp.status_code == 200
            assert resp.get_json() == []
