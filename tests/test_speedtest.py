"""Tests for Speedtest Tracker client and API endpoint."""

import pytest
from unittest.mock import patch, MagicMock

from app.modules.speedtest.client import SpeedtestClient
from app.web import app, init_config, init_storage
from app.config import ConfigManager


# ── Sample API responses ──

SAMPLE_RESULT = {
    "id": 1,
    "ping": 12.5,
    "download_bits": 1_100_000_000,
    "upload_bits": 55_000_000,
    "download_bits_human": "1.10 Gbps",
    "upload_bits_human": "55.00 Mbps",
    "status": "completed",
    "healthy": True,
    "created_at": "2025-01-15T10:30:00Z",
    "data": {
        "ping": {"jitter": 2.3},
        "packetLoss": 0.5,
        "timestamp": "2025-01-15T10:30:00Z",
    },
}

SAMPLE_RESULT_MINIMAL = {
    "id": 2,
    "ping": 8.0,
    "download_bits": 500_000_000,
    "upload_bits": 25_000_000,
    "download_bits_human": "500.00 Mbps",
    "upload_bits_human": "25.00 Mbps",
    "status": "completed",
    "healthy": None,
    "created_at": "2025-01-14T08:00:00Z",
    "data": {},
}

SAMPLE_API_RESPONSE = {
    "data": [SAMPLE_RESULT, SAMPLE_RESULT_MINIMAL],
}


# ── Client Tests ──


class TestSpeedtestClient:
    def _make_client(self):
        return SpeedtestClient("http://speedtest.local:8999", "test-token")

    @patch("app.modules.speedtest.client.requests.Session.get")
    def test_get_latest_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": [SAMPLE_RESULT]}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        client = self._make_client()
        results = client.get_latest(1)

        assert len(results) == 1
        r = results[0]
        assert r["download_mbps"] == 1100.0
        assert r["upload_mbps"] == 55.0
        assert r["ping_ms"] == 12.5
        assert r["jitter_ms"] == 2.3
        assert r["packet_loss_pct"] == 0.5
        assert r["download_human"] == "1.10 Gbps"
        assert r["timestamp"] == "2025-01-15T10:30:00Z"

    @patch("app.modules.speedtest.client.requests.Session.get")
    def test_get_latest_empty(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": []}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        client = self._make_client()
        results = client.get_latest(1)
        assert results == []

    @patch("app.modules.speedtest.client.requests.Session.get")
    def test_get_latest_connection_error(self, mock_get):
        mock_get.side_effect = Exception("Connection refused")

        client = self._make_client()
        results = client.get_latest(1)
        assert results == []

    @patch("app.modules.speedtest.client.requests.Session.get")
    def test_get_results_pagination(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {**SAMPLE_API_RESPONSE, "meta": {"last_page": 1}}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        client = self._make_client()
        results = client.get_results(per_page=100)

        assert len(results) == 2
        call_kwargs = mock_get.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params")
        assert params["page[size]"] == 100
        assert params["page[number]"] == 1

    @patch("app.modules.speedtest.client.requests.Session.get")
    def test_get_results_connection_error(self, mock_get):
        mock_get.side_effect = Exception("Timeout")

        client = self._make_client()
        results = client.get_results()
        assert results == []

    @patch("app.modules.speedtest.client.requests.Session.get")
    def test_parse_minimal_result(self, mock_get):
        """Result with empty data dict should not crash."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": [SAMPLE_RESULT_MINIMAL]}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        client = self._make_client()
        results = client.get_latest(1)

        assert len(results) == 1
        r = results[0]
        assert r["ping_ms"] == 8.0
        assert r["jitter_ms"] == 0
        assert r["packet_loss_pct"] == 0

    def test_auth_headers(self):
        client = self._make_client()
        assert client.session.headers["Authorization"] == "Bearer test-token"
        assert client.session.headers["Accept"] == "application/json"

    def test_url_trailing_slash(self):
        client = SpeedtestClient("http://example.com:8999/", "tok")
        assert client.base_url == "http://example.com:8999"

    @patch("app.modules.speedtest.client.requests.Session.get")
    def test_get_latest_with_error_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": [SAMPLE_RESULT]}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        client = self._make_client()
        results, error = client.get_latest_with_error(1)
        assert len(results) == 1
        assert error is None

    @patch("app.modules.speedtest.client.requests.Session.get")
    def test_get_latest_with_error_connection_error(self, mock_get):
        import requests as req
        mock_get.side_effect = req.ConnectionError("Connection refused")

        client = self._make_client()
        results, error = client.get_latest_with_error(1)
        assert results == []
        assert "ConnectionError" in error

    @patch("app.modules.speedtest.client.requests.Session.get")
    def test_get_latest_with_error_http_error(self, mock_get):
        import requests as req
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.raise_for_status.side_effect = req.HTTPError(response=mock_resp)
        mock_get.return_value = mock_resp

        client = self._make_client()
        results, error = client.get_latest_with_error(1)
        assert results == []
        assert "401" in error

    @patch("app.modules.speedtest.client.requests.Session.get")
    def test_get_latest_with_error_timeout(self, mock_get):
        import requests as req
        mock_get.side_effect = req.Timeout("timed out")

        client = self._make_client()
        results, error = client.get_latest_with_error(1)
        assert results == []
        assert "Timeout" in error


# ── Config Tests ──


class TestSpeedtestConfig:
    def test_is_speedtest_configured_false(self, tmp_path):
        mgr = ConfigManager(str(tmp_path / "data"))
        mgr.save({"modem_password": "test", "modem_type": "fritzbox"})
        assert not mgr.is_speedtest_configured()

    def test_is_speedtest_configured_url_only(self, tmp_path):
        mgr = ConfigManager(str(tmp_path / "data"))
        mgr.save({"modem_password": "test", "modem_type": "fritzbox", "speedtest_tracker_url": "http://x"})
        assert not mgr.is_speedtest_configured()

    def test_is_speedtest_configured_true(self, tmp_path):
        mgr = ConfigManager(str(tmp_path / "data"))
        mgr.save({
            "modem_password": "test",
            "modem_type": "fritzbox",
            "speedtest_tracker_url": "http://x",
            "speedtest_tracker_token": "tok",
        })
        assert mgr.is_speedtest_configured()

    def test_token_is_encrypted(self, tmp_path):
        mgr = ConfigManager(str(tmp_path / "data"))
        mgr.save({
            "modem_password": "test",
            "modem_type": "fritzbox",
            "speedtest_tracker_token": "my-secret-token",
        })
        # Raw value in file should not be the plaintext
        import json
        with open(mgr.config_path) as f:
            raw = json.load(f)
        assert raw["speedtest_tracker_token"] != "my-secret-token"
        # But get() returns decrypted
        assert mgr.get("speedtest_tracker_token") == "my-secret-token"


# ── API Tests ──


def _reset_speedtest_module_storage():
    """Reset the speedtest module's lazy-initialized storage between tests."""
    import app.modules.speedtest.routes as speedtest_routes
    speedtest_routes._storage = None


@pytest.fixture
def speedtest_client(tmp_path):
    data_dir = str(tmp_path / "data")
    mgr = ConfigManager(data_dir)
    mgr.save({
        "modem_password": "test",
        "modem_type": "fritzbox",
        "speedtest_tracker_url": "http://speedtest.local:8999",
        "speedtest_tracker_token": "test-token",
    })
    init_config(mgr)
    init_storage(None)
    _reset_speedtest_module_storage()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client
    _reset_speedtest_module_storage()


class TestSpeedtestAPI:
    @patch("app.modules.speedtest.client.requests.Session.get")
    def test_api_speedtest(self, mock_get, speedtest_client):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": [SAMPLE_RESULT]}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        resp = speedtest_client.get("/api/speedtest?days=7")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]["download_mbps"] == 1100.0
        assert data[0]["ping_ms"] == 12.5

    @patch("app.modules.speedtest.client.requests.Session.get")
    def test_api_test_speedtest_success(self, mock_get, speedtest_client):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": [SAMPLE_RESULT]}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        resp = speedtest_client.post("/api/test-speedtest", json={
            "speedtest_tracker_url": "http://speedtest.local:8999",
            "speedtest_tracker_token": "test-token",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["results"] == 1
        assert "download" in data["latest"]

    def test_api_test_speedtest_missing_fields(self, speedtest_client):
        resp = speedtest_client.post("/api/test-speedtest", json={})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is False
        assert "required" in data["error"].lower()

    @patch("app.modules.speedtest.client.requests.Session.get")
    def test_api_test_speedtest_connection_error(self, mock_get, speedtest_client):
        import requests as req
        mock_get.side_effect = req.ConnectionError("Connection refused")

        resp = speedtest_client.post("/api/test-speedtest", json={
            "speedtest_tracker_url": "http://speedtest.local:8999",
            "speedtest_tracker_token": "test-token",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is False
        assert "ConnectionError" in data["error"]

    def test_signal_api_treats_legacy_unsupported_zero_error_counters_as_unavailable(self, speedtest_client, monkeypatch):
        import app.modules.speedtest.routes as speedtest_routes

        class SpeedtestStorage:
            def get_speedtest_by_id(self, result_id):
                return {"id": result_id, "timestamp": "2025-01-15T10:30:00Z"}

        class CoreStorage:
            def get_closest_snapshot(self, timestamp):
                return {
                    "timestamp": timestamp,
                    "summary": {
                        "errors_supported": False,
                        "health": "good",
                        "ds_correctable_errors": 0,
                        "ds_uncorrectable_errors": 0,
                    },
                    "us_channels": [],
                }

        monkeypatch.setattr(speedtest_routes, "_get_speedtest_storage", lambda: SpeedtestStorage())
        monkeypatch.setattr(speedtest_routes, "get_storage", lambda: CoreStorage())

        resp = speedtest_client.get("/api/speedtest/1/signal")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["found"] is True
        assert data["ds_correctable_errors"] is None
        assert data["ds_uncorrectable_errors"] is None

    def test_signal_api_preserves_supported_zero_error_counters(self, speedtest_client, monkeypatch):
        import app.modules.speedtest.routes as speedtest_routes

        class SpeedtestStorage:
            def get_speedtest_by_id(self, result_id):
                return {"id": result_id, "timestamp": "2025-01-15T10:30:00Z"}

        class CoreStorage:
            def get_closest_snapshot(self, timestamp):
                return {
                    "timestamp": timestamp,
                    "summary": {
                        "errors_supported": True,
                        "health": "good",
                        "ds_correctable_errors": 0,
                        "ds_uncorrectable_errors": 0,
                    },
                    "us_channels": [],
                }

        monkeypatch.setattr(speedtest_routes, "_get_speedtest_storage", lambda: SpeedtestStorage())
        monkeypatch.setattr(speedtest_routes, "get_storage", lambda: CoreStorage())

        resp = speedtest_client.get("/api/speedtest/1/signal")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["found"] is True
        assert data["ds_correctable_errors"] == 0
        assert data["ds_uncorrectable_errors"] == 0

    def test_api_speedtest_not_configured(self, tmp_path):
        data_dir = str(tmp_path / "data2")
        mgr = ConfigManager(data_dir)
        mgr.save({"modem_password": "test", "modem_type": "fritzbox"})
        init_config(mgr)
        init_storage(None)
        _reset_speedtest_module_storage()
        app.config["TESTING"] = True
        with app.test_client() as client:
            resp = client.get("/api/speedtest?days=7")
            assert resp.status_code == 200
            assert resp.get_json() == []


class TestSpeedtestRun:
    """Tests for POST /api/speedtest/run."""

    def _reset_rate_limit(self):
        import app.modules.speedtest.routes as sr
        sr._last_trigger_ts = 0

    @patch("app.modules.speedtest.routes.requests.post")
    def test_run_success(self, mock_post, speedtest_client):
        self._reset_rate_limit()
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_post.return_value = mock_resp

        resp = speedtest_client.post("/api/speedtest/run")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        mock_post.assert_called_once()

    @patch("app.modules.speedtest.routes.requests.post")
    def test_run_rate_limited(self, mock_post, speedtest_client):
        self._reset_rate_limit()
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_post.return_value = mock_resp

        resp1 = speedtest_client.post("/api/speedtest/run")
        assert resp1.status_code == 200

        resp2 = speedtest_client.post("/api/speedtest/run")
        assert resp2.status_code == 429
        assert "Rate limited" in resp2.get_json()["error"]

    @patch("app.modules.speedtest.routes.requests.post")
    def test_run_stt_error(self, mock_post, speedtest_client):
        self._reset_rate_limit()
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_post.return_value = mock_resp

        resp = speedtest_client.post("/api/speedtest/run")
        assert resp.status_code == 502
        assert resp.get_json()["success"] is False

    @patch("app.modules.speedtest.routes.requests.post")
    def test_run_connection_error(self, mock_post, speedtest_client):
        self._reset_rate_limit()
        import requests as req
        mock_post.side_effect = req.ConnectionError("refused")

        resp = speedtest_client.post("/api/speedtest/run")
        assert resp.status_code == 502
        assert "Cannot reach" in resp.get_json()["error"]

    def test_run_not_configured(self, tmp_path):
        data_dir = str(tmp_path / "data3")
        mgr = ConfigManager(data_dir)
        mgr.save({"modem_password": "test", "modem_type": "fritzbox"})
        init_config(mgr)
        init_storage(None)
        _reset_speedtest_module_storage()
        app.config["TESTING"] = True
        with app.test_client() as client:
            resp = client.post("/api/speedtest/run")
            assert resp.status_code == 400
            assert "not configured" in resp.get_json()["error"]

    def test_run_blocked_in_demo_mode(self, tmp_path):
        data_dir = str(tmp_path / "data4")
        mgr = ConfigManager(data_dir)
        mgr.save({
            "modem_password": "test",
            "modem_type": "fritzbox",
            "demo_mode": True,
            "speedtest_tracker_url": "http://speedtest.local:8999",
            "speedtest_tracker_token": "test-token",
        })
        init_config(mgr)
        init_storage(None)
        _reset_speedtest_module_storage()
        app.config["TESTING"] = True
        with app.test_client() as client:
            resp = client.post("/api/speedtest/run")
            assert resp.status_code == 400
            assert "demo" in resp.get_json()["error"].lower()
