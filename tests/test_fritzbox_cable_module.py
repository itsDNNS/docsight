"""Tests for the FRITZ!Box cable utilization module route."""

from unittest.mock import patch

from app.config import ConfigManager
from app.modules.fritzbox_cable.routes import bp
from app.web import app, init_config, init_storage


class TestFritzBoxCableUtilizationRoute:
    @classmethod
    def setup_class(cls):
        routes = {rule.rule for rule in app.url_map.iter_rules()}
        if "/api/fritzbox/cable-utilization" not in routes:
            app.register_blueprint(bp)

    def test_requires_fritzbox_driver(self, tmp_path):
        mgr = ConfigManager(str(tmp_path / "data"))
        mgr.save({"modem_password": "test", "modem_type": "cm8200"})
        init_config(mgr)
        init_storage(None)
        app.config["TESTING"] = True

        with app.test_client() as client:
            resp = client.get("/api/fritzbox/cable-utilization")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["supported"] is False

    @patch("app.modules.fritzbox_cable.routes.fb.get_cable_utilization")
    @patch("app.modules.fritzbox_cable.routes.fb.login")
    def test_returns_live_payload_for_fritzbox(self, mock_login, mock_get, tmp_path):
        mgr = ConfigManager(str(tmp_path / "data_fb"))
        mgr.save({
            "modem_password": "secret",
            "modem_type": "fritzbox",
            "modem_url": "http://fritz.box",
            "modem_user": "admin",
        })
        init_config(mgr)
        init_storage(None)
        app.config["TESTING"] = True

        mock_login.return_value = "sid123"
        mock_get.return_value = {"supported": True, "model": "FRITZ!Box 6690 Cable"}

        with app.test_client() as client:
            resp = client.get("/api/fritzbox/cable-utilization")

        assert resp.status_code == 200
        assert resp.get_json()["model"] == "FRITZ!Box 6690 Cable"
        mock_login.assert_called_once_with("http://fritz.box", "admin", "secret")
        mock_get.assert_called_once_with("http://fritz.box", "sid123")

    @patch("app.modules.fritzbox_cable.routes.fb.login")
    def test_returns_502_when_fetch_fails(self, mock_login, tmp_path):
        mgr = ConfigManager(str(tmp_path / "data_err"))
        mgr.save({
            "modem_password": "secret",
            "modem_type": "fritzbox",
            "modem_url": "http://fritz.box",
            "modem_user": "admin",
        })
        init_config(mgr)
        init_storage(None)
        app.config["TESTING"] = True

        mock_login.side_effect = RuntimeError("boom")

        with app.test_client() as client:
            resp = client.get("/api/fritzbox/cable-utilization")

        assert resp.status_code == 502
        assert resp.get_json()["supported"] is False
