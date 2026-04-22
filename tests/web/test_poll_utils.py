"""Tests for poll endpoint and small web utility helpers."""

import json
from app.web import format_k, init_config, app
from app.config import ConfigManager

class TestPollEndpoint:
    def test_poll_not_configured(self, tmp_path):
        from app.web import _state
        mgr = ConfigManager(str(tmp_path / "data_poll"))
        init_config(mgr)
        app.config["TESTING"] = True
        with app.test_client() as c:
            resp = c.post("/api/poll")
            # Unconfigured -> redirects to setup on GET, but POST /api/poll
            # should still be accessible (no auth required when no password)
            assert resp.status_code in (302, 500)

    def test_poll_rate_limit(self, client, sample_analysis):
        import app.web as web_module
        from unittest.mock import MagicMock
        mock_collector = MagicMock()
        web_module._modem_collector = mock_collector
        web_module._last_manual_poll = __import__('time').time()
        resp = client.post("/api/poll")
        assert resp.status_code == 429
        data = json.loads(resp.data)
        assert data["success"] is False
        # Reset for other tests
        web_module._last_manual_poll = 0.0
        web_module._modem_collector = None


class TestFormatK:
    def test_large_number(self):
        from app.web import format_k
        assert format_k(132007) == "132k"

    def test_medium_number(self):
        from app.web import format_k
        assert format_k(5929) == "5.9k"

    def test_round_thousand(self):
        from app.web import format_k
        assert format_k(3000) == "3k"

    def test_small_number(self):
        from app.web import format_k
        assert format_k(42) == "42"

    def test_invalid(self):
        from app.web import format_k
        assert format_k("bad") == "bad"

