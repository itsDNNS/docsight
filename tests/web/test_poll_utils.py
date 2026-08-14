"""Tests for poll endpoint and small web utility helpers."""

import json

from app.web import format_k
from app.runtime import get_runtime
from app.config import ConfigManager

class TestPollEndpoint:
    def test_poll_not_configured(self, tmp_path, make_app):
        mgr = ConfigManager(str(tmp_path / "data_poll"))
        app = make_app(config_manager=mgr)
        with app.test_client() as c:
            resp = c.post("/api/poll")
            # Unconfigured -> redirects to setup on GET, but POST /api/poll
            # should still be accessible (no auth required when no password)
            assert resp.status_code in (302, 500)

    def test_poll_rate_limit(self, client, sample_analysis):
        from unittest.mock import MagicMock
        mock_collector = MagicMock()
        runtime = get_runtime(client.application)
        runtime.modem_collector = mock_collector
        runtime.set_last_manual_poll(__import__('time').time())
        resp = client.post("/api/poll")
        assert resp.status_code == 429
        data = json.loads(resp.data)
        assert data["success"] is False


class TestFormatK:
    def test_required_contract_cases(self):
        cases = [
            ("1200000 formats to one-decimal millions", 1_200_000, "1.2M"),
            ("132007 formats to whole thousands", 132_007, "132k"),
            ("5929 keeps one decimal in thousands", 5_929, "5.9k"),
            ("3000 trims trailing decimal", 3_000, "3k"),
            ("42 stays unchanged", 42, "42"),
            ("non-numeric values pass through", "bad", "bad"),
        ]

        for label, value, expected in cases:
            assert format_k(value) == expected, label
