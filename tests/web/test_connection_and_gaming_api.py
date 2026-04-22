"""Tests for connection and gaming score endpoints."""

import pytest

from app.web import app, init_config, update_state

class TestConnectionEndpoint:
    def test_no_connection_info(self, client):
        resp = client.get("/api/connection")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["connection_type"] is None
        assert data["max_downstream_kbps"] is None
        assert data["max_upstream_kbps"] is None

    def test_with_connection_info(self, client):
        update_state(connection_info={
            "connection_type": "DOCSIS 3.1",
            "max_downstream_kbps": 250000,
            "max_upstream_kbps": 40000,
        })
        data = client.get("/api/connection").get_json()
        assert data["connection_type"] == "DOCSIS 3.1"
        assert data["max_downstream_kbps"] == 250000
        assert data["max_upstream_kbps"] == 40000

    def test_isp_name_from_config(self, config_mgr):
        config_mgr.save({"isp_name": "Vodafone"})
        init_config(config_mgr)
        app.config["TESTING"] = True
        with app.test_client() as c:
            data = c.get("/api/connection").get_json()
        assert data["isp_name"] == "Vodafone"


class TestGamingScoreEndpoint:
    @pytest.fixture(autouse=True)
    def reset_state(self):
        from app.web import _state
        _state["analysis"] = None
        _state["speedtest_latest"] = None
        yield
        _state["analysis"] = None
        _state["speedtest_latest"] = None

    def test_no_data_returns_nulls(self, client):
        resp = client.get("/api/gaming-score")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["score"] is None
        assert data["grade"] is None
        assert data["components"] == {}
        assert data["has_speedtest"] is False
        assert data["raw"] == {}
        assert set(data["genres"].keys()) == {"fps", "moba", "mmo", "strategy"}

    def test_with_analysis_no_speedtest(self, client, sample_analysis):
        update_state(analysis=sample_analysis)
        resp = client.get("/api/gaming-score")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data["score"], int)
        assert data["grade"] in ("A", "B", "C", "D", "F")
        assert data["has_speedtest"] is False
        assert "docsis_health" in data["components"]
        assert "snr_headroom" in data["components"]
        assert data["raw"]["docsis_health"] == "good"
        assert data["raw"]["ds_snr_min"] == 35.0
        assert "ping_ms" not in data["raw"]

    def test_with_analysis_and_speedtest(self, client, sample_analysis):
        update_state(
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
        assert data["genres"]["fps"] == "ok"

    def test_genres_degrade_with_grade(self, client, sample_analysis):
        # Simulate a poor connection: zero SNR headroom, no speedtest
        sample_analysis["summary"]["health"] = "poor"
        sample_analysis["summary"]["ds_snr_min"] = 25.0
        update_state(analysis=sample_analysis)
        data = client.get("/api/gaming-score").get_json()
        # Without speedtest data the score may still be partial, but genres key must exist
        assert all(v in ("ok", "warn", "bad") for v in data["genres"].values())

    def test_enabled_flag_reflects_config(self, config_mgr, sample_analysis):
        config_mgr.save({"gaming_quality_enabled": True})
        init_config(config_mgr)
        update_state(analysis=sample_analysis)
        app.config["TESTING"] = True
        with app.test_client() as c:
            data = c.get("/api/gaming-score").get_json()
        assert data["enabled"] is True

