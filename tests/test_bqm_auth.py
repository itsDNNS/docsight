"""Tests for ThinkBroadband auth and CSV download flow."""

from unittest.mock import MagicMock, patch

import pytest

from app.modules.bqm.auth import ThinkBroadbandAuth, ThinkBroadbandBatchAbort


def _response(status=200, text="", content_type="text/csv"):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    resp.headers = {"Content-Type": content_type}
    return resp


class TestThinkBroadbandAuth:
    @patch("app.modules.bqm.auth.requests.Session")
    def test_login_success(self, MockSession):
        session = MockSession.return_value
        session.post.return_value = _response(200, "ok", "text/html")
        client = ThinkBroadbandAuth("user", "pass")
        assert client.login() is True

    @patch("app.modules.bqm.auth.requests.Session")
    def test_download_csv_relogs_once(self, MockSession):
        session = MockSession.return_value
        session.post.return_value = _response(200, "ok", "text/html")
        session.get.side_effect = [
            _response(200, "<html>login</html>", "text/html"),
            _response(200, '"Timestamp",...\n', "text/csv"),
        ]
        client = ThinkBroadbandAuth("user", "pass")
        assert client.download_csv("123", "2026-03-15").startswith('"Timestamp"')
        assert session.post.call_count == 1
        assert session.get.call_count == 2

    @patch("app.modules.bqm.auth.requests.Session")
    def test_download_csv_aborts_on_rate_limit(self, MockSession):
        session = MockSession.return_value
        session.get.return_value = _response(429, "slow down", "text/plain")
        client = ThinkBroadbandAuth("user", "pass")
        with pytest.raises(ThinkBroadbandBatchAbort):
            client.download_csv("123", "2026-03-15")

    @patch("app.modules.bqm.auth.requests.Session")
    def test_validate_monitor_id_uses_current_session(self, MockSession):
        session = MockSession.return_value
        session.get.return_value = _response(200, '"Timestamp",...\n', "text/csv")
        client = ThinkBroadbandAuth("user", "pass")
        assert client.validate_monitor_id("123") is True
