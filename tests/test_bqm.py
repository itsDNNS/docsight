"""Tests for ThinkBroadband BQM graph fetching, storage, and API."""

import io
import sqlite3
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest
import requests

from app.modules.bqm.auth import ThinkBroadbandBatchAbort, fetch_graph
from app.modules.bqm.collector import BQMCollector, collect_bqm
from app.modules.bqm.csv_parser import EXPECTED_COLUMNS
from app.modules.bqm.routes import run_bqm_initial_fetch
from app.modules.bqm.storage import BqmStorage
from app.module_registry import ModuleInfo
from app.storage import SnapshotStorage
from app.config import ConfigManager
from app.runtime import current_runtime
from tests.test_bqm_csv_parser import PARSED_ROWS, VALID_CSV
from tests.test_error_responses import _upload
from tests.test_smart_capture_api import configured_client

pytestmark = pytest.mark.usefixtures("route_app")


# ── Fetcher Tests ──

_SHARE_ID = "a" * 40
_SHARE_URL = "https://www.thinkbroadband.com/broadband/monitoring/quality/share/" + _SHARE_ID


def _response(status, content):
    """A real requests response for ``status`` returned from the share graph URL."""
    response = requests.Response()
    response.status_code, response._content, response.url = status, content, _SHARE_URL + ".png"
    return response


_FAILED_GETS = pytest.mark.parametrize("get", [
    MagicMock(side_effect=requests.ConnectionError(f"Max retries exceeded with url: {_SHARE_URL}.png")),
    MagicMock(return_value=_response(404, b"x" * 200)),
    MagicMock(return_value=_response(300, b"<html>" + b"x" * 200)),
], ids=["network-error", "http-404", "http-300-html"])


class TestBQMFetcher:
    @pytest.mark.parametrize("content, fetched", [
        (b"\x89PNG" + b"\x00" * 200, True),
        (b"", False),
        (b"tiny", False),
    ], ids=["png", "empty", "too-small"])
    @patch("app.modules.bqm.auth.requests.get")
    def test_fetch_content(self, mock_get, content, fetched):
        mock_get.return_value = _response(200, content)
        assert fetch_graph("https://example.com/graph.png") == (content if fetched else None)

    @_FAILED_GETS
    def test_fetch_failure_logs_no_share_id(self, get, caplog):
        with patch("app.modules.bqm.auth.requests.get", get):
            assert fetch_graph(_SHARE_URL + ".png") is None
        assert _SHARE_ID not in caplog.text

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
        *(dict(row) for row in PARSED_ROWS),
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

    def test_store_csv_data_reraises_storage_errors(self, bqm_storage, sample_csv_rows, monkeypatch):
        def boom(*args, **kwargs):
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr("app.storage.sqlite.sqlite3.connect", boom)

        with pytest.raises(sqlite3.OperationalError, match="database is locked"):
            bqm_storage.store_csv_data(sample_csv_rows)

    def test_last_success_metadata_roundtrip(self, bqm_storage):
        bqm_storage.record_collection_success(
            collection_date="2026-03-16",
            target_date="2026-03-15",
            mode="csv",
            rows=1440,
        )

        meta = bqm_storage.get_collection_metadata()
        assert meta["last_success_collection_date"] == "2026-03-16"
        assert meta["last_success_target_date"] == "2026-03-15"
        assert meta["last_success_mode"] == "csv"
        assert meta["last_success_rows"] == "1440"


# ── Collector Tests ──


def _sample_bqm_csv(date="2026-03-15"):
    return (
        'Timestamp,Sent Polls,Lost Polls,Min Latency (ns),Ave Latency (ns),Max Latency (ns),Score\n'
        f'{date}T00:00:00+00:00,100,0,30430000,33850000,52690000,1\n'
    )


def _bqm_config(tmp_path, url, **config):
    """Return (db_path, storage, config manager) for a collector using ``url``."""
    db_path = str(tmp_path / "collector.db")
    mgr = ConfigManager(str(tmp_path / "data"))
    mgr.save({"modem_password": "test", "modem_type": "fritzbox", "bqm_url": url, **config})
    return db_path, SnapshotStorage(db_path, max_days=7), mgr


@pytest.fixture
def fixed_clock():
    """Pin the configured-zone clock of the collector and of fetch-now to 2099-01-02 14:05."""
    now = MagicMock(return_value=datetime(2099, 1, 2, 14, 5))
    with patch("app.tz.local_now", now), patch("app.modules.bqm.collector.local_now", now):
        yield now


_BQM_CALLERS = pytest.mark.parametrize("run, png_date", [
    (lambda mgr, storage: BQMCollector(mgr, storage).collect().data, "2099-01-01"),
    (lambda mgr, storage: run_bqm_initial_fetch(mgr, storage), "2099-01-02"),
], ids=["collector", "fetch-now"])


class TestBQMCollector:
    @patch("app.modules.bqm.collector.fetch_share_csv")
    def test_collect_records_persistent_success_metadata(self, mock_fetch, tmp_path):
        db_path, storage, mgr = _bqm_config(tmp_path, _SHARE_URL + "-2-y.csv")
        mock_fetch.return_value = _sample_bqm_csv()

        collector = BQMCollector(mgr, storage)
        result = collector.collect()

        assert result.success is True
        meta = BqmStorage(db_path).get_collection_metadata()
        assert meta["last_success_mode"] == "csv"
        assert meta["last_success_target_date"] == "2026-03-15"
        assert meta["last_success_rows"] == "1"

    @pytest.mark.usefixtures("fixed_clock")
    @patch("app.modules.bqm.collector.fetch_share_csv")
    def test_new_collector_skips_when_target_date_already_collected(self, mock_fetch, tmp_path):
        db_path, storage, mgr = _bqm_config(tmp_path, _SHARE_URL + "-2-y.csv")
        bs = BqmStorage(db_path)
        bs.record_collection_success(
            collection_date="2099-01-02",
            target_date="2099-01-01",
            mode="csv",
            rows=1440,
        )

        result = BQMCollector(mgr, storage).collect()

        assert result.success is True
        assert result.data == {"skipped": True, "reason": "already_collected"}
        mock_fetch.assert_not_called()

    @_BQM_CALLERS
    @patch("app.modules.bqm.collector.fetch_graph")
    def test_png_collection_records_yesterday_target_for_restart_skip(
        self, mock_fetch, run, png_date, tmp_path, sample_png, fixed_clock,
    ):
        """The collector stores the graph under yesterday, fetch-now under today."""
        db_path, storage, mgr = _bqm_config(tmp_path, _SHARE_URL + ".png", timezone="Pacific/Kiritimati")
        mock_fetch.return_value = sample_png

        assert run(mgr, storage) == {"success": True, "date": png_date, "mode": "png"}

        fixed_clock.assert_called_with("Pacific/Kiritimati")
        mock_fetch.assert_called_once_with(_SHARE_URL + ".png")
        assert BqmStorage(db_path).get_bqm_dates() == [png_date]
        meta = BqmStorage(db_path).get_collection_metadata()
        assert meta["last_success_collection_date"] == "2099-01-02"
        assert meta["last_success_target_date"] == png_date
        assert meta["last_success_mode"] == "png"

    @_BQM_CALLERS
    @patch("app.modules.bqm.collector.fetch_graph")
    def test_failed_graph_write_does_not_mark_day_collected(self, mock_fetch, run, png_date, tmp_path, sample_png):
        db_path, storage, mgr = _bqm_config(tmp_path, _SHARE_URL + ".png")
        mock_fetch.return_value = sample_png
        BqmStorage(db_path)
        with sqlite3.connect(db_path) as conn:
            conn.execute("CREATE TRIGGER reject_graph BEFORE INSERT ON bqm_graphs BEGIN SELECT RAISE(ABORT, 'disk full'); END")

        assert run(mgr, storage) == {"success": False, "error": "BQM fetch failed"}
        assert BqmStorage(db_path).get_collection_metadata() == {}

    @pytest.mark.parametrize("url", [
        "https://example.com/graph.png",
        "https://example.com/graphs/" + "b" * 40 + ".png",
    ], ids=["plain", "hex-filename"])
    @patch("app.modules.bqm.collector.fetch_graph")
    def test_png_url_outside_thinkbroadband_is_fetched_as_configured(self, mock_fetch, url, bqm_storage, sample_png):
        mock_fetch.return_value = sample_png
        assert collect_bqm(bqm_storage, url, "2099-01-02", "2099-01-01")["success"] is True
        mock_fetch.assert_called_once_with(url)
        assert bqm_storage.get_bqm_dates() == ["2099-01-01"]

    @pytest.mark.parametrize("fetched, error", [
        ("", "BQM CSV download failed"),
        (",".join(EXPECTED_COLUMNS) + "\n", "BQM CSV contained no valid rows"),
        ("not a bqm csv\n", "BQM CSV is invalid"),
        (ThinkBroadbandBatchAbort("HTTP 429"), "ThinkBroadband temporarily rejected the BQM request"),
        (sqlite3.OperationalError("database is locked"), "BQM fetch failed"),
    ], ids=["empty", "no-rows", "bad-header", "batch-abort", "unexpected"])
    def test_csv_failure_does_not_mark_day_collected(self, fetched, error, bqm_storage):
        with patch("app.modules.bqm.collector.fetch_share_csv", side_effect=[fetched]):
            result = collect_bqm(bqm_storage, _SHARE_URL + "-2-y.csv", "2099-01-02", "2099-01-01")

        assert result == {"success": False, "error": error}
        assert bqm_storage.get_collection_metadata() == {}


# ── API Tests ──



def single_module_loader(module):
    """Module loader stub whose only (enabled) module is ``module``."""
    return SimpleNamespace(
        get_enabled_modules=lambda: [module],
        get_modules=lambda: [module],
        get_theme_modules=lambda: [],
    )


def bqm_module(**fields):
    return ModuleInfo(
        id="docsight.bqm",
        name="BQM",
        description="Test module context",
        version="1.0.0",
        author="DOCSight",
        min_app_version="2026.2",
        type="integration",
        contributes={},
        path="",
        **fields,
    )


def _enabled_bqm_loader():
    return single_module_loader(bqm_module(
        template_paths={"tab": "bqm_tab.html", "dialogs": "bqm_dialogs.html"},
        has_js=True,
    ))


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
    previous_module_loader = current_runtime().module_loader
    current_runtime().module_loader = _enabled_bqm_loader()
    try:
        with configured_client(tmp_path / "data", s, bqm_url="https://example.com/graph.png") as client:
            yield client, today
    finally:
        current_runtime().module_loader = previous_module_loader


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
        with configured_client(tmp_path / "data3") as client:
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

    @pytest.mark.parametrize("prefix", [b"", b"\xef\xbb\xbf"], ids=["plain", "utf8-bom"])
    def test_import_csv_upload(self, bqm_client, prefix):
        client, _ = bqm_client
        with patch.object(BqmStorage, "store_csv_data") as store:
            resp = client.post("/api/bqm/import-csv", data={"file": (io.BytesIO(prefix + VALID_CSV.encode()), "bqm.csv")},
                               content_type="multipart/form-data")
        assert (resp.status_code, resp.get_json()) == (
            200, {"parsed_rows": 2, "days": 1, "date_range": {"start": "2026-03-15", "end": "2026-03-15"}})
        store.assert_called_once_with(PARSED_ROWS)

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

    @patch("app.modules.bqm.collector.fetch_share_csv")
    def test_fetch_now_downloads_and_stores_csv(self, mock_fetch, bqm_client):
        client, _ = bqm_client
        mock_fetch.return_value = _sample_bqm_csv("2026-03-15")
        client.post("/api/config", json={
            "bqm_url": "https://www.thinkbroadband.com/broadband/monitoring/quality/share/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb-2-y.csv",
        })

        resp = client.post("/api/bqm/fetch-now")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["mode"] == "csv"
        assert data["rows"] == 1
        assert data["date"] == "2026-03-15"

    @patch("app.modules.bqm.collector.fetch_graph")
    def test_fetch_now_rejects_arbitrary_png_url(self, mock_fetch, bqm_client):
        client, _ = bqm_client
        client.post("/api/config", json={"bqm_url": "http://192.168.1.1/router.png"})

        resp = client.post("/api/bqm/fetch-now")

        assert resp.status_code == 400
        data = resp.get_json()
        assert data["success"] is False
        assert "ThinkBroadband CSV Yesterday share URL" in data["error"]
        mock_fetch.assert_not_called()

    @patch("app.blueprints.config_bp.run_bqm_initial_fetch")
    def test_config_save_triggers_initial_bqm_fetch_when_url_changes(self, mock_fetch, bqm_client):
        client, _ = bqm_client
        mock_fetch.return_value = {"success": True, "mode": "csv", "rows": 1, "date": "2026-03-15"}

        resp = client.post("/api/config", json={"bqm_url": "https://www.thinkbroadband.com/broadband/monitoring/quality/share/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb-2-y.csv"})

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["bqm_initial_fetch"] == {"success": True, "mode": "csv", "rows": 1, "date": "2026-03-15"}
        mock_fetch.assert_called_once()

    @patch("app.blueprints.config_bp.run_bqm_initial_fetch")
    def test_config_save_does_not_fetch_arbitrary_bqm_url(self, mock_fetch, bqm_client):
        client, _ = bqm_client

        resp = client.post("/api/config", json={"bqm_url": "http://192.168.1.1"})

        assert resp.status_code == 200
        data = resp.get_json()
        assert data == {"success": True}
        mock_fetch.assert_not_called()

    @patch("app.blueprints.config_bp.run_bqm_initial_fetch")
    def test_config_save_rejects_embedded_thinkbroadband_url_for_initial_fetch(self, mock_fetch, bqm_client):
        client, _ = bqm_client

        resp = client.post("/api/config", json={
            "bqm_url": "https://evil.example/redirect?next=https://www.thinkbroadband.com/broadband/monitoring/quality/share/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb-2-y.csv",
        })

        assert resp.status_code == 200
        assert resp.get_json() == {"success": True}
        mock_fetch.assert_not_called()


    @pytest.mark.parametrize("bqm_url, method, path, kwargs", [
        ("", "post", "/api/config", {"json": {"bqm_url": _SHARE_URL + "-2-y.csv"}}),
        (_SHARE_URL + "-2-y.csv", "post", "/api/bqm/fetch-now", {}),
        (_SHARE_URL + ".png", "post", "/api/bqm/fetch-now", {}),
        (_SHARE_URL + ".png", "get", "/api/bqm/live", {}),
        ("", "post", "/api/bqm/validate-monitor", {"json": {"url": _SHARE_URL + "-2-y.csv"}}),
        ("", "post", "/api/bqm/import", _upload("files[]", b"\x89PNG graph", _SHARE_ID + ".png", dates="2026-01-01")),
        ("", "post", "/api/bqm/import-csv",
         _upload("file", (VALID_CSV + f'"{_SHARE_ID}","{_SHARE_ID}","","1","1","1","1"\n').encode(), "bqm.csv")),
    ], ids=["initial-fetch", "csv-fetch", "png-fetch", "live-graph", "validate-monitor", "graph-import", "csv-row"])
    @patch.object(BqmStorage, "import_bqm_graph", side_effect=sqlite3.OperationalError(f"disk full: {_SHARE_ID}"))
    @patch("app.modules.bqm.auth.requests.get",
           side_effect=requests.ConnectionError(f"Max retries exceeded with url: {_SHARE_URL}-2-y.csv"))
    def test_failures_keep_share_id_out_of_logs(self, _get, _import, bqm_client, caplog, bqm_url, method, path, kwargs):
        client, _ = bqm_client
        client.post("/api/config", json={"bqm_url": bqm_url})
        caplog.clear()
        getattr(client, method)(path, **kwargs)
        assert caplog.records
        assert _SHARE_ID not in caplog.text


class TestBQMLive:
    """Tests for the /api/bqm/live endpoint."""

    @patch("app.modules.bqm.auth.requests.get")
    def test_live_success(self, mock_get, bqm_client, sample_png):
        """Live fetch succeeds: returns fresh PNG with live source header."""
        mock_get.return_value = _response(200, sample_png)

        client, _ = bqm_client
        resp = client.get("/api/bqm/live")
        assert resp.status_code == 200
        assert resp.content_type == "image/png"
        assert resp.headers.get("X-BQM-Source") == "live"
        assert resp.headers.get("X-BQM-Timestamp") is not None
        assert resp.data == sample_png

    @_FAILED_GETS
    def test_live_fallback_to_cached(self, get, bqm_client, sample_png):
        """Live fetch fails: falls back to today's cached image."""
        client, _ = bqm_client
        with patch("app.modules.bqm.auth.requests.get", get):
            resp = client.get("/api/bqm/live")
        assert resp.status_code == 200
        assert resp.content_type == "image/png"
        assert resp.headers.get("X-BQM-Source") == "cached"
        assert resp.data == sample_png

    @patch("app.modules.bqm.auth.requests.get", side_effect=requests.ConnectionError("Network error"))
    def test_live_both_fail(self, _mock_get, tmp_path):
        """Both live and cached fail: returns 404."""

        with configured_client(tmp_path / "data_live", bqm_url="https://example.com/graph.png") as client:
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

    def test_index_omits_chart_script_when_bqm_module_is_disabled(self, bqm_client):
        client, _ = bqm_client
        enabled_loader = current_runtime().module_loader
        try:
            current_runtime().module_loader = None
            resp = client.get("/")
        finally:
            current_runtime().module_loader = enabled_loader

        assert resp.status_code == 200
        assert '/modules/docsight.bqm/static/js/bqm-chart.js' not in resp.get_data(
            as_text=True
        )

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

    def test_settings_explains_csv_yesterday_and_bulk_import(self, bqm_client):
        with open("app/modules/bqm/templates/bqm_settings.html", "r", encoding="utf-8") as f:
            html = f.read()
        assert "CSV Yesterday" in html
        assert "CSV Live" in html
        assert "12 months" in html
        assert "bulk import" in html.lower()

    def test_bqm_setup_modal_points_to_csv_yesterday_and_bulk_import(self, bqm_client):
        with open("app/modules/bqm/templates/bqm_dialogs.html", "r", encoding="utf-8") as f:
            html = f.read()
        assert "CSV Yesterday share URL" in html
        assert "CSV Live is for spot checks only" in html
        assert "one initial fetch" in html
        assert "CSV bulk import" in html
        assert "ends in .png" not in html
        assert "A public or shareable BQM monitor URL" not in html

    def test_bqm_calendar_buttons_are_accessible(self):
        with open("app/modules/bqm/templates/bqm_tab.html", "r", encoding="utf-8") as f:
            html = f.read()
        with open("app/modules/bqm/static/main.js", "r", encoding="utf-8") as f:
            js = f.read()
        assert 'aria-label="{{ t.bqm_import_title }}"' in html
        assert 'aria-label="{{ t.get(\'bqm_csv_import\', \'Import CSV\') }}"' in html
        assert 'aria-label="{{ t.bqm_delete }}"' in html
        assert "document.createElement('button')" in js
        # The visible day number stays in the name; month, year and data kind are screen reader text.
        assert "cell.appendChild(document.createTextNode(String(d)));" in js
        assert "bqmScreenReaderText(monthNames[month] + ' ')" in js
        assert "T.bqm_cached_png || 'Cached PNG'" in js


class TestBqmChartConfig:
    """Verify bqm-chart.js has correct scale and toggle config."""

    def test_loss_scale_inverted(self):
        """Loss Y-axis must be inverted: range returns [sentMax, 0]."""
        with open("app/modules/bqm/static/js/bqm-chart.js", "r", encoding="utf-8") as f:
            js = f.read()
        # The scale range must return [sentMax, 0] (inverted), not [0, sentMax]
        assert "return [sentMax, 0]" in js
        assert "return [0, sentMax]" not in js

    def test_loss_poll_overlay_has_no_zero_baseline(self):
        """Lost-poll events should draw as plugin bars only, not a red zero-value line."""
        with open("app/modules/bqm/static/js/bqm-chart.js", "r", encoding="utf-8") as f:
            js = f.read()
        with open("app/static/js/chart-engine.js", "r", encoding="utf-8") as f:
            chart_engine = f.read()

        loss_dataset = js[js.index("label: (T && T.bqm_chart_lost_polls)") : js.index("], 'line', null")]
        assert "lineWidth: 0" in loss_dataset
        assert "width: ds.lineWidth" in chart_engine

    def test_loss_poll_toggle_controls_plugin_overlay(self):
        """Hiding Lost Polls in the legend should hide the real loss markers too."""
        with open("app/modules/bqm/static/js/bqm-chart.js", "r", encoding="utf-8") as f:
            js = f.read()
        plugin_body = js[js.index("function bqmLossPlugin") : js.index("function render(container")]
        assert "u.series[seriesIdx].show === false" in plugin_body

    def test_toggle_logic_in_bqm_js(self):
        """BQM main.js must contain toggle handler wiring."""
        with open("app/modules/bqm/static/main.js", "r", encoding="utf-8") as f:
            js = f.read()
        assert "bqm-toggle-uplot" in js
        assert "bqm-toggle-png" in js
        assert "updateBqmViewToggle" in js

    def test_live_badge_labels_cached_png_without_claiming_live(self):
        """Cached fallback status must not be labelled as live freshness."""
        with open("app/modules/bqm/static/main.js", "r", encoding="utf-8") as f:
            js = f.read()
        assert "T.bqm_cached_png" in js
        assert "T.bqm_cached_png_loaded" in js
        assert "source === 'live' ? 'inline' : 'none'" not in js

    def test_no_slideshow_in_bqm_js(self):
        """BQM main.js must not contain any slideshow references."""
        with open("app/modules/bqm/static/main.js", "r", encoding="utf-8") as f:
            js = f.read()
        assert "slideshow" not in js.lower()
        assert "bqm-play" not in js
        assert "bqm-stop-btn" not in js
