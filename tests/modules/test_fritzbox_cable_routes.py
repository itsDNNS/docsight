"""Tests for fritzbox_cable routes serving stored data."""

from unittest.mock import patch, MagicMock
import pytest


@pytest.fixture
def app():
    from flask import Flask
    from app.blueprints import segment_bp as seg_mod
    seg_mod._storage_instance = None  # reset singleton
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test"
    app.register_blueprint(seg_mod.segment_bp)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


class TestSegmentDataEndpoint:
    @patch("app.blueprints.segment_bp.require_auth", lambda f: f)
    @patch("app.blueprints.segment_bp.get_config_manager")
    @patch("app.blueprints.segment_bp._get_storage")
    def test_returns_stored_data(self, mock_get_storage, mock_get_config, client):
        mock_cfg = MagicMock()
        mock_cfg.get.return_value = "fritzbox"
        mock_cfg.is_demo_mode.return_value = False
        mock_get_config.return_value = mock_cfg

        mock_storage = MagicMock()
        mock_storage.get_range.return_value = [
            {"timestamp": "2026-03-09T14:30:00Z", "ds_total": 6.2, "us_total": 11.4, "ds_own": 0.05, "us_own": 0.17},
        ]
        mock_storage.get_latest.return_value = [
            {"timestamp": "2026-03-09T14:30:00Z", "ds_total": 6.2, "us_total": 11.4, "ds_own": 0.05, "us_own": 0.17},
        ]
        mock_storage.get_stats.return_value = {
            "count": 100, "ds_total_avg": 6.0, "ds_total_min": 2.0, "ds_total_max": 15.0,
            "us_total_avg": 10.0, "us_total_min": 3.0, "us_total_max": 40.0,
        }
        mock_get_storage.return_value = mock_storage

        resp = client.get("/api/fritzbox/segment-utilization?range=24h")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "samples" in data
        assert "latest" in data
        assert "stats" in data


class TestSegmentRangeEndpoint:
    @patch("app.blueprints.segment_bp.require_auth", lambda f: f)
    @patch("app.blueprints.segment_bp.get_config_manager")
    @patch("app.blueprints.segment_bp._get_storage")
    def test_range_endpoint_for_correlation(self, mock_get_storage, mock_get_config, client):
        mock_cfg = MagicMock()
        mock_cfg.get.return_value = "fritzbox"
        mock_cfg.is_demo_mode.return_value = False
        mock_get_config.return_value = mock_cfg

        mock_storage = MagicMock()
        mock_storage.get_range.return_value = [
            {"timestamp": "2026-03-09T14:30:00Z", "ds_total": 6.2, "us_total": 11.4, "ds_own": 0.05, "us_own": 0.17},
        ]
        mock_get_storage.return_value = mock_storage

        resp = client.get("/api/fritzbox/segment-utilization/range?start=2026-03-09T00:00:00Z&end=2026-03-09T23:59:59Z")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]["ds_total"] == pytest.approx(6.2)
