"""Notification dispatcher -- routes events to external channels (webhook, etc.)."""

from __future__ import annotations

import json
import logging
import re
import time
from abc import ABC, abstractmethod
from urllib.parse import quote
import requests

try:
    from pywebpush import WebPushException, webpush
except Exception:  # pragma: no cover - dependency availability is exercised by runtime config
    WebPushException = Exception
    webpush = None

from .types import EventDict, NotificationPayload, NotificationTestResult
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
    def send(self, payload: NotificationPayload) -> bool:
        """Send a notification payload. Returns True on success."""


class WebhookChannel(NotificationChannel):
    """HTTP POST webhook — works with ntfy, Discord, Gotify, custom endpoints."""

    def __init__(self, url, headers=None):
        self._url = url
        self._headers = {"Content-Type": "application/json"}
        if headers:
            self._headers.update(headers)

    def send(self, payload: NotificationPayload) -> bool:
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


class AppriseChannel(NotificationChannel):
    """Apprise API channel using /notify or /notify/{config_key}."""

    _TYPE_BY_SEVERITY = {
        "info": "info",
        "warning": "warning",
        "critical": "failure",
    }

    def __init__(self, base_url, config_key="", tag="", token=""):
        self._base_url = (base_url or "").rstrip("/")
        self._config_key = (config_key or "").strip()
        self._tag = (tag or "").strip()
        self._token = (token or "").strip()
        self._log_label = "Apprise API"
        self._last_error = ""

    @staticmethod
    def _format_body(payload: NotificationPayload) -> str:
        message = str(payload.get("message", ""))
        details = payload.get("details") or {}
        if not details:
            return message

        lines = []
        for key, value in details.items():
            if isinstance(value, (dict, list)):
                value = json.dumps(value, default=str)
            lines.append(f"{str(key).replace('_', ' ')}: {value}")
        return f"{message}\n\nDetails:\n" + "\n".join(lines)

    @classmethod
    def _format_payload(cls, payload: NotificationPayload) -> dict[str, object]:
        event_type = str(payload.get("event_type", "unknown"))
        severity = str(payload.get("severity", "info"))
        apprise_payload: dict[str, object] = {
            "title": f"DOCSight: {event_type.replace('_', ' ').title()}",
            "body": cls._format_body(payload),
            "type": cls._TYPE_BY_SEVERITY.get(severity, "info"),
            "format": "text",
        }
        return apprise_payload

    def _notify_url(self) -> str:
        if self._config_key:
            return f"{self._base_url}/notify/{quote(self._config_key, safe='')}"
        return f"{self._base_url}/notify"

    def send(self, payload: NotificationPayload) -> bool:
        try:
            apprise_payload = self._format_payload(payload)
            if self._tag:
                apprise_payload["tag"] = self._tag
            headers = {"Content-Type": "application/json"}
            if self._token:
                headers["Authorization"] = f"Bearer {self._token}"
            r = requests.post(
                self._notify_url(),
                json=apprise_payload,
                headers=headers,
                timeout=10,
            )
            r.raise_for_status()
            self._last_error = ""
            return True
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else "unknown"
            self._last_error = f"HTTP {status}"
            log.warning(
                "Apprise POST failed (%s): HTTP %s",
                self._log_label,
                status,
            )
            return False
        except Exception as e:
            self._last_error = type(e).__name__
            log.warning("Apprise POST failed (%s): %s", self._log_label, type(e).__name__)
            return False


class WebPushChannel(NotificationChannel):
    """Browser Web Push channel backed by persisted PWA subscriptions."""

    def __init__(self, storage, vapid_private_key: str, vapid_subject: str):
        self._storage = storage
        self._vapid_private_key = (vapid_private_key or "").strip()
        self._vapid_subject = (vapid_subject or "mailto:admin@example.com").strip()
        self._last_error = ""
        self._log_label = "PWA Web Push"

    @staticmethod
    def _notification_url(event_type: str) -> str:
        if event_type == "test":
            return "/?source=pwa#live"
        return "/?source=pwa#events"

    @classmethod
    def _format_payload(cls, payload: NotificationPayload) -> dict[str, object]:
        severity = str(payload.get("severity", "info") or "info")
        event_type = str(payload.get("event_type", "unknown") or "unknown")
        title = f"DOCSight {severity}: {event_type.replace('_', ' ').title()}"
        body = str(payload.get("message", "") or "DOCSight notification")
        return {
            "title": title[:100],
            "body": body[:240],
            "severity": severity,
            "event_type": event_type,
            "timestamp": payload.get("timestamp", utc_now()),
            "url": cls._notification_url(event_type),
        }

    @staticmethod
    def _response_status(exc) -> int | None:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
        try:
            return int(status) if status is not None else None
        except (TypeError, ValueError):
            return None

    def send(self, payload: NotificationPayload) -> bool:
        if webpush is None:
            self._last_error = "Web Push dependency unavailable"
            log.warning("Web Push unavailable: pywebpush is not installed")
            return False
        if not self._storage or not self._vapid_private_key:
            self._last_error = "Web Push is not configured"
            return False

        subscriptions = self._storage.list_pwa_push_subscriptions()
        if not subscriptions:
            self._last_error = "No browser subscriptions"
            return False

        data = json.dumps(self._format_payload(payload), separators=(",", ":"))
        errors = []
        for record in subscriptions:
            subscription = record.get("subscription") or {}
            endpoint = subscription.get("endpoint") or record.get("endpoint") or ""
            try:
                webpush(
                    subscription_info=subscription,
                    data=data,
                    vapid_private_key=self._vapid_private_key,
                    vapid_claims={"sub": self._vapid_subject},
                )
            except WebPushException as exc:
                status = self._response_status(exc)
                if status in (404, 410) and endpoint:
                    self._storage.delete_pwa_push_subscription(endpoint)
                    errors.append(f"expired:{status}")
                    continue
                errors.append(f"HTTP {status or 'unknown'}")
                log.warning("Web Push POST failed (%s): HTTP %s", self._log_label, status or "unknown")
            except Exception as exc:
                status = self._response_status(exc)
                if status in (404, 410) and endpoint:
                    self._storage.delete_pwa_push_subscription(endpoint)
                    errors.append(f"expired:{status}")
                    continue
                errors.append(type(exc).__name__)
                log.warning("Web Push POST failed (%s): %s", self._log_label, type(exc).__name__)

        if errors:
            self._last_error = "; ".join(errors)
            return False
        self._last_error = ""
        return True


class DiscordWebhookChannel(NotificationChannel):
    """Discord-native webhook channel with rich embed formatting."""

    def __init__(self, url):
        self._url = url
        self._log_label = "Discord webhook"

    @staticmethod
    def _format_embed(payload: NotificationPayload) -> dict[str, object]:
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

    def send(self, payload: NotificationPayload) -> bool:
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
                self._log_label, e.response.status_code if e.response is not None else "unknown",
            )
            return False
        except Exception as e:
            log.warning("Discord webhook POST failed (%s): %s", self._log_label, type(e).__name__)
            return False


def is_discord_webhook_url(url: str) -> bool:
    """Check if a URL is a Discord webhook endpoint."""
    return bool(_DISCORD_URL_RE.match(url))


class NotificationDispatcher:
    """Routes events through severity filter and cooldown to notification channels."""

    def __init__(self, config_mgr, storage=None):
        self._config_mgr = config_mgr
        self._storage = storage
        # key -> last_sent_timestamp, where key is either event_type or
        # event_type:severity when a severity-specific cooldown is configured.
        self._cooldown_tracker = {}

    def _get_cooldown_overrides(self) -> dict[str, int]:
        try:
            data = json.loads(self._config_mgr.get("notify_cooldowns", "{}"))
        except (json.JSONDecodeError, TypeError):
            return {}
        if not isinstance(data, dict):
            return {}
        return data

    @staticmethod
    def _coerce_cooldown(value, default: int) -> int:
        try:
            return int(value)
        except (ValueError, TypeError):
            return default

    def _get_channels(self) -> list[NotificationChannel]:
        channels = []
        url = self._config_mgr.get("notify_webhook_url")
        if url:
            if is_discord_webhook_url(url):
                channels.append(DiscordWebhookChannel(url))
            else:
                headers = {}
                token = self._config_mgr.get("notify_webhook_token")
                if token:
                    headers["Authorization"] = f"Bearer {token}"
                channels.append(WebhookChannel(url, headers))

        if self._config_mgr.get("notify_apprise_enabled"):
            apprise_url = self._config_mgr.get("notify_apprise_url")
            if apprise_url:
                channels.append(AppriseChannel(
                    apprise_url,
                    config_key=self._config_mgr.get("notify_apprise_key") or "",
                    tag=self._config_mgr.get("notify_apprise_tag") or "",
                    token=self._config_mgr.get("notify_apprise_token") or "",
                ))
        if self._config_mgr.get("notify_pwa_push_enabled") and self._storage:
            vapid_public_key = self._config_mgr.get("notify_pwa_push_vapid_public_key") or ""
            vapid_private_key = self._config_mgr.get("notify_pwa_push_vapid_private_key") or ""
            if vapid_public_key and vapid_private_key:
                channels.append(WebPushChannel(
                    self._storage,
                    vapid_private_key=vapid_private_key,
                    vapid_subject=self._config_mgr.get("notify_pwa_push_vapid_subject") or "mailto:admin@example.com",
                ))
        return channels

    def dispatch(self, events: list[EventDict]) -> None:
        """Send qualifying events to all configured channels."""
        channels = self._get_channels()
        if not channels:
            return
            
        for event in events:
            if not self._should_send(event):
                continue
            payload = self._build_payload(event)
            for channel in channels:
                try:
                    channel.send(payload)
                except Exception as e:
                    log.warning(
                        "Notification failed (%s): %s",
                        type(channel).__name__, e,
                    )

    def _should_send(self, event) -> bool:
        # Severity filter
        min_severity = self._config_mgr.get("notify_min_severity", "warning")
        min_level = SEVERITY_ORDER.get(min_severity, 1)
        event_level = SEVERITY_ORDER.get(event.get("severity", "info"), 0)
        if event_level < min_level:
            return False

        # Cooldown per event_type and severity. Exact event_type:severity
        # overrides take precedence. Legacy event-only overrides still provide
        # the cooldown value for every severity of that event, but non-disabled
        # cooldown tracking remains severity-specific.
        now = time.time()
        event_type = str(event.get("event_type", "unknown") or "unknown")
        severity = str(event.get("severity", "info") or "info").lower()

        default_cooldown = self._coerce_cooldown(
            self._config_mgr.get("notify_cooldown", 3600),
            3600,
        )

        overrides = self._get_cooldown_overrides()
        severity_key = f"{event_type}:{severity}"
        if severity_key in overrides:
            cooldown = overrides[severity_key]
        else:
            cooldown = overrides.get(event_type, default_cooldown)

        cooldown = self._coerce_cooldown(cooldown, default_cooldown)

        if cooldown == 0:  # 0 = disabled, never send this type/severity
            return False
        if severity_key in self._cooldown_tracker:
            if (now - self._cooldown_tracker[severity_key]) < cooldown:
                return False
        self._cooldown_tracker[severity_key] = now
        return True

    @staticmethod
    def _build_payload(event: EventDict) -> NotificationPayload:
        return {
            "source": "docsight",
            "timestamp": event.get("timestamp", utc_now()),
            "severity": event.get("severity", "info"),
            "event_type": event.get("event_type", "unknown"),
            "message": event.get("message", ""),
            "details": event.get("details", {}),
        }

    def test(self) -> NotificationTestResult:
        """Send a test notification to all channels. Returns {success, error}."""
        channels = self._get_channels()
        if not channels:
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
        for channel in channels:
            try:
                if not channel.send(payload):
                    detail = getattr(channel, "_last_error", "")
                    errors.append(
                        f"{type(channel).__name__}: {detail or 'send returned false'}",
                    )
            except Exception as e:
                errors.append(f"{type(channel).__name__}: {e}")
        if errors:
            return {"success": False, "error": "; ".join(errors)}
        return {"success": True}
