"""Tests for settings and setup pages."""

from app.web import init_config, app
from app.config import ConfigManager

class TestSettingsRoute:
    def test_settings_contains_comcast_xfinity_isp_option(self, client):
        resp = client.get("/settings?lang=en")
        assert resp.status_code == 200
        assert b"Comcast/Xfinity" in resp.data

    def test_settings_modules_lists_builtin_features(self, client):
        resp = client.get("/settings?lang=en")
        assert resp.status_code == 200
        assert b"Built-in Features" in resp.data
        assert b"Gaming Quality Index" in resp.data
        assert b"Segment Utilization" in resp.data
        assert b"Requires FRITZ!OS 8.20 or newer" in resp.data

    def test_settings_connection_includes_segment_toggle_for_fritzbox(self, client):
        resp = client.get("/settings?lang=en")
        assert resp.status_code == 200
        assert b"Collect segment utilization" in resp.data
        assert b'name="segment_utilization_enabled"' in resp.data

    def test_settings_modules_shows_segment_disabled_status(self, client, config_mgr):
        config_mgr.save({"segment_utilization_enabled": False})
        init_config(config_mgr)
        resp = client.get("/settings?lang=en")
        assert resp.status_code == 200
        assert b"Segment Utilization" in resp.data
        assert b"Disabled" in resp.data


class TestSetupRoute:
    def test_setup_redirects_when_configured(self, client):
        resp = client.get("/setup")
        assert resp.status_code == 302
        assert "/" == resp.headers["Location"]

    def test_setup_renders_when_unconfigured(self, tmp_path):
        mgr = ConfigManager(str(tmp_path / "data3"))
        init_config(mgr)
        app.config["TESTING"] = True
        with app.test_client() as c:
            resp = c.get("/setup")
            assert resp.status_code == 200
            assert b"DOCSight" in resp.data


class TestSettingsRender:
    def test_settings_renders(self, client):
        resp = client.get("/settings")
        assert resp.status_code == 200

