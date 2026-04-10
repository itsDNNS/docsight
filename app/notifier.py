"""Notification dispatcher — routes events to external channels (webhook, etc.)."""

import json
import logging
import re
import time
from abc import ABC, abstractmethod
import requests

from .tz import utc_now

log = logging.getLogger("docsis.notifier")

SEVERITY_ORDER = {"info": 0, "warning": 1, "critical": 2}

_DISCORD_URL_RE = re.compile(
    r"https://(?:ptb\.|canary\.)?discord(?:app)?\.com/api(?:/v\d+)?/webhooks/\d+/[\w-]+(?:\?[\w=&]+)?\Z",
    re.IGNORECASE,
)

_DISCORD_EMBED_TITLE_MAX = 256
_DISCORD_EMBED_DESC_MAX = 4096
_DISCORD_EMBED_FIELD_NAME_MAX = 256
_DISCORD_EMBED_FIELD_VALUE_MAX = 1024
_DISCORD_EMBED_FIELDS_MAX = 25
_DISCORD_EMBED_TOTAL_MAX = 6000

DISCORD_SEVERITY_COLORS = {
    "info": 0x3498DB,       # blue
    "warning": 0xF39C12,    # amber
    "critical": 0xE74C3C,   # red
}


class NotificationChannel(ABC):
    """Base class for notification channels."""

    @abstractmethod
    def send(self, payload: dict) -> bool:
        """Send a notification payload. Returns True on success."""


class WebhookChannel(NotificationChannel):
    """HTTP POST webhook — works with ntfy, Discord, Gotify, custom endpoints."""

    def __init__(self, url, headers=None):
        self._url = url
        self._headers = {"Content-Type": "application/json"}
        if headers:
            self._headers.update(headers)

    def send(self, payload: dict) -> bool:
        try:
            r = requests.post(
                self._url,
                json=payload,
                headers=self._headers,
                timeout=10,
            )
            r.raise_for_status()
            return True
        except Exception as e:
            log.warning("Webhook POST failed (%s): %s", self._url, e)
            return False


class DiscordWebhookChannel(NotificationChannel):
    """Discord-native webhook channel with rich embed formatting."""

    def __init__(self, url):
        self._url = url
        # Redact token from URL for logging (keep webhook ID only)
        parts = url.rsplit("/", 1)
        self._safe_url = parts[0] + "/***" if len(parts) == 2 else url

    @staticmethod
    def _format_embed(payload: dict) -> dict:
        """Convert a DOCSight notification payload into a Discord embed."""
        severity = payload.get("severity", "info")
        event_type = payload.get("event_type", "unknown")
        message = payload.get("message", "")
        details = payload.get("details") or {}
        timestamp = payload.get("timestamp", utc_now())

        title = f"{severity.upper()}: {event_type.replace('_', ' ').title()}"
        embed = {
            "title": title[:_DISCORD_EMBED_TITLE_MAX],
            "description": message[:_DISCORD_EMBED_DESC_MAX],
            "color": DISCORD_SEVERITY_COLORS.get(severity, 0x95A5A6),
            "timestamp": timestamp,
            "footer": {"text": "DOCSight"},
        }

        footer_text = embed["footer"]["text"]
        total_chars = len(embed["title"]) + len(embed["description"]) + len(footer_text)
        fields = []
        for key, value in details.items():
            if isinstance(value, (dict, list)):
                value = json.dumps(value, default=str)
            name = key.replace("_", " ").title()[:_DISCORD_EMBED_FIELD_NAME_MAX]
            val_str = str(value)[:_DISCORD_EMBED_FIELD_VALUE_MAX]
            total_chars += len(name) + len(val_str)
            if total_chars > _DISCORD_EMBED_TOTAL_MAX:
                break
            fields.append({
                "name": name,
                "value": val_str,
                "inline": len(str(value)) < 40,
            })
            if len(fields) >= _DISCORD_EMBED_FIELDS_MAX:
                break
        if fields:
            embed["fields"] = fields

        return embed

    def send(self, payload: dict) -> bool:
        try:
            discord_payload = {"embeds": [self._format_embed(payload)]}
            r = requests.post(
                self._url,
                json=discord_payload,
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            r.raise_for_status()
            return True
        except requests.HTTPError as e:
            # Sanitize: raise_for_status() embeds the full URL (with token)
            log.warning(
                "Discord webhook POST failed (%s): HTTP %s",
                self._safe_url, e.response.status_code if e.response is not None else "unknown",
            )
            return False
        except Exception as e:
            log.warning("Discord webhook POST failed (%s): %s", self._safe_url, type(e).__name__)
            return False


def is_discord_webhook_url(url: str) -> bool:
    """Check if a URL is a Discord webhook endpoint."""
    return bool(_DISCORD_URL_RE.match(url))


class NotificationDispatcher:
    """Routes events through severity filter and cooldown to notification channels."""

    def __init__(self, config_mgr):
        self._config_mgr = config_mgr
        self._channels = []
        self._cooldown_tracker = {}  # event_type -> last_sent_timestamp
        try:
            self._default_cooldown = int(config_mgr.get("notify_cooldown", 3600))
        except (ValueError, TypeError):
            self._default_cooldown = 3600
        try:
            self._cooldown_overrides = json.loads(
                config_mgr.get("notify_cooldowns", "{}")
            )
        except (json.JSONDecodeError, TypeError):
            self._cooldown_overrides = {}
        self._min_severity = config_mgr.get("notify_min_severity", "warning")
        self._setup_channels()

    def _setup_channels(self):
        url = self._config_mgr.get("notify_webhook_url")
        if url:
            if is_discord_webhook_url(url):
                self._channels.append(DiscordWebhookChannel(url))
                log.info("Notification channel: Discord webhook configured")
            else:
                headers = {}
                token = self._config_mgr.get("notify_webhook_token")
                if token:
                    headers["Authorization"] = f"Bearer {token}"
                self._channels.append(WebhookChannel(url, headers))
                log.info("Notification channel: webhook configured")

    def dispatch(self, events: list):
        """Send qualifying events to all configured channels."""
        if not self._channels:
            return
        for event in events:
            if not self._should_send(event):
                continue
            payload = self._build_payload(event)
            for channel in self._channels:
                try:
                    channel.send(payload)
                except Exception as e:
                    log.warning(
                        "Notification failed (%s): %s",
                        type(channel).__name__, e,
                    )

    def _should_send(self, event) -> bool:
        # Severity filter
        min_level = SEVERITY_ORDER.get(self._min_severity, 1)
        event_level = SEVERITY_ORDER.get(event.get("severity", "info"), 0)
        if event_level < min_level:
            return False

        # Cooldown per event_type
        now = time.time()
        key = event.get("event_type", "unknown")
        cooldown = self._cooldown_overrides.get(key, self._default_cooldown)
        if isinstance(cooldown, str):
            try:
                cooldown = int(cooldown)
            except ValueError:
                cooldown = self._default_cooldown
        if cooldown == 0:  # 0 = disabled, never send this type
            return False
        if key in self._cooldown_tracker:
            if (now - self._cooldown_tracker[key]) < cooldown:
                return False
        self._cooldown_tracker[key] = now
        return True

    @staticmethod
    def _build_payload(event):
        return {
            "source": "docsight",
            "timestamp": event.get("timestamp", utc_now()),
            "severity": event.get("severity", "info"),
            "event_type": event.get("event_type", "unknown"),
            "message": event.get("message", ""),
            "details": event.get("details", {}),
        }

    def test(self) -> dict:
        """Send a test notification to all channels. Returns {success, error}."""
        if not self._channels:
            return {"success": False, "error": "No notification channels configured"}
        payload = {
            "source": "docsight",
            "timestamp": utc_now(),
            "severity": "info",
            "event_type": "test",
            "message": "DOCSight test notification",
            "details": {"test": True},
        }
        errors = []
        for channel in self._channels:
            try:
                if not channel.send(payload):
                    errors.append(f"{type(channel).__name__}: send returned false")
            except Exception as e:
                errors.append(f"{type(channel).__name__}: {e}")
        if errors:
            return {"success": False, "error": "; ".join(errors)}
        return {"success": True}
