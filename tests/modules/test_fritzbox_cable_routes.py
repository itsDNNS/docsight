"""Tests for fritzbox_cable routes serving stored data."""

import sqlite3
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
import pytest
from tests.conftest import OPEN_INSTANCE_ENVIRON


@pytest.fixture
def app(tmp_path):
    from app.app_factory import create_app
    from app.config import ConfigManager
    return create_app(
        config_manager=ConfigManager(str(tmp_path / "segment-config")),
        environ=dict(OPEN_INSTANCE_ENVIRON), testing=True,
    )


@pytest.fixture
def client(app):
    return app.test_client()


SUMMARY = "/api/fritzbox/segment-utilization"
EVENTS = "/api/fritzbox/segment-utilization/events"


@pytest.fixture
def serve(monkeypatch, client):
    """GET a segment view with the given modem type, feature switch and storage."""
    monkeypatch.setattr("app.blueprints.segment_bp.utc_cutoff", lambda hours: f"cutoff-{hours}h")
    monkeypatch.setattr("app.blueprints.segment_bp.utc_now", lambda: "now")

    def get(path, storage, modem_type="fritzbox", enabled=True):
        config_manager = SimpleNamespace(
            get=lambda key: modem_type, is_segment_utilization_enabled=lambda: enabled,
        )
        monkeypatch.setattr("app.blueprints.segment_bp.current_runtime",
                            lambda: SimpleNamespace(config_manager=config_manager))
        monkeypatch.setattr("app.blueprints.segment_bp._get_storage", lambda: storage)
        return client.get(path)

    return get


def _broken_storage():
    storage = MagicMock()
    storage.get_range.side_effect = storage.get_events.side_effect = sqlite3.OperationalError("database is locked")
    return storage


@pytest.mark.parametrize("path", [SUMMARY, EVENTS])
@pytest.mark.parametrize(("storage", "kwargs", "status", "error"), [
    (MagicMock, {"modem_type": "arris"}, 400, "This view is only available for FRITZ!Box cable devices."),
    (MagicMock, {"enabled": False}, 400, "Segment utilization is disabled in Settings."),
    (lambda: None, {}, 503, "Storage unavailable"),
    (_broken_storage, {}, 503, "Reading stored data failed. See the DOCSight log for details."),
], ids=["unsupported-driver", "disabled", "no-storage", "storage-error"])
def test_segment_views_refuse_when_unavailable(serve, path, storage, kwargs, status, error):
    resp = serve(path, storage(), **kwargs)
    assert (resp.status_code, resp.get_json(), resp.content_type) == (status, {"error": error}, "application/json")


_NO_SAMPLES = {"samples": [], "latest": [], "stats": {}}


def _no_events(range_key):
    return {"events": [], "threshold": 80, "min_minutes": 3, "range": range_key}


@pytest.mark.parametrize(("path", "start", "method", "body"), [
    (f"{SUMMARY}?range=7d", "cutoff-168h", "get_stats", _NO_SAMPLES),
    (f"{SUMMARY}?range=bogus", "cutoff-24h", "get_stats", _NO_SAMPLES),
    (f"{SUMMARY}?range=all", "2000-01-01T00:00:00Z", "get_range", _NO_SAMPLES),
    (f"{EVENTS}?range=24h", "cutoff-24h", "get_events", _no_events("24h")),
    (f"{EVENTS}?range=bogus", "cutoff-168h", "get_events", _no_events("7d")),
    (f"{EVENTS}?range=all", "2000-01-01T00:00:00Z", "get_events", _no_events("all")),
])
def test_segment_views_read_the_requested_window(serve, path, start, method, body):
    storage = MagicMock()
    storage.get_range.return_value = storage.get_latest.return_value = storage.get_events.return_value = []
    storage.get_stats.return_value = {}
    resp = serve(path, storage)
    assert (resp.status_code, resp.get_json(), resp.content_type) == (200, body, "application/json")
    assert getattr(storage, method).call_args.args[:2] == (start, "now")


class TestSegmentDataEndpoint:
    @patch("app.blueprints.segment_bp.require_auth", lambda f: f)
    @patch("app.blueprints.segment_bp.current_runtime")
    @patch("app.blueprints.segment_bp._get_storage")
    def test_returns_stored_data(self, mock_get_storage, mock_runtime, client):
        mock_cfg = MagicMock()
        mock_cfg.get.return_value = "fritzbox"
        mock_cfg.is_demo_mode.return_value = False
        mock_runtime.return_value.config_manager = mock_cfg

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
    @patch("app.blueprints.segment_bp.current_runtime")
    @patch("app.blueprints.segment_bp._get_storage")
    def test_returns_events_payload(self, mock_get_storage, mock_runtime, client):
        mock_cfg = MagicMock()
        mock_cfg.get.return_value = "fritzbox"
        mock_cfg.is_segment_utilization_enabled.return_value = True
        mock_runtime.return_value.config_manager = mock_cfg

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
    @patch("app.blueprints.segment_bp.current_runtime")
    @patch("app.blueprints.segment_bp._get_storage")
    def test_clamps_invalid_threshold_and_min_minutes(self, mock_get_storage, mock_runtime, client):
        mock_cfg = MagicMock()
        mock_cfg.get.return_value = "fritzbox"
        mock_cfg.is_segment_utilization_enabled.return_value = True
        mock_runtime.return_value.config_manager = mock_cfg

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
    @patch("app.blueprints.segment_bp.current_runtime")
    @patch("app.blueprints.segment_bp._get_storage")
    def test_passes_range_to_storage(self, mock_get_storage, mock_runtime, client):
        mock_cfg = MagicMock()
        mock_cfg.get.return_value = "fritzbox"
        mock_cfg.is_segment_utilization_enabled.return_value = True
        mock_runtime.return_value.config_manager = mock_cfg

        mock_storage = MagicMock()
        mock_storage.get_events.return_value = []
        mock_get_storage.return_value = mock_storage

        resp = client.get("/api/fritzbox/segment-utilization/events?range=24h&threshold=70&min_minutes=5")
        assert resp.status_code == 200
        mock_storage.get_events.assert_called_once()
        _, kwargs = mock_storage.get_events.call_args
        assert kwargs.get("threshold") == 70
        assert kwargs.get("min_minutes") == 5

class TestSegmentRangeEndpoint:
    @patch("app.blueprints.segment_bp.require_auth", lambda f: f)
    @patch("app.blueprints.segment_bp.current_runtime")
    @patch("app.blueprints.segment_bp._get_storage")
    def test_range_endpoint_for_correlation(self, mock_get_storage, mock_runtime, client):
        mock_cfg = MagicMock()
        mock_cfg.get.return_value = "fritzbox"
        mock_cfg.is_segment_utilization_enabled.return_value = True
        mock_runtime.return_value.config_manager = mock_cfg

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
    @patch("app.blueprints.segment_bp.current_runtime")
    @patch("app.blueprints.segment_bp._get_storage")
    def test_range_endpoint_returns_empty_when_driver_unsupported(
        self, mock_get_storage, mock_runtime, client,
    ):
        """The correlation graph fetches this range endpoint opportunistically.
        When the modem driver isn't fritzbox, the endpoint must return an
        empty list so the correlation view degrades cleanly."""
        mock_cfg = MagicMock()
        mock_cfg.get.return_value = "arris"
        mock_cfg.is_segment_utilization_enabled.return_value = True
        mock_runtime.return_value.config_manager = mock_cfg
        mock_get_storage.return_value = MagicMock()

        resp = client.get(
            "/api/fritzbox/segment-utilization/range"
            "?start=2026-03-09T00:00:00Z&end=2026-03-09T23:59:59Z"
        )
        assert resp.status_code == 200
        assert resp.get_json() == []

    @patch("app.blueprints.segment_bp.require_auth", lambda f: f)
    @patch("app.blueprints.segment_bp.current_runtime")
    @patch("app.blueprints.segment_bp._get_storage")
    def test_range_endpoint_returns_empty_when_feature_disabled(
        self, mock_get_storage, mock_runtime, client,
    ):
        mock_cfg = MagicMock()
        mock_cfg.get.return_value = "fritzbox"
        mock_cfg.is_segment_utilization_enabled.return_value = False
        mock_runtime.return_value.config_manager = mock_cfg
        mock_get_storage.return_value = MagicMock()

        resp = client.get(
            "/api/fritzbox/segment-utilization/range"
            "?start=2026-03-09T00:00:00Z&end=2026-03-09T23:59:59Z"
        )
        assert resp.status_code == 200
        assert resp.get_json() == []
