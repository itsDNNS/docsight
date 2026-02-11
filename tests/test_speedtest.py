"""Tests for Speedtest Tracker client and API endpoint."""

import pytest
from unittest.mock import patch, MagicMock

from app.speedtest import SpeedtestClient
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

    @patch("app.speedtest.requests.Session.get")
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

    @patch("app.speedtest.requests.Session.get")
    def test_get_latest_empty(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": []}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        client = self._make_client()
        results = client.get_latest(1)
        assert results == []

    @patch("app.speedtest.requests.Session.get")
    def test_get_latest_connection_error(self, mock_get):
        mock_get.side_effect = Exception("Connection refused")

        client = self._make_client()
        results = client.get_latest(1)
        assert results == []

    @patch("app.speedtest.requests.Session.get")
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

    @patch("app.speedtest.requests.Session.get")
    def test_get_results_connection_error(self, mock_get):
        mock_get.side_effect = Exception("Timeout")

        client = self._make_client()
        results = client.get_results()
        assert results == []

    @patch("app.speedtest.requests.Session.get")
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


# ── Config Tests ──


class TestSpeedtestConfig:
    def test_is_speedtest_configured_false(self, tmp_path):
        mgr = ConfigManager(str(tmp_path / "data"))
        mgr.save({"modem_password": "test"})
        assert not mgr.is_speedtest_configured()

    def test_is_speedtest_configured_url_only(self, tmp_path):
        mgr = ConfigManager(str(tmp_path / "data"))
        mgr.save({"modem_password": "test", "speedtest_tracker_url": "http://x"})
        assert not mgr.is_speedtest_configured()

    def test_is_speedtest_configured_true(self, tmp_path):
        mgr = ConfigManager(str(tmp_path / "data"))
        mgr.save({
            "modem_password": "test",
            "speedtest_tracker_url": "http://x",
            "speedtest_tracker_token": "tok",
        })
        assert mgr.is_speedtest_configured()

    def test_token_is_encrypted(self, tmp_path):
        mgr = ConfigManager(str(tmp_path / "data"))
        mgr.save({
            "modem_password": "test",
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


@pytest.fixture
def speedtest_client(tmp_path):
    data_dir = str(tmp_path / "data")
    mgr = ConfigManager(data_dir)
    mgr.save({
        "modem_password": "test",
        "speedtest_tracker_url": "http://speedtest.local:8999",
        "speedtest_tracker_token": "test-token",
    })
    init_config(mgr)
    init_storage(None)
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


class TestSpeedtestAPI:
    @patch("app.speedtest.requests.Session.get")
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

    def test_api_speedtest_not_configured(self, tmp_path):
        data_dir = str(tmp_path / "data2")
        mgr = ConfigManager(data_dir)
        mgr.save({"modem_password": "test"})
        init_config(mgr)
        init_storage(None)
        app.config["TESTING"] = True
        with app.test_client() as client:
            resp = client.get("/api/speedtest?days=7")
            assert resp.status_code == 200
            assert resp.get_json() == []
