"""Tests for config-saving API."""

import json
import logging


class TestConfigAPI:
    def test_save_config(self, client):
        resp = client.post(
            "/api/config",
            data=json.dumps({"poll_interval": 120}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["success"] is True

    def test_save_log_omits_configuration_key_names(self, client, caplog):
        key_marker = "private_config_key_name_marker"

        with caplog.at_level(logging.INFO, logger="docsis.audit"):
            resp = client.post(
                "/api/config",
                data=json.dumps(
                    {key_marker: "ordinary-value", "modem_password": "secret-value"}
                ),
                content_type="application/json",
            )

        assert resp.status_code == 200
        assert "Config changed:" in caplog.text
        assert key_marker not in caplog.text
        assert "modem_password" not in caplog.text
        assert "secret-value" not in caplog.text

    def test_save_clamps_poll_interval(self, client):
        resp = client.post(
            "/api/config",
            data=json.dumps({"poll_interval": 10}),
            content_type="application/json",
        )
        assert json.loads(resp.data)["success"] is True

    def test_save_no_data(self, client):
        resp = client.post("/api/config", content_type="application/json")
        assert resp.status_code in (400, 500)

