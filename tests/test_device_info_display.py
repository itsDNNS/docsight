"""Tests for device info display in dashboard and API."""

import json
import pytest

from app.web import app, update_state, init_config, init_storage, format_uptime, _state
from app.config import ConfigManager
from app.storage import SnapshotStorage


_SAMPLE_ANALYSIS = {
    "summary": {
        "ds_total": 33, "us_total": 4,
        "ds_power_min": -1.0, "ds_power_max": 5.0, "ds_power_avg": 2.5,
        "us_power_min": 40.0, "us_power_max": 45.0, "us_power_avg": 42.5,
        "ds_snr_min": 35.0, "ds_snr_avg": 37.0,
        "ds_correctable_errors": 1234, "ds_uncorrectable_errors": 56,
        "health": "good", "health_issues": [],
    },
    "ds_channels": [{"channel_id": 1, "power": 3.0, "snr": 35.0}],
    "us_channels": [{"channel_id": 1, "power": 42.0}],
}


@pytest.fixture
def config_mgr(tmp_path):
    data_dir = str(tmp_path / "data")
    mgr = ConfigManager(data_dir)
    mgr.save({"modem_password": "test", "modem_type": "fritzbox"})
    return mgr


@pytest.fixture
def storage(tmp_path):
    return SnapshotStorage(str(tmp_path / "test.db"), max_days=7)


@pytest.fixture
def client(config_mgr, storage):
    init_config(config_mgr)
    init_storage(storage)
    app.config["TESTING"] = True
    # Seed analysis so the dashboard renders the hero card
    update_state(analysis=_SAMPLE_ANALYSIS)
    with app.test_client() as c:
        yield c


# ── fmt_uptime filter ──


class TestFormatUptime:
    def test_days_hours_minutes(self):
        assert format_uptime(3 * 86400 + 12 * 3600 + 5 * 60) == "3d 12h 5m"

    def test_hours_minutes_only(self):
        assert format_uptime(5 * 3600 + 30 * 60) == "5h 30m"

    def test_minutes_only(self):
        assert format_uptime(42 * 60) == "42m"

    def test_zero_seconds(self):
        assert format_uptime(0) == "0m"

    def test_one_day_exact(self):
        assert format_uptime(86400) == "1d 0h 0m"

    def test_large_uptime(self):
        assert format_uptime(90 * 86400 + 3600) == "90d 1h 0m"

    def test_none_returns_empty(self):
        assert format_uptime(None) == ""

    def test_non_numeric_returns_empty(self):
        assert format_uptime("abc") == ""

    def test_negative_returns_empty(self):
        assert format_uptime(-100) == ""

    def test_seconds_ignored(self):
        # 1 day + 1 hour + 1 minute + 30 seconds = still "1d 1h 1m"
        assert format_uptime(86400 + 3600 + 60 + 30) == "1d 1h 1m"


# ── /api/device endpoint ──


class TestDeviceInfoAPI:
    def test_device_endpoint_returns_full_info(self, client):
        """Device endpoint returns all fields from driver."""
        update_state(device_info={
            "manufacturer": "Compal",
            "model": "CH7465LG",
            "sw_version": "1.2.3",
            "uptime_seconds": 86400,
        })
        resp = client.get("/api/device")
        data = json.loads(resp.data)
        assert data["manufacturer"] == "Compal"
        assert data["model"] == "CH7465LG"
        assert data["sw_version"] == "1.2.3"
        assert data["uptime_seconds"] == 86400

    def test_device_endpoint_partial_info(self, client):
        """Device endpoint returns partial info when driver doesn't provide all fields."""
        update_state(device_info={
            "manufacturer": "Arris",
            "model": "CM8200A",
            "sw_version": "",
        })
        resp = client.get("/api/device")
        data = json.loads(resp.data)
        assert data["model"] == "CM8200A"
        assert data["sw_version"] == ""
        assert "uptime_seconds" not in data

    def test_device_endpoint_no_data(self, client):
        """Device endpoint returns empty dict when no device info."""
        _state["device_info"] = None
        resp = client.get("/api/device")
        data = json.loads(resp.data)
        assert data == {}


# ── Dashboard rendering ──


class TestDeviceInfoDashboard:
    def _render_index(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        return resp.data.decode("utf-8")

    def test_model_badge_rendered(self, client):
        """Model badge appears when device_info has model."""
        update_state(device_info={"model": "CH7465LG", "manufacturer": "Compal"})
        html = self._render_index(client)
        assert "CH7465LG" in html
        assert 'data-lucide="router"' in html

    def test_firmware_badge_rendered(self, client):
        """Firmware badge appears when sw_version is non-empty."""
        update_state(device_info={"model": "TC4400", "sw_version": "2.1.0beta3"})
        html = self._render_index(client)
        assert "2.1.0beta3" in html
        assert 'data-lucide="package"' in html

    def test_uptime_badge_rendered(self, client):
        """Uptime badge appears when uptime_seconds is present."""
        update_state(device_info={"model": "CH7465LG", "uptime_seconds": 259200})
        html = self._render_index(client)
        assert "3d 0h 0m" in html

    def test_no_badges_when_no_device_info(self, client):
        """No device badges when device_info is empty."""
        _state["device_info"] = None
        html = self._render_index(client)
        assert 'data-lucide="router"' not in html

    def test_no_firmware_badge_when_empty(self, client):
        """No firmware badge when sw_version is empty string."""
        update_state(device_info={"model": "Hitron CODA-56", "sw_version": ""})
        html = self._render_index(client)
        assert "Hitron CODA-56" in html
        assert 'data-lucide="package"' not in html

    def test_no_uptime_badge_when_missing(self, client):
        """No uptime badge when uptime_seconds is not in device_info."""
        update_state(device_info={"model": "CM8200A"})
        html = self._render_index(client)
        assert "CM8200A" in html
        # Extract hero-meta section and verify no clock badge
        hero_start = html.find("hero-meta")
        hero_end = html.find("hero-chart-wrap")
        hero_section = html[hero_start:hero_end] if hero_start != -1 else ""
        assert 'data-lucide="clock"' not in hero_section

    def test_zero_uptime_rendered(self, client):
        """Uptime badge shows '0m' when uptime_seconds is 0 (falsy but valid)."""
        update_state(device_info={"model": "DemoRouter", "uptime_seconds": 0})
        html = self._render_index(client)
        assert "0m" in html
