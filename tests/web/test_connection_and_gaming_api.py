"""Tests for connection and gaming score endpoints."""

from app.runtime import current_runtime
import pytest


class TestConnectionEndpoint:
    def test_no_connection_info(self, client):
        resp = client.get("/api/connection")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["connection_type"] is None
        assert data["max_downstream_kbps"] is None
        assert data["max_upstream_kbps"] is None

    def test_with_connection_info(self, client):
        current_runtime().update_state(connection_info={
            "connection_type": "DOCSIS 3.1",
            "max_downstream_kbps": 250000,
            "max_upstream_kbps": 40000,
        })
        data = client.get("/api/connection").get_json()
        assert data["connection_type"] == "DOCSIS 3.1"
        assert data["max_downstream_kbps"] == 250000
        assert data["max_upstream_kbps"] == 40000

    def test_isp_name_from_config(self, config_mgr, make_app):
        config_mgr.save({"isp_name": "Vodafone"})
        app = make_app(config_manager=config_mgr)
        with app.test_client() as c:
            data = c.get("/api/connection").get_json()
        assert data["isp_name"] == "Vodafone"


class TestGamingScoreEndpoint:
    def test_no_data_returns_nulls(self, client):
        resp = client.get("/api/gaming-score")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["score"] is None
        assert data["grade"] is None
        assert data["components"] == {}
        assert data["has_speedtest"] is False
        assert data["raw"] == {}
        assert "genres" not in data

    def test_with_analysis_no_speedtest(self, client, sample_analysis):
        current_runtime().update_state(analysis=sample_analysis)
        resp = client.get("/api/gaming-score")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["score"] is None
        assert data["grade"] is None
        assert data["has_speedtest"] is False
        assert data["components"] == {}
        assert data["raw"] == {}

    def test_with_analysis_and_speedtest(self, client, sample_analysis):
        current_runtime().update_state(
            analysis=sample_analysis,
            speedtest_latest={"ping_ms": 15, "jitter_ms": 3, "packet_loss_pct": 0},
        )
        resp = client.get("/api/gaming-score")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["has_speedtest"] is True
        assert "latency" in data["components"]
        assert "jitter" in data["components"]
        assert "packet_loss" in data["components"]
        assert data["score"] >= 90  # perfect inputs should yield A
        assert data["raw"]["ping_ms"] == 15
        assert data["raw"]["jitter_ms"] == 3
        assert data["raw"]["packet_loss_pct"] == 0
        assert "genres" not in data

    def test_speedtest_can_be_scored_without_modem_data(self, client):
        current_runtime().update_state(
            analysis=None,
            speedtest_latest={"ping_ms": 15, "jitter_ms": 3, "packet_loss_pct": 0},
        )
        data = client.get("/api/gaming-score").get_json()
        assert data["score"] == 100
        assert set(data["components"]) == {"latency", "jitter", "packet_loss"}

    def test_incomplete_speedtest_does_not_break_dashboard(self, client, sample_analysis):
        from bs4 import BeautifulSoup

        current_runtime().update_state(
            analysis=sample_analysis,
            speedtest_latest={"download_mbps": 100, "upload_mbps": 20,
                              "ping_ms": None, "jitter_ms": None, "packet_loss_pct": None},
        )
        assert client.get("/api/gaming-score").get_json()["score"] is None
        response = client.get("/")
        assert response.status_code == 200
        soup = BeautifulSoup(response.data, "html.parser")
        assert soup.select_one("#view-gaming .gaming-grade-big") is None

    def test_enabled_flag_reflects_config(self, config_mgr, sample_analysis, make_app):
        config_mgr.save({"gaming_quality_enabled": True})
        app = make_app(config_manager=config_mgr)
        with app.app_context(), app.test_client() as c:
            current_runtime().update_state(analysis=sample_analysis)
            data = c.get("/api/gaming-score").get_json()
        assert data["enabled"] is True
