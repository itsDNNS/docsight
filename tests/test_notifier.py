"""Tests for the notification system."""

import time
import pytest
from unittest.mock import MagicMock, patch, call

from app.notifier import Notifier, build_health_notification, build_digest


@pytest.fixture
def mock_config():
    """ConfigManager mock with no channels configured."""
    mgr = MagicMock()
    mgr.get.return_value = ""
    return mgr


@pytest.fixture
def notifier(mock_config):
    return Notifier(mock_config)


def _config_with(**overrides):
    """Build a mock ConfigManager that returns overrides for matching keys."""
    mgr = MagicMock()
    def _get(key, default=""):
        return overrides.get(key, default)
    mgr.get.side_effect = _get
    return mgr


# ── is_configured ──

class TestIsConfigured:
    def test_not_configured_by_default(self, notifier):
        assert notifier.is_configured() is False

    def test_configured_webhook(self):
        n = Notifier(_config_with(notify_webhook_url="http://example.com/hook"))
        assert n.is_configured() is True

    def test_configured_telegram(self):
        n = Notifier(_config_with(
            notify_telegram_token="123:ABC",
            notify_telegram_chat_id="456",
        ))
        assert n.is_configured() is True

    def test_telegram_incomplete(self):
        """Only token without chat_id is not sufficient."""
        n = Notifier(_config_with(notify_telegram_token="123:ABC"))
        assert n.is_configured() is False

    def test_configured_discord(self):
        n = Notifier(_config_with(notify_discord_webhook_url="https://discord.com/api/webhooks/x/y"))
        assert n.is_configured() is True

    def test_configured_email(self):
        n = Notifier(_config_with(notify_email_smtp_host="smtp.example.com"))
        assert n.is_configured() is True

    def test_configured_gotify(self):
        n = Notifier(_config_with(notify_gotify_url="http://gotify.local"))
        assert n.is_configured() is True

    def test_configured_ntfy(self):
        n = Notifier(_config_with(notify_ntfy_url="https://ntfy.sh/docsight"))
        assert n.is_configured() is True


# ── Cooldown ──

class TestCooldown:
    def test_no_dedup_key_sends_always(self, notifier):
        """Without dedup_key, no cooldown is applied."""
        assert notifier._in_cooldown("key1") is False
        assert notifier._in_cooldown("key1") is True  # 2nd call within window

    def test_different_keys_independent(self, notifier):
        assert notifier._in_cooldown("a") is False
        assert notifier._in_cooldown("b") is False

    def test_cooldown_expires(self, notifier):
        notifier._cooldown_seconds = 0  # instant expiry
        assert notifier._in_cooldown("x") is False
        assert notifier._in_cooldown("x") is False  # already expired


# ── Send routing ──

class TestSendRouting:
    @patch("app.notifier.requests.post")
    def test_webhook_called(self, mock_post):
        n = Notifier(_config_with(notify_webhook_url="http://example.com/hook"))
        mock_post.return_value = MagicMock(status_code=200)
        mock_post.return_value.raise_for_status = MagicMock()

        n.send("Test Title", "Test Message", "warning")
        mock_post.assert_called_once()
        payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
        assert payload["title"] == "Test Title"
        assert payload["source"] == "docsight"

    @patch("app.notifier.requests.post")
    def test_telegram_called(self, mock_post):
        n = Notifier(_config_with(
            notify_telegram_token="123:ABC",
            notify_telegram_chat_id="456",
        ))
        mock_post.return_value = MagicMock(status_code=200)
        mock_post.return_value.raise_for_status = MagicMock()

        n.send("Alert", "Body", "critical")
        mock_post.assert_called_once()
        url = mock_post.call_args[0][0] if mock_post.call_args[0] else mock_post.call_args.kwargs.get("url", "")
        assert "api.telegram.org" in url

    @patch("app.notifier.requests.post")
    def test_discord_embed(self, mock_post):
        n = Notifier(_config_with(notify_discord_webhook_url="https://discord.com/hook"))
        mock_post.return_value = MagicMock(status_code=200)
        mock_post.return_value.raise_for_status = MagicMock()

        n.send("Title", "Msg", "info")
        payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
        assert "embeds" in payload
        assert payload["embeds"][0]["title"] == "Title"

    @patch("app.notifier.requests.post")
    def test_gotify_priority(self, mock_post):
        n = Notifier(_config_with(
            notify_gotify_url="http://gotify.local",
            notify_gotify_token="tok",
        ))
        mock_post.return_value = MagicMock(status_code=200)
        mock_post.return_value.raise_for_status = MagicMock()

        n.send("Title", "Msg", "critical")
        payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
        assert payload["priority"] == 8  # critical → 8

    @patch("app.notifier.requests.post")
    def test_ntfy_headers(self, mock_post):
        n = Notifier(_config_with(
            notify_ntfy_url="https://ntfy.sh/docsight",
            notify_ntfy_token="tok",
        ))
        mock_post.return_value = MagicMock(status_code=200)
        mock_post.return_value.raise_for_status = MagicMock()

        n.send("Title", "Body", "warning")
        headers = mock_post.call_args.kwargs.get("headers") or mock_post.call_args[1].get("headers")
        assert headers["Title"] == "Title"
        assert headers["Priority"] == "high"
        assert "Bearer" in headers["Authorization"]

    def test_send_no_channels_configured(self, notifier):
        """Should not raise if nothing is configured."""
        notifier.send("X", "Y")  # no-op

    @patch("app.notifier.requests.post")
    def test_send_dedup_suppresses_second(self, mock_post):
        n = Notifier(_config_with(notify_webhook_url="http://example.com"))
        mock_post.return_value = MagicMock(status_code=200)
        mock_post.return_value.raise_for_status = MagicMock()

        n.send("A", "B", dedup_key="dup1")
        n.send("A", "B", dedup_key="dup1")
        assert mock_post.call_count == 1

    @patch("app.notifier.requests.post")
    def test_backend_error_logged_not_raised(self, mock_post):
        """Backend errors should be caught and logged."""
        n = Notifier(_config_with(notify_webhook_url="http://example.com"))
        mock_post.side_effect = ConnectionError("fail")
        # Should not raise
        n.send("A", "B")


# ── Email backend ──

class TestEmailBackend:
    @patch("app.notifier.smtplib.SMTP")
    def test_email_sent(self, mock_smtp_class):
        mock_server = MagicMock()
        mock_smtp_class.return_value = mock_server

        n = Notifier(_config_with(
            notify_email_smtp_host="smtp.test.com",
            notify_email_smtp_port="587",
            notify_email_smtp_user="user@test.com",
            notify_email_smtp_password="pass",
            notify_email_from="noreply@test.com",
            notify_email_to="admin@test.com",
            notify_email_tls="true",
        ))
        n.send("Subject", "Body", "info")

        mock_smtp_class.assert_called_once_with("smtp.test.com", 587, timeout=10)
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("user@test.com", "pass")
        mock_server.send_message.assert_called_once()
        mock_server.quit.assert_called_once()


# ── build_health_notification ──

class TestBuildHealthNotification:
    def test_good_health_returns_none(self):
        analysis = {"summary": {"health": "good", "health_issues": []}}
        assert build_health_notification(analysis) is None

    def test_poor_health_returns_critical(self):
        analysis = {
            "summary": {
                "health": "poor",
                "health_issues": ["ds_power_critical", "snr_critical"],
                "ds_power_min": -2,
                "ds_power_max": 12,
                "ds_snr_min": 22,
            }
        }
        title, message, level = build_health_notification(analysis)
        assert "POOR" in title
        assert level == "critical"
        assert "DS Power" in message

    def test_marginal_health_warning(self):
        analysis = {
            "summary": {
                "health": "marginal",
                "health_issues": ["us_power_warn"],
                "us_power_max": 52,
            }
        }
        title, message, level = build_health_notification(analysis)
        assert level == "warning"
        assert "US Power" in message

    def test_no_issues_returns_none(self):
        analysis = {"summary": {"health": "marginal", "health_issues": []}}
        assert build_health_notification(analysis) is None


# ── build_digest ──

class TestBuildDigest:
    def test_basic_digest(self):
        analysis = {
            "summary": {
                "health": "good",
                "ds_total": 33,
                "us_total": 4,
                "ds_power_min": -1,
                "ds_power_max": 5,
                "ds_power_avg": 2.5,
                "ds_snr_min": 35,
                "ds_snr_avg": 37,
                "ds_correctable_errors": 1234,
                "ds_uncorrectable_errors": 56,
                "us_power_min": 40,
                "us_power_max": 45,
                "us_power_avg": 42.5,
            },
        }
        subject, body = build_digest(analysis)
        assert "DOCSight" in subject
        assert "GOOD" in body
        assert "33" in body

    def test_digest_with_watchdog_events(self):
        analysis = {"summary": {"health": "poor", "ds_total": 10, "us_total": 2,
                                "ds_power_min": 0, "ds_power_max": 5, "ds_power_avg": 3,
                                "ds_snr_min": 30, "ds_snr_avg": 33,
                                "ds_correctable_errors": 0, "ds_uncorrectable_errors": 0,
                                "us_power_min": 40, "us_power_max": 44, "us_power_avg": 42}}
        events = [{"type": "modulation_drop", "message": "CH3 dropped"}]
        subject, body = build_digest(analysis, watchdog_events=events)
        assert "Watchdog" in body

    def test_digest_with_ping_stats(self):
        analysis = {"summary": {"health": "good", "ds_total": 10, "us_total": 2,
                                "ds_power_min": 0, "ds_power_max": 5, "ds_power_avg": 3,
                                "ds_snr_min": 30, "ds_snr_avg": 33,
                                "ds_correctable_errors": 0, "ds_uncorrectable_errors": 0,
                                "us_power_min": 40, "us_power_max": 44, "us_power_avg": 42}}
        ping = {"avg_ms": 12.3, "loss_pct": 0.1}
        subject, body = build_digest(analysis, ping_stats=ping)
        assert "12.3" in body
        assert "0.1" in body
