"""Tests for the notification dispatcher and webhook channels."""

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from app.notifier import (
    DISCORD_SEVERITY_COLORS,
    DiscordWebhookChannel,
    NotificationDispatcher,
    WebhookChannel,
    is_discord_webhook_url,
)


# ---------------------------------------------------------------------------
# is_discord_webhook_url
# ---------------------------------------------------------------------------

class TestIsDiscordWebhookUrl:
    @pytest.mark.parametrize("url", [
        "https://discord.com/api/webhooks/123456/abcdef",
        "https://discordapp.com/api/webhooks/123456/abcdef",
        "https://ptb.discord.com/api/webhooks/123456/abcdef",
        "https://canary.discord.com/api/webhooks/123456/abcdef",
        "HTTPS://discord.com/api/webhooks/123456/abcdef",
        "https://discord.com/api/webhooks/123456/abcdef?wait=true",
        "https://discord.com/api/webhooks/123456/abcdef?thread_id=999",
        "https://discord.com/api/webhooks/123456/abcdef?wait=true&thread_id=999",
        "https://discord.com/api/v10/webhooks/123456/abcdef",
        "https://discord.com/api/v10/webhooks/123456/abcdef?wait=true",
    ])
    def test_discord_urls_detected(self, url):
        assert is_discord_webhook_url(url) is True

    @pytest.mark.parametrize("url", [
        "https://ntfy.sh/docsight",
        "https://hooks.slack.com/services/T00/B00/xxx",
        "https://example.com/webhook",
        "https://discord.com/channels/123",
        "https://not-discord.com/api/webhooks/123/abc",
        "http://discord.com/api/webhooks/123456/abcdef",     # HTTP rejected
        "https://discord.com/api/webhooks/",                  # missing id/token
        "https://discord.com/api/webhooks/123456",            # missing token
        "https://discord.com/api/webhooks/123/abc\ngarbage",  # trailing newline
        "https://discord.com/api/webhooks/123/abc token",     # trailing space
        "",
    ])
    def test_non_discord_urls_rejected(self, url):
        assert is_discord_webhook_url(url) is False


# ---------------------------------------------------------------------------
# DiscordWebhookChannel._format_embed
# ---------------------------------------------------------------------------

class TestDiscordFormatEmbed:
    def test_basic_embed_structure(self):
        payload = {
            "source": "docsight",
            "timestamp": "2026-04-10T10:00:00Z",
            "severity": "warning",
            "event_type": "power_change",
            "message": "Downstream power shifted",
            "details": {"prev": -1.5, "current": -4.2},
        }
        embed = DiscordWebhookChannel._format_embed(payload)

        assert embed["title"] == "WARNING: Power Change"
        assert embed["description"] == "Downstream power shifted"
        assert embed["color"] == DISCORD_SEVERITY_COLORS["warning"]
        assert embed["timestamp"] == "2026-04-10T10:00:00Z"
        assert embed["footer"] == {"text": "DOCSight"}

    def test_fields_from_details(self):
        payload = {
            "severity": "critical",
            "event_type": "snr_change",
            "message": "SNR dropped",
            "details": {"prev": 38.0, "current": 30.0, "threshold": 33.0},
        }
        embed = DiscordWebhookChannel._format_embed(payload)
        field_names = [f["name"] for f in embed["fields"]]
        assert "Prev" in field_names
        assert "Current" in field_names
        assert "Threshold" in field_names

    def test_nested_details_serialized(self):
        payload = {
            "severity": "info",
            "event_type": "test",
            "message": "Test",
            "details": {"nested": {"a": 1, "b": 2}},
        }
        embed = DiscordWebhookChannel._format_embed(payload)
        nested_field = [f for f in embed["fields"] if f["name"] == "Nested"][0]
        assert '"a": 1' in nested_field["value"]

    def test_empty_details_no_fields(self):
        payload = {
            "severity": "info",
            "event_type": "test",
            "message": "Test",
            "details": {},
        }
        embed = DiscordWebhookChannel._format_embed(payload)
        assert "fields" not in embed

    def test_field_value_truncated_at_1024(self):
        payload = {
            "severity": "info",
            "event_type": "test",
            "message": "Test",
            "details": {"long_value": "x" * 2000},
        }
        embed = DiscordWebhookChannel._format_embed(payload)
        assert len(embed["fields"][0]["value"]) == 1024

    def test_max_25_fields(self):
        payload = {
            "severity": "info",
            "event_type": "test",
            "message": "Test",
            "details": {f"key_{i}": i for i in range(30)},
        }
        embed = DiscordWebhookChannel._format_embed(payload)
        assert len(embed["fields"]) == 25

    def test_unknown_severity_gets_grey(self):
        payload = {
            "severity": "unknown_level",
            "event_type": "test",
            "message": "Test",
            "details": {},
        }
        embed = DiscordWebhookChannel._format_embed(payload)
        assert embed["color"] == 0x95A5A6

    def test_none_details_handled(self):
        payload = {
            "severity": "info",
            "event_type": "test",
            "message": "Test",
            "details": None,
        }
        embed = DiscordWebhookChannel._format_embed(payload)
        assert "fields" not in embed

    def test_title_truncated_at_256(self):
        payload = {
            "severity": "info",
            "event_type": "a" * 300,
            "message": "Test",
            "details": {},
        }
        embed = DiscordWebhookChannel._format_embed(payload)
        assert len(embed["title"]) <= 256

    def test_description_truncated_at_4096(self):
        payload = {
            "severity": "info",
            "event_type": "test",
            "message": "x" * 5000,
            "details": {},
        }
        embed = DiscordWebhookChannel._format_embed(payload)
        assert len(embed["description"]) <= 4096

    def test_total_embed_under_6000_chars(self):
        payload = {
            "severity": "info",
            "event_type": "test",
            "message": "x" * 3000,
            "details": {f"key_{i}": "y" * 500 for i in range(20)},
        }
        embed = DiscordWebhookChannel._format_embed(payload)
        total = len(embed["title"]) + len(embed["description"])
        total += len(embed.get("footer", {}).get("text", ""))
        for f in embed.get("fields", []):
            total += len(f["name"]) + len(f["value"])
        assert total <= 6000

    def test_field_name_truncated_at_256(self):
        payload = {
            "severity": "info",
            "event_type": "test",
            "message": "Test",
            "details": {"a" * 300: "value"},
        }
        embed = DiscordWebhookChannel._format_embed(payload)
        assert len(embed["fields"][0]["name"]) <= 256


# ---------------------------------------------------------------------------
# DiscordWebhookChannel.send
# ---------------------------------------------------------------------------

class TestDiscordWebhookSend:
    @patch("app.notifier.requests.post")
    def test_send_posts_embed_payload(self, mock_post):
        mock_post.return_value = MagicMock(status_code=204)
        mock_post.return_value.raise_for_status = MagicMock()

        channel = DiscordWebhookChannel("https://discord.com/api/webhooks/1/abc")
        payload = {
            "source": "docsight",
            "timestamp": "2026-04-10T10:00:00Z",
            "severity": "info",
            "event_type": "test",
            "message": "Test notification",
            "details": {"test": True},
        }
        assert channel.send(payload) is True

        call_kwargs = mock_post.call_args
        sent_json = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert "embeds" in sent_json
        assert len(sent_json["embeds"]) == 1
        assert sent_json["embeds"][0]["description"] == "Test notification"

    @patch("app.notifier.requests.post")
    def test_send_returns_false_on_error(self, mock_post):
        mock_post.side_effect = Exception("Connection refused")
        channel = DiscordWebhookChannel("https://discord.com/api/webhooks/1/abc")
        assert channel.send({"severity": "info", "event_type": "test",
                             "message": "x", "details": {}}) is False

    def test_log_label_does_not_contain_url(self):
        channel = DiscordWebhookChannel(
            "https://discord.com/api/webhooks/123456/secret-token-here",
        )
        assert "secret-token-here" not in channel._log_label
        assert "123456" not in channel._log_label

    @patch("app.notifier.requests.post")
    def test_send_handles_none_details(self, mock_post):
        mock_post.return_value = MagicMock(status_code=204)
        mock_post.return_value.raise_for_status = MagicMock()
        channel = DiscordWebhookChannel("https://discord.com/api/webhooks/1/abc")
        assert channel.send({"severity": "info", "event_type": "test",
                             "message": "x", "details": None}) is True

    @patch("app.notifier.requests.post")
    def test_http_error_log_does_not_leak_token(self, mock_post, caplog):
        import logging
        resp = MagicMock(status_code=404)
        resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
        mock_post.return_value = resp
        secret = "super-secret-token-xyz"
        channel = DiscordWebhookChannel(
            f"https://discord.com/api/webhooks/123/{secret}",
        )
        with caplog.at_level(logging.WARNING, logger="docsis.notifier"):
            channel.send({"severity": "info", "event_type": "test",
                          "message": "x", "details": {}})
        assert secret not in caplog.text
        assert "123" not in caplog.text
        assert "404" in caplog.text


# ---------------------------------------------------------------------------
# NotificationDispatcher._setup_channels — auto-detection
# ---------------------------------------------------------------------------

class TestDispatcherChannelSetup:
    def _make_config(self, url, token=None):
        cfg = MagicMock()
        cfg.get.side_effect = lambda key, default=None: {
            "notify_webhook_url": url,
            "notify_webhook_token": token,
            "notify_cooldown": "3600",
            "notify_cooldowns": "{}",
            "notify_min_severity": "info",
        }.get(key, default)
        return cfg

    def test_discord_url_creates_discord_channel(self):
        dispatcher = NotificationDispatcher(
            self._make_config("https://discord.com/api/webhooks/123/abc"),
        )
        assert len(dispatcher._channels) == 1
        assert isinstance(dispatcher._channels[0], DiscordWebhookChannel)

    def test_generic_url_creates_webhook_channel(self):
        dispatcher = NotificationDispatcher(
            self._make_config("https://ntfy.sh/docsight"),
        )
        assert len(dispatcher._channels) == 1
        assert isinstance(dispatcher._channels[0], WebhookChannel)

    def test_discord_url_ignores_token(self):
        dispatcher = NotificationDispatcher(
            self._make_config(
                "https://discord.com/api/webhooks/123/abc",
                token="should-be-ignored",
            ),
        )
        assert isinstance(dispatcher._channels[0], DiscordWebhookChannel)

    def test_no_url_creates_no_channels(self):
        dispatcher = NotificationDispatcher(self._make_config(None))
        assert len(dispatcher._channels) == 0
