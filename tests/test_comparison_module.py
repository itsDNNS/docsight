"""Tests for the Before/After Comparison module."""

import os
import sys

import pytest
from unittest.mock import patch, MagicMock
from flask import Flask
from app.web import app


@pytest.fixture
def app_client():
    """Create a test client with comparison module blueprint."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


SNAPSHOT_A = {
    "timestamp": "2026-03-01T06:00:00Z",
    "summary": {
        "ds_power_avg": 3.1,
        "ds_snr_avg": 34.2,
        "us_power_avg": 42.1,
        "ds_correctable_errors": 100,
        "ds_uncorrectable_errors": 0,
        "health": "good",
    },
    "ds_channels": [],
    "us_channels": [],
}
SNAPSHOT_B = {
    "timestamp": "2026-03-08T06:00:00Z",
    "summary": {
        "ds_power_avg": 4.2,
        "ds_snr_avg": 31.5,
        "us_power_avg": 42.4,
        "ds_correctable_errors": 200,
        "ds_uncorrectable_errors": 127,
        "health": "marginal",
    },
    "ds_channels": [],
    "us_channels": [],
}

UNSUPPORTED_ERRORS_SNAPSHOT = {
    "timestamp": "2026-03-01T06:00:00Z",
    "summary": {
        "ds_power_avg": 3.1,
        "ds_snr_avg": 34.2,
        "us_power_avg": 42.1,
        "ds_correctable_errors": None,
        "ds_uncorrectable_errors": None,
        "health": "good",
    },
    "ds_channels": [],
    "us_channels": [],
}


class TestCompareEndpoint:
    def test_missing_params_returns_400(self, app_client):
        resp = app_client.get("/api/comparison")
        assert resp.status_code == 400

    def test_partial_params_returns_400(self, app_client):
        resp = app_client.get("/api/comparison?from_a=2026-03-01&to_a=2026-03-01")
        assert resp.status_code == 400

    def test_valid_request_returns_periods_and_delta(self, app_client):
        with patch("app.modules.comparison.routes._get_storage") as mock_storage:
            storage = MagicMock()
            storage.get_range_data.side_effect = [
                [SNAPSHOT_A],
                [SNAPSHOT_B],
            ]
            mock_storage.return_value = storage
            resp = app_client.get(
                "/api/comparison"
                "?from_a=2026-03-01T00:00:00Z&to_a=2026-03-01T23:59:00Z"
                "&from_b=2026-03-08T00:00:00Z&to_b=2026-03-08T23:59:00Z"
            )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "period_a" in data
        assert "period_b" in data
        assert "delta" in data
        assert data["period_a"]["avg"]["ds_power"] == 3.1
        assert data["period_b"]["avg"]["ds_power"] == 4.2
        assert data["delta"]["ds_power"] == pytest.approx(1.1)
        assert data["delta"]["ds_snr"] == pytest.approx(-2.7)

    def test_empty_period_returns_zero_snapshots(self, app_client):
        with patch("app.modules.comparison.routes._get_storage") as mock_storage:
            storage = MagicMock()
            storage.get_range_data.side_effect = [[], [SNAPSHOT_B]]
            mock_storage.return_value = storage
            resp = app_client.get(
                "/api/comparison"
                "?from_a=2026-03-01T00:00:00Z&to_a=2026-03-01T23:59:00Z"
                "&from_b=2026-03-08T00:00:00Z&to_b=2026-03-08T23:59:00Z"
            )
        data = resp.get_json()
        assert data["period_a"]["snapshots"] == 0
        assert data["period_a"]["avg"]["ds_power"] is None

    def test_delta_verdict_degraded(self, app_client):
        """Lower SNR + higher errors = degraded."""
        with patch("app.modules.comparison.routes._get_storage") as mock_storage:
            storage = MagicMock()
            storage.get_range_data.side_effect = [[SNAPSHOT_A], [SNAPSHOT_B]]
            mock_storage.return_value = storage
            resp = app_client.get(
                "/api/comparison"
                "?from_a=2026-03-01T00:00:00Z&to_a=2026-03-01T23:59:00Z"
                "&from_b=2026-03-08T00:00:00Z&to_b=2026-03-08T23:59:00Z"
            )
        data = resp.get_json()
        assert data["delta"]["verdict"] == "degraded"

    def test_delta_verdict_improved(self, app_client):
        """Better SNR, lower errors = improved."""
        better_b = {
            "timestamp": "2026-03-08T06:00:00Z",
            "summary": {
                "ds_power_avg": 3.5,
                "ds_snr_avg": 38.0,
                "us_power_avg": 43.0,
                "ds_correctable_errors": 50,
                "ds_uncorrectable_errors": 0,
                "health": "good",
            },
            "ds_channels": [],
            "us_channels": [],
        }
        with patch("app.modules.comparison.routes._get_storage") as mock_storage:
            storage = MagicMock()
            storage.get_range_data.side_effect = [[SNAPSHOT_A], [better_b]]
            mock_storage.return_value = storage
            resp = app_client.get(
                "/api/comparison"
                "?from_a=2026-03-01T00:00:00Z&to_a=2026-03-01T23:59:00Z"
                "&from_b=2026-03-08T00:00:00Z&to_b=2026-03-08T23:59:00Z"
            )
        data = resp.get_json()
        assert data["delta"]["verdict"] == "improved"

    def test_delta_verdict_unchanged(self, app_client):
        """Same values = unchanged."""
        with patch("app.modules.comparison.routes._get_storage") as mock_storage:
            storage = MagicMock()
            storage.get_range_data.side_effect = [[SNAPSHOT_A], [SNAPSHOT_A]]
            mock_storage.return_value = storage
            resp = app_client.get(
                "/api/comparison"
                "?from_a=2026-03-01T00:00:00Z&to_a=2026-03-01T23:59:00Z"
                "&from_b=2026-03-08T00:00:00Z&to_b=2026-03-08T23:59:00Z"
            )
        data = resp.get_json()
        assert data["delta"]["verdict"] == "unchanged"

    def test_timeseries_included(self, app_client):
        with patch("app.modules.comparison.routes._get_storage") as mock_storage:
            storage = MagicMock()
            storage.get_range_data.side_effect = [[SNAPSHOT_A], [SNAPSHOT_B]]
            mock_storage.return_value = storage
            resp = app_client.get(
                "/api/comparison"
                "?from_a=2026-03-01T00:00:00Z&to_a=2026-03-01T23:59:00Z"
                "&from_b=2026-03-08T00:00:00Z&to_b=2026-03-08T23:59:00Z"
            )
        data = resp.get_json()
        assert len(data["period_a"]["timeseries"]) == 1
        assert data["period_a"]["timeseries"][0]["ds_power_avg"] == 3.1

    def test_health_distribution(self, app_client):
        with patch("app.modules.comparison.routes._get_storage") as mock_storage:
            storage = MagicMock()
            storage.get_range_data.side_effect = [[SNAPSHOT_A, SNAPSHOT_A], [SNAPSHOT_B]]
            mock_storage.return_value = storage
            resp = app_client.get(
                "/api/comparison"
                "?from_a=2026-03-01T00:00:00Z&to_a=2026-03-01T23:59:00Z"
                "&from_b=2026-03-08T00:00:00Z&to_b=2026-03-08T23:59:00Z"
            )
        data = resp.get_json()
        assert data["period_a"]["health_distribution"]["good"] == 2
        assert data["period_a"]["snapshots"] == 2

    def test_period_from_to_echoed(self, app_client):
        with patch("app.modules.comparison.routes._get_storage") as mock_storage:
            storage = MagicMock()
            storage.get_range_data.side_effect = [[], []]
            mock_storage.return_value = storage
            resp = app_client.get(
                "/api/comparison"
                "?from_a=2026-03-01T00:00:00Z&to_a=2026-03-01T23:59:00Z"
                "&from_b=2026-03-08T00:00:00Z&to_b=2026-03-08T23:59:00Z"
            )
        data = resp.get_json()
        assert data["period_a"]["from"] == "2026-03-01T00:00:00Z"
        assert data["period_b"]["to"] == "2026-03-08T23:59:00Z"


class TestAggregatePeriod:
    """Unit tests for the _aggregate_period function."""

    def test_empty_snapshots(self):
        from app.modules.comparison.routes import _aggregate_period

        result = _aggregate_period([])
        assert result["snapshots"] == 0
        assert result["avg"]["ds_power"] is None
        assert result["total"]["uncorr_errors"] == 0

    def test_single_snapshot(self):
        from app.modules.comparison.routes import _aggregate_period

        result = _aggregate_period([SNAPSHOT_A])
        assert result["snapshots"] == 1
        assert result["avg"]["ds_power"] == 3.1
        assert result["avg"]["ds_snr"] == 34.2
        assert result["total"]["corr_errors"] == 100
        assert result["total"]["uncorr_errors"] == 0

    def test_multiple_snapshots_averages(self):
        from app.modules.comparison.routes import _aggregate_period

        result = _aggregate_period([SNAPSHOT_A, SNAPSHOT_B])
        assert result["snapshots"] == 2
        assert result["avg"]["ds_power"] == pytest.approx(3.65)
        assert result["avg"]["ds_snr"] == pytest.approx(32.85)
        assert result["total"]["corr_errors"] == 300

    def test_unsupported_error_counters_remain_none(self):
        from app.modules.comparison.routes import _aggregate_period

        result = _aggregate_period([UNSUPPORTED_ERRORS_SNAPSHOT])

        assert result["errors_supported"] is False
        assert result["corr_errors_supported"] is False
        assert result["uncorr_errors_supported"] is False
        assert result["total"]["corr_errors"] is None
        assert result["total"]["uncorr_errors"] is None
        assert result["timeseries"][0]["uncorr_errors"] is None

    def test_zero_error_counters_stay_supported_zeroes(self):
        from app.modules.comparison.routes import _aggregate_period

        result = _aggregate_period([SNAPSHOT_A])

        assert result["errors_supported"] is True
        assert result["corr_errors_supported"] is True
        assert result["uncorr_errors_supported"] is True
        assert result["total"]["corr_errors"] == 100
        assert result["total"]["uncorr_errors"] == 0

    def test_partially_supported_error_counters_do_not_invent_zeroes(self):
        from app.modules.comparison.routes import _aggregate_period

        partial = {
            **UNSUPPORTED_ERRORS_SNAPSHOT,
            "summary": {
                **UNSUPPORTED_ERRORS_SNAPSHOT["summary"],
                "ds_correctable_errors": 5,
                "ds_uncorrectable_errors": None,
            },
        }
        result = _aggregate_period([partial])

        assert result["errors_supported"] is True
        assert result["corr_errors_supported"] is True
        assert result["uncorr_errors_supported"] is False
        assert result["total"]["corr_errors"] == 5
        assert result["total"]["uncorr_errors"] is None
        assert result["timeseries"][0]["uncorr_errors"] is None

    def test_compare_periods_helper(self):
        from app.modules.comparison.routes import compare_periods

        storage = MagicMock()
        storage.get_range_data.side_effect = [[SNAPSHOT_A], [SNAPSHOT_B]]

        result = compare_periods(
            storage,
            "2026-03-01T00:00:00Z",
            "2026-03-01T23:59:00Z",
            "2026-03-08T00:00:00Z",
            "2026-03-08T23:59:00Z",
        )

        assert result["period_a"]["avg"]["ds_power"] == 3.1
        assert result["period_b"]["health_distribution"]["marginal"] == 1
        assert result["delta"]["verdict"] == "degraded"
        assert result["period_b"]["total"]["uncorr_errors"] == 127


class TestComputeDelta:
    """Unit tests for the _compute_delta function."""

    def test_basic_delta(self):
        from app.modules.comparison.routes import _aggregate_period, _compute_delta

        pa = _aggregate_period([SNAPSHOT_A])
        pb = _aggregate_period([SNAPSHOT_B])
        delta = _compute_delta(pa, pb)
        assert delta["ds_power"] == pytest.approx(1.1)
        assert delta["ds_snr"] == pytest.approx(-2.7)
        assert delta["us_power"] == pytest.approx(0.3)
        assert delta["uncorr_errors"] == 127

    def test_delta_with_empty_period(self):
        from app.modules.comparison.routes import _aggregate_period, _compute_delta

        pa = _aggregate_period([])
        pb = _aggregate_period([SNAPSHOT_B])
        delta = _compute_delta(pa, pb)
        assert delta["ds_power"] is None
        assert delta["ds_snr"] is None

    def test_both_periods_empty(self):
        from app.modules.comparison.routes import _aggregate_period, _compute_delta

        pa = _aggregate_period([])
        pb = _aggregate_period([])
        delta = _compute_delta(pa, pb)
        assert delta["ds_power"] is None
        assert delta["uncorr_errors"] == 0
        assert delta["verdict"] == "unchanged"

    def test_delta_ignores_unsupported_error_counters(self):
        from app.modules.comparison.routes import _aggregate_period, _compute_delta

        unsupported_a = _aggregate_period([UNSUPPORTED_ERRORS_SNAPSHOT])
        unsupported_b = _aggregate_period([
            {**UNSUPPORTED_ERRORS_SNAPSHOT, "timestamp": "2026-03-08T06:00:00Z"}
        ])

        delta = _compute_delta(unsupported_a, unsupported_b)

        assert delta["uncorr_errors"] is None
        assert delta["verdict"] == "unchanged"

    def test_extreme_snr_improvement(self):
        """Large SNR jump should be classified as improved."""
        from app.modules.comparison.routes import _aggregate_period, _compute_delta

        great = {
            "timestamp": "2026-03-08T06:00:00Z",
            "summary": {
                "ds_power_avg": 3.0,
                "ds_snr_avg": 40.0,
                "us_power_avg": 42.0,
                "ds_correctable_errors": 0,
                "ds_uncorrectable_errors": 0,
                "health": "good",
            },
            "ds_channels": [],
            "us_channels": [],
        }
        pa = _aggregate_period([SNAPSHOT_A])
        pb = _aggregate_period([great])
        delta = _compute_delta(pa, pb)
        assert delta["verdict"] == "improved"


class TestModuleDiscovery:
    """Integration: comparison module loads correctly via module loader."""

    def setup_method(self):
        from app.i18n import _TRANSLATIONS

        self._orig_translations = {k: dict(v) for k, v in _TRANSLATIONS.items()}
        self._orig_sys_modules = {
            k: v for k, v in sys.modules.items()
            if k.startswith("app.modules.")
        }

    def teardown_method(self):
        from app.i18n import _TRANSLATIONS
        from app import web

        _TRANSLATIONS.clear()
        _TRANSLATIONS.update(self._orig_translations)
        # Restore original module objects (load_all re-imports them as new objects,
        # which breaks unittest.mock.patch targets for later tests)
        for key in list(sys.modules.keys()):
            if key.startswith("app.modules."):
                if key in self._orig_sys_modules:
                    sys.modules[key] = self._orig_sys_modules[key]
                else:
                    del sys.modules[key]
        web.init_modules(None)

    def test_comparison_module_discovered(self):
        from app.module_loader import discover_modules

        modules_dir = os.path.join(os.path.dirname(__file__), "..", "app", "modules")
        mods = discover_modules([modules_dir])
        ids = [m.id for m in mods]
        assert "docsight.comparison" in ids

    def test_comparison_module_has_correct_type(self):
        from app.module_loader import discover_modules

        modules_dir = os.path.join(os.path.dirname(__file__), "..", "app", "modules")
        mods = discover_modules([modules_dir])
        mod = next(m for m in mods if m.id == "docsight.comparison")
        assert mod.type == "analysis"

    def test_comparison_module_loads_i18n(self):
        from app.module_loader import ModuleLoader

        modules_dir = os.path.join(os.path.dirname(__file__), "..", "app", "modules")
        test_app = Flask(__name__)
        loader = ModuleLoader(test_app, search_paths=[modules_dir])
        loader.load_all()

        from app.i18n import get_translations

        en = get_translations("en")
        assert en.get("docsight.comparison.title") == "Before/After Comparison"

        de = get_translations("de")
        assert de.get("docsight.comparison.title") == "Vorher/Nachher-Vergleich"

    def test_comparison_manifest_valid(self):
        import json

        manifest_path = os.path.join(
            os.path.dirname(__file__), "..", "app", "modules", "comparison", "manifest.json"
        )
        with open(manifest_path) as f:
            manifest = json.load(f)

        assert manifest["id"] == "docsight.comparison"
        assert "routes" in manifest["contributes"]
        assert "tab" in manifest["contributes"]
        assert "i18n" in manifest["contributes"]
        assert manifest["menu"]["label_key"] == "docsight.comparison.title"
