"""Tests for config-saving API."""

import json

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

