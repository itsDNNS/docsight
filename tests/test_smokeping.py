"""Tests for Smokeping integration."""

import pytest
from unittest.mock import MagicMock, patch

from app.smokeping import SmokepingClient


@pytest.fixture
def client():
    return SmokepingClient("http://smokeping.local:8067", target="ISP.Router")


# ── URL generation ──

class TestGraphUrl:
    def test_default_period(self, client):
        url = client.get_graph_url()
        assert "smokeping.cgi" in url
        assert "ISP/Router" in url  # dots replaced with /
        assert "3hours" in url

    def test_custom_period(self, client):
        url = client.get_graph_url("10days")
        assert "10days" in url

    def test_empty_target(self):
        c = SmokepingClient("http://smokeping.local", target="")
        url = c.get_graph_url()
        assert "target=" in url

    def test_trailing_slash_stripped(self):
        c = SmokepingClient("http://smokeping.local:8067/", target="X")
        url = c.get_graph_url()
        assert "http://smokeping.local:8067/smokeping" in url
        assert "//" not in url.replace("http://", "")


# ── Fetch graph ──

class TestFetchGraph:
    @patch("app.smokeping.requests.get")
    def test_fetch_png(self, mock_get, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "image/png"}
        mock_resp.content = b"\x89PNG fake image data"
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        data = client.fetch_graph("3hours")
        assert data is not None
        assert data.startswith(b"\x89PNG")

    @patch("app.smokeping.requests.get")
    def test_fetch_non_image_returns_none(self, mock_get, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "text/html"}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        assert client.fetch_graph() is None

    @patch("app.smokeping.requests.get")
    def test_fetch_network_error(self, mock_get, client):
        mock_get.side_effect = ConnectionError("unreachable")
        assert client.fetch_graph() is None


# ── Fetch data (CSV parse) ──

class TestFetchData:
    @patch("app.smokeping.requests.get")
    def test_parse_csv(self, mock_get, client):
        csv_content = (
            "# Smokeping data\n"
            "1706000000,0.012,0,0.011,0.012,0.013,0.014,0.015\n"
            "1706003600,0.015,1,0.014,0.016,U,0.017,0.018\n"
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = csv_content
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        data = client.fetch_data()
        assert data is not None
        assert len(data) == 2
        # First point: median 0.012s → 12ms
        assert data[0]["median_ms"] == 12.0
        assert data[0]["loss_pct"] == 0.0
        # Second point: 1 loss out of 5 probes
        assert data[1]["loss_pct"] == 20.0

    @patch("app.smokeping.requests.get")
    def test_parse_empty_csv(self, mock_get, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "# No data\n"
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        data = client.fetch_data()
        assert data == []

    @patch("app.smokeping.requests.get")
    def test_fetch_data_network_error(self, mock_get, client):
        mock_get.side_effect = ConnectionError()
        assert client.fetch_data() is None

    @patch("app.smokeping.requests.get")
    def test_parse_u_median(self, mock_get, client):
        """'U' (undefined) median should result in None."""
        csv_content = "1706000000,U,0,0.011,0.012\n"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = csv_content
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        data = client.fetch_data()
        assert data[0]["median_ms"] is None


# ── Health check ──

class TestHealthCheck:
    @patch("app.smokeping.requests.get")
    def test_reachable(self, mock_get, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp
        assert client.health_check() is True

    @patch("app.smokeping.requests.get")
    def test_unreachable(self, mock_get, client):
        mock_get.side_effect = ConnectionError()
        assert client.health_check() is False

    @patch("app.smokeping.requests.get")
    def test_server_error(self, mock_get, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_get.return_value = mock_resp
        assert client.health_check() is False


# ── CSV parser edge cases ──

class TestCsvParser:
    def test_short_lines_skipped(self, client):
        result = client._parse_csv("1706000000,0.012\n")
        assert result == []

    def test_comments_skipped(self, client):
        result = client._parse_csv("# comment\n\n")
        assert result == []

    def test_invalid_values_skipped(self, client):
        result = client._parse_csv("not_a_number,0.01,0\n")
        assert result == []
