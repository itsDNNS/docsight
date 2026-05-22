"""Tests for the notification dispatcher and webhook channels."""

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from app.notifier import (
    DISCORD_SEVERITY_COLORS,
    AppriseChannel,
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
        url_tail_marker = "REDACTED-PLACEHOLDER-VALUE"
        channel = DiscordWebhookChannel(
            f"https://discord.com/api/webhooks/123/{url_tail_marker}",
        )
        with caplog.at_level(logging.WARNING, logger="docsis.notifier"):
            channel.send({"severity": "info", "event_type": "test",
                          "message": "x", "details": {}})
        assert url_tail_marker not in caplog.text
        assert "123" not in caplog.text
        assert "404" in caplog.text


# ---------------------------------------------------------------------------
# AppriseChannel
# ---------------------------------------------------------------------------

class TestAppriseChannel:
    def test_format_payload_maps_severity_to_apprise_type(self):
        payload = {
            "severity": "critical",
            "event_type": "snr_change",
            "message": "SNR dropped",
            "details": {"previous_snr": 38.0, "current_snr": 30.0},
        }
        formatted = AppriseChannel._format_payload(payload)

        assert formatted["title"] == "DOCSight: Snr Change"
        assert formatted["type"] == "failure"
        assert formatted["format"] == "text"
        assert "SNR dropped" in formatted["body"]
        assert "previous snr: 38.0" in formatted["body"]
        assert "current snr: 30.0" in formatted["body"]

    def test_format_payload_serializes_nested_details(self):
        formatted = AppriseChannel._format_payload({
            "severity": "warning",
            "event_type": "test_event",
            "message": "Nested",
            "details": {"nested": {"a": 1}},
        })

        assert formatted["type"] == "warning"
        assert 'nested: {"a": 1}' in formatted["body"]

    @patch("app.notifier.requests.post")
    def test_send_posts_to_stateless_endpoint(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        mock_post.return_value.raise_for_status = MagicMock()
        channel = AppriseChannel("http://apprise:8000")

        assert channel.send({"severity": "info", "event_type": "test", "message": "Hello", "details": {}}) is True

        assert mock_post.call_args.args[0] == "http://apprise:8000/notify"
        sent_json = mock_post.call_args.kwargs["json"]
        assert sent_json["body"] == "Hello"
        assert "Authorization" not in mock_post.call_args.kwargs["headers"]

    @patch("app.notifier.requests.post")
    def test_send_posts_to_config_key_with_tag_and_token(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        mock_post.return_value.raise_for_status = MagicMock()
        channel = AppriseChannel(
            "http://apprise:8000/",
            config_key="default key",
            tag="ops,admin",
            token="tok",
        )

        assert channel.send({"severity": "info", "event_type": "test", "message": "Hello", "details": {}}) is True

        assert mock_post.call_args.args[0] == "http://apprise:8000/notify/default%20key"
        assert mock_post.call_args.kwargs["json"]["tag"] == "ops,admin"
        assert mock_post.call_args.kwargs["headers"]["Authorization"] == "Bearer tok"

    @patch("app.notifier.requests.post")
    def test_http_error_log_does_not_leak_secret_context(self, mock_post, caplog):
        import logging
        resp = MagicMock(status_code=401)
        resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
        mock_post.return_value = resp
        key_marker = "REDACTED-CONFIG-KEY"
        token_marker = "TOKMARK"
        channel = AppriseChannel(
            "http://apprise:8000",
            config_key=key_marker,
            tag="ops",
            token=token_marker,
        )

        with caplog.at_level(logging.WARNING, logger="docsis.notifier"):
            channel.send({"severity": "info", "event_type": "test", "message": "x", "details": {}})

        assert key_marker not in caplog.text
        assert token_marker not in caplog.text
        assert "401" in caplog.text


# ---------------------------------------------------------------------------
# NotificationDispatcher._setup_channels — auto-detection
# ---------------------------------------------------------------------------

class TestDispatcherChannelSetup:
    def _make_config(self, url, token=None, apprise_enabled=False, apprise_url="", apprise_key="", apprise_tag="", apprise_token=""):
        cfg = MagicMock()
        cfg.get.side_effect = lambda key, default=None: {
            "notify_webhook_url": url,
            "notify_webhook_token": token,
            "notify_apprise_enabled": apprise_enabled,
            "notify_apprise_url": apprise_url,
            "notify_apprise_key": apprise_key,
            "notify_apprise_tag": apprise_tag,
            "notify_apprise_token": apprise_token,
            "notify_cooldown": "3600",
            "notify_cooldowns": "{}",
            "notify_min_severity": "info",
        }.get(key, default)
        return cfg

    def test_discord_url_creates_discord_channel(self):
        dispatcher = NotificationDispatcher(
            self._make_config("https://discord.com/api/webhooks/123/abc"),
        )
        channels = dispatcher._get_channels()
        assert len(channels) == 1
        assert isinstance(channels[0], DiscordWebhookChannel)

    def test_generic_url_creates_webhook_channel(self):
        dispatcher = NotificationDispatcher(
            self._make_config("https://ntfy.sh/docsight"),
        )
        channels = dispatcher._get_channels()
        assert len(channels) == 1
        assert isinstance(channels[0], WebhookChannel)

    def test_discord_url_ignores_token(self):
        dispatcher = NotificationDispatcher(
            self._make_config(
                "https://discord.com/api/webhooks/123/abc",
                token="UNUSED",
            ),
        )
        channels = dispatcher._get_channels()
        assert isinstance(channels[0], DiscordWebhookChannel)

    def test_no_url_creates_no_channels(self):
        dispatcher = NotificationDispatcher(self._make_config(None))
        assert len(dispatcher._get_channels()) == 0

    def test_apprise_enabled_creates_apprise_channel(self):
        dispatcher = NotificationDispatcher(
            self._make_config(
                None,
                apprise_enabled=True,
                apprise_url="http://apprise:8000",
                apprise_key="default",
                apprise_tag="ops",
                apprise_token="token",
            ),
        )
        channels = dispatcher._get_channels()
        assert len(channels) == 1
        assert isinstance(channels[0], AppriseChannel)

    def test_webhook_and_apprise_can_run_together(self):
        dispatcher = NotificationDispatcher(
            self._make_config(
                "https://ntfy.sh/docsight",
                apprise_enabled=True,
                apprise_url="http://apprise:8000",
            ),
        )
        channels = dispatcher._get_channels()
        assert [type(channel) for channel in channels] == [WebhookChannel, AppriseChannel]

    def test_apprise_enabled_without_url_is_ignored(self):
        dispatcher = NotificationDispatcher(self._make_config(None, apprise_enabled=True))
        assert len(dispatcher._get_channels()) == 0

    @patch("app.notifier.requests.post")
    def test_apprise_dispatch_keeps_severity_and_cooldown_controls(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        mock_post.return_value.raise_for_status = MagicMock()
        config = self._make_config(
            None,
            apprise_enabled=True,
            apprise_url="http://apprise:8000",
        )
        config.get.side_effect = lambda key, default=None: {
            "notify_webhook_url": None,
            "notify_apprise_enabled": True,
            "notify_apprise_url": "http://apprise:8000",
            "notify_apprise_key": "",
            "notify_apprise_tag": "",
            "notify_apprise_token": "",
            "notify_cooldown": "3600",
            "notify_cooldowns": json.dumps({"disabled_event": 0}),
            "notify_min_severity": "warning",
        }.get(key, default)
        dispatcher = NotificationDispatcher(config)

        dispatcher.dispatch([
            {"timestamp": "2026-04-10T10:00:00Z", "severity": "info", "event_type": "low_info", "message": "Below threshold", "details": {}},
            {"timestamp": "2026-04-10T10:00:01Z", "severity": "warning", "event_type": "disabled_event", "message": "Disabled", "details": {}},
            {"timestamp": "2026-04-10T10:00:02Z", "severity": "warning", "event_type": "signal_warning", "message": "Sent", "details": {"snr": 30}},
        ])
        dispatcher.dispatch([
            {"timestamp": "2026-04-10T10:00:03Z", "severity": "warning", "event_type": "signal_warning", "message": "Suppressed by cooldown", "details": {}},
        ])

        assert mock_post.call_count == 1
        assert mock_post.call_args.args[0] == "http://apprise:8000/notify"
        sent_json = mock_post.call_args.kwargs["json"]
        assert sent_json["title"] == "DOCSight: Signal Warning"
        assert sent_json["type"] == "warning"
        assert "Sent" in sent_json["body"]
        assert "snr: 30" in sent_json["body"]

    @patch("app.notifier.requests.post")
    def test_apprise_test_notification_returns_sanitized_http_error(self, mock_post):
        resp = MagicMock(status_code=401)
        resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
        mock_post.return_value = resp
        key_marker = "REDACTED-CONFIG-KEY"
        apprise_token_marker = "REDACTED-TOKEN"
        config = self._make_config(
            None,
            apprise_enabled=True,
            apprise_url="http://apprise:8000",
            apprise_key=key_marker,
            apprise_token=apprise_token_marker,
        )
        dispatcher = NotificationDispatcher(config)

        result = dispatcher.test()

        assert result == {"success": False, "error": "AppriseChannel: HTTP 401"}
        assert key_marker not in result.get("error", "")
        assert apprise_token_marker not in result.get("error", "")

    def test_test_notification_returns_generic_error_for_unexpected_channel_exception(self, monkeypatch):
        class BrokenChannel:
            def send(self, payload):
                raise RuntimeError("secret-token-123 / internal/path")

        dispatcher = NotificationDispatcher(self._make_config(None))
        monkeypatch.setattr(dispatcher, "_get_channels", lambda: [BrokenChannel()])

        result = dispatcher.test()

        assert result == {
            "success": False,
            "error": "BrokenChannel: test failed; check server logs",
        }
        assert "secret-token-123" not in result.get("error", "")
        assert "internal/path" not in result.get("error", "")


class TestDispatcherSeverityCooldowns:
    def _make_config(self, cooldowns, default_cooldown="3600"):
        cfg = MagicMock()
        cfg.get.side_effect = lambda key, default=None: {
            "notify_min_severity": "info",
            "notify_cooldown": default_cooldown,
            "notify_cooldowns": json.dumps(cooldowns),
        }.get(key, default)
        return cfg

    def test_default_cooldown_is_tracked_independently_by_severity(self):
        dispatcher = NotificationDispatcher(self._make_config({}))

        assert dispatcher._should_send({"event_type": "modulation_change", "severity": "info"}) is True
        assert dispatcher._should_send({"event_type": "modulation_change", "severity": "critical"}) is True
        assert dispatcher._should_send({"event_type": "modulation_change", "severity": "info"}) is False
        assert dispatcher._should_send({"event_type": "modulation_change", "severity": "critical"}) is False

    def test_severity_specific_cooldowns_are_tracked_independently(self):
        dispatcher = NotificationDispatcher(self._make_config({
            "modulation_change:info": 3600,
            "modulation_change:critical": 3600,
        }))

        assert dispatcher._should_send({"event_type": "modulation_change", "severity": "info"}) is True
        assert dispatcher._should_send({"event_type": "modulation_change", "severity": "critical"}) is True
        assert dispatcher._should_send({"event_type": "modulation_change", "severity": "info"}) is False
        assert dispatcher._should_send({"event_type": "modulation_change", "severity": "critical"}) is False

    def test_legacy_event_cooldown_value_is_tracked_independently_by_severity(self):
        dispatcher = NotificationDispatcher(self._make_config({"modulation_change": 3600}))

        assert dispatcher._should_send({"event_type": "modulation_change", "severity": "info"}) is True
        assert dispatcher._should_send({"event_type": "modulation_change", "severity": "critical"}) is True
        assert dispatcher._should_send({"event_type": "modulation_change", "severity": "info"}) is False
        assert dispatcher._should_send({"event_type": "modulation_change", "severity": "critical"}) is False

    def test_severity_specific_disable_does_not_disable_other_severities(self):
        dispatcher = NotificationDispatcher(self._make_config({
            "health_change:info": 0,
            "health_change:critical": 3600,
        }))

        assert dispatcher._should_send({"event_type": "health_change", "severity": "info"}) is False
        assert dispatcher._should_send({"event_type": "health_change", "severity": "critical"}) is True
