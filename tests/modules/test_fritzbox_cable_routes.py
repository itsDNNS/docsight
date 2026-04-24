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


class TestSegmentEventsEndpoint:
    @patch("app.blueprints.segment_bp.require_auth", lambda f: f)
    @patch("app.blueprints.segment_bp.get_config_manager")
    @patch("app.blueprints.segment_bp._get_storage")
    def test_returns_events_payload(self, mock_get_storage, mock_get_config, client):
        mock_cfg = MagicMock()
        mock_cfg.get.return_value = "fritzbox"
        mock_cfg.is_segment_utilization_enabled.return_value = True
        mock_get_config.return_value = mock_cfg

        mock_storage = MagicMock()
        mock_storage.get_events.return_value = [
            {
                "direction": "downstream",
                "start": "2026-03-09T10:01:00Z",
                "end": "2026-03-09T10:03:00Z",
                "duration_minutes": 3,
                "peak_total": 90.0,
                "peak_own": 3.0,
                "peak_neighbor_load": 87.0,
                "confidence": "high",
            }
        ]
        mock_get_storage.return_value = mock_storage

        resp = client.get("/api/fritzbox/segment-utilization/events?range=7d&threshold=80&min_minutes=3")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "events" in data
        assert len(data["events"]) == 1
        ev = data["events"][0]
        assert ev["direction"] == "downstream"
        assert ev["duration_minutes"] == 3
        # Echo back the validated params so the UI can show them.
        assert data.get("threshold") == 80
        assert data.get("min_minutes") == 3

    @patch("app.blueprints.segment_bp.require_auth", lambda f: f)
    @patch("app.blueprints.segment_bp.get_config_manager")
    @patch("app.blueprints.segment_bp._get_storage")
    def test_clamps_invalid_threshold_and_min_minutes(self, mock_get_storage, mock_get_config, client):
        mock_cfg = MagicMock()
        mock_cfg.get.return_value = "fritzbox"
        mock_cfg.is_segment_utilization_enabled.return_value = True
        mock_get_config.return_value = mock_cfg

        mock_storage = MagicMock()
        mock_storage.get_events.return_value = []
        mock_get_storage.return_value = mock_storage

        # Unparseable values fall back to defaults, out-of-range values are clamped.
        resp = client.get("/api/fritzbox/segment-utilization/events?threshold=abc&min_minutes=-5")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["threshold"] == 80  # unparseable -> default
        assert data["min_minutes"] == 1  # -5 clamps to lower bound

        resp = client.get("/api/fritzbox/segment-utilization/events?threshold=500&min_minutes=99999")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["threshold"] == 100
        assert data["min_minutes"] == 1440

    @patch("app.blueprints.segment_bp.require_auth", lambda f: f)
    @patch("app.blueprints.segment_bp.get_config_manager")
    @patch("app.blueprints.segment_bp._get_storage")
    def test_rejects_when_driver_unsupported(self, mock_get_storage, mock_get_config, client):
        mock_cfg = MagicMock()
        mock_cfg.get.return_value = "arris"
        mock_get_config.return_value = mock_cfg
        mock_get_storage.return_value = MagicMock()

        resp = client.get("/api/fritzbox/segment-utilization/events")
        assert resp.status_code == 400

    @patch("app.blueprints.segment_bp.require_auth", lambda f: f)
    @patch("app.blueprints.segment_bp.get_config_manager")
    @patch("app.blueprints.segment_bp._get_storage")
    def test_passes_range_to_storage(self, mock_get_storage, mock_get_config, client):
        mock_cfg = MagicMock()
        mock_cfg.get.return_value = "fritzbox"
        mock_cfg.is_segment_utilization_enabled.return_value = True
        mock_get_config.return_value = mock_cfg

        mock_storage = MagicMock()
        mock_storage.get_events.return_value = []
        mock_get_storage.return_value = mock_storage

        resp = client.get("/api/fritzbox/segment-utilization/events?range=24h&threshold=70&min_minutes=5")
        assert resp.status_code == 200
        mock_storage.get_events.assert_called_once()
        _, kwargs = mock_storage.get_events.call_args
        assert kwargs.get("threshold") == 70
        assert kwargs.get("min_minutes") == 5

    @patch("app.blueprints.segment_bp.require_auth", lambda f: f)
    @patch("app.blueprints.segment_bp.get_config_manager")
    @patch("app.blueprints.segment_bp._get_storage")
    def test_invalid_range_is_normalized_in_echo(self, mock_get_storage, mock_get_config, client):
        """An unrecognized range string must not be echoed verbatim —
        the response reports the default the server actually used."""
        mock_cfg = MagicMock()
        mock_cfg.get.return_value = "fritzbox"
        mock_cfg.is_segment_utilization_enabled.return_value = True
        mock_get_config.return_value = mock_cfg

        mock_storage = MagicMock()
        mock_storage.get_events.return_value = []
        mock_get_storage.return_value = mock_storage

        resp = client.get("/api/fritzbox/segment-utilization/events?range=not-a-range")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["range"] == "7d"


class TestSegmentDataEndpointRange:
    @patch("app.blueprints.segment_bp.require_auth", lambda f: f)
    @patch("app.blueprints.segment_bp.get_config_manager")
    @patch("app.blueprints.segment_bp._get_storage")
    def test_invalid_range_normalizes_to_default(self, mock_get_storage, mock_get_config, client):
        mock_cfg = MagicMock()
        mock_cfg.get.return_value = "fritzbox"
        mock_cfg.is_segment_utilization_enabled.return_value = True
        mock_get_config.return_value = mock_cfg

        mock_storage = MagicMock()
        mock_storage.get_range.return_value = []
        mock_storage.get_latest.return_value = []
        mock_storage.get_stats.return_value = {"count": 0}
        mock_get_storage.return_value = mock_storage

        resp = client.get("/api/fritzbox/segment-utilization?range=bogus")
        # The default (24h) was applied, so the call succeeds and does not
        # echo the invalid input back anywhere in the response.
        assert resp.status_code == 200


class TestSegmentRangeEndpoint:
    @patch("app.blueprints.segment_bp.require_auth", lambda f: f)
    @patch("app.blueprints.segment_bp.get_config_manager")
    @patch("app.blueprints.segment_bp._get_storage")
    def test_range_endpoint_for_correlation(self, mock_get_storage, mock_get_config, client):
        mock_cfg = MagicMock()
        mock_cfg.get.return_value = "fritzbox"
        mock_cfg.is_segment_utilization_enabled.return_value = True
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

    @patch("app.blueprints.segment_bp.require_auth", lambda f: f)
    @patch("app.blueprints.segment_bp.get_config_manager")
    @patch("app.blueprints.segment_bp._get_storage")
    def test_range_endpoint_returns_empty_when_driver_unsupported(
        self, mock_get_storage, mock_get_config, client,
    ):
        """The correlation graph fetches this range endpoint opportunistically.
        When the modem driver isn't fritzbox, the endpoint must return an
        empty list so the correlation view degrades cleanly."""
        mock_cfg = MagicMock()
        mock_cfg.get.return_value = "arris"
        mock_cfg.is_segment_utilization_enabled.return_value = True
        mock_get_config.return_value = mock_cfg
        mock_get_storage.return_value = MagicMock()

        resp = client.get(
            "/api/fritzbox/segment-utilization/range"
            "?start=2026-03-09T00:00:00Z&end=2026-03-09T23:59:59Z"
        )
        assert resp.status_code == 200
        assert resp.get_json() == []

    @patch("app.blueprints.segment_bp.require_auth", lambda f: f)
    @patch("app.blueprints.segment_bp.get_config_manager")
    @patch("app.blueprints.segment_bp._get_storage")
    def test_range_endpoint_returns_empty_when_feature_disabled(
        self, mock_get_storage, mock_get_config, client,
    ):
        mock_cfg = MagicMock()
        mock_cfg.get.return_value = "fritzbox"
        mock_cfg.is_segment_utilization_enabled.return_value = False
        mock_get_config.return_value = mock_cfg
        mock_get_storage.return_value = MagicMock()

        resp = client.get(
            "/api/fritzbox/segment-utilization/range"
            "?start=2026-03-09T00:00:00Z&end=2026-03-09T23:59:59Z"
        )
        assert resp.status_code == 200
        assert resp.get_json() == []
