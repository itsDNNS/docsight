"""Notification system for DOCSight – supports multiple channels.

Supported backends:
    - Webhook (generic HTTP POST with JSON payload)
    - Telegram (Bot API)
    - Discord (webhook URL)
    - Email (SMTP)
    - Gotify (push notification server)
    - ntfy (ntfy.sh or self-hosted)

Each backend is optional and only activated when configured.
"""

import json
import logging
import smtplib
import threading
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests

log = logging.getLogger("docsis.notifier")


class Notifier:
    """Dispatches notifications to configured channels."""

    def __init__(self, config_mgr):
        self.config_mgr = config_mgr
        self._cooldown: dict[str, float] = {}
        self._cooldown_seconds = 300  # 5 min between duplicate alerts
        self._lock = threading.Lock()

    def _get(self, key, default=""):
        return self.config_mgr.get(key, default)

    def _in_cooldown(self, key: str) -> bool:
        """Check if a notification key is in cooldown."""
        now = time.time()
        with self._lock:
            last = self._cooldown.get(key, 0)
            if now - last < self._cooldown_seconds:
                return True
            self._cooldown[key] = now
        return False

    # ── Public API ──

    def is_configured(self) -> bool:
        """True if at least one notification channel is configured."""
        return any([
            self._get("notify_webhook_url"),
            self._get("notify_telegram_token") and self._get("notify_telegram_chat_id"),
            self._get("notify_discord_webhook_url"),
            self._get("notify_email_smtp_host"),
            self._get("notify_gotify_url"),
            self._get("notify_ntfy_url"),
        ])

    def send(self, title: str, message: str, level: str = "warning",
             dedup_key: str | None = None):
        """Send a notification to all configured channels.

        Args:
            title: Short notification title.
            message: Notification body text.
            level: Severity level (info, warning, critical).
            dedup_key: Optional key for deduplication/cooldown.
        """
        if dedup_key and self._in_cooldown(dedup_key):
            log.debug("Notification suppressed (cooldown): %s", dedup_key)
            return

        channels = []
        if self._get("notify_webhook_url"):
            channels.append(("webhook", self._send_webhook))
        if self._get("notify_telegram_token") and self._get("notify_telegram_chat_id"):
            channels.append(("telegram", self._send_telegram))
        if self._get("notify_discord_webhook_url"):
            channels.append(("discord", self._send_discord))
        if self._get("notify_email_smtp_host"):
            channels.append(("email", self._send_email))
        if self._get("notify_gotify_url"):
            channels.append(("gotify", self._send_gotify))
        if self._get("notify_ntfy_url"):
            channels.append(("ntfy", self._send_ntfy))

        if not channels:
            return

        for name, func in channels:
            try:
                func(title, message, level)
                log.info("Notification sent via %s: %s", name, title)
            except Exception as e:
                log.error("Notification failed (%s): %s", name, e)

    def send_digest(self, subject: str, body: str):
        """Send a digest (longer message, no cooldown)."""
        for name, func in [
            ("webhook", self._send_webhook),
            ("telegram", self._send_telegram),
            ("discord", self._send_discord),
            ("email", self._send_email),
            ("gotify", self._send_gotify),
            ("ntfy", self._send_ntfy),
        ]:
            try:
                if name == "webhook" and self._get("notify_webhook_url"):
                    func(subject, body, "info")
                elif name == "telegram" and self._get("notify_telegram_token"):
                    func(subject, body, "info")
                elif name == "discord" and self._get("notify_discord_webhook_url"):
                    func(subject, body, "info")
                elif name == "email" and self._get("notify_email_smtp_host"):
                    func(subject, body, "info")
                elif name == "gotify" and self._get("notify_gotify_url"):
                    func(subject, body, "info")
                elif name == "ntfy" and self._get("notify_ntfy_url"):
                    func(subject, body, "info")
            except Exception as e:
                log.error("Digest failed (%s): %s", name, e)

    # ── Backend implementations ──

    def _send_webhook(self, title: str, message: str, level: str):
        """Send generic JSON webhook POST."""
        url = self._get("notify_webhook_url")
        payload = {
            "title": title,
            "message": message,
            "level": level,
            "source": "docsight",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()

    def _send_telegram(self, title: str, message: str, level: str):
        """Send via Telegram Bot API."""
        token = self._get("notify_telegram_token")
        chat_id = self._get("notify_telegram_chat_id")
        icon = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}.get(level, "📡")
        text = f"{icon} *{title}*\n\n{message}"
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown",
            },
            timeout=10,
        )
        r.raise_for_status()

    def _send_discord(self, title: str, message: str, level: str):
        """Send via Discord webhook."""
        url = self._get("notify_discord_webhook_url")
        color = {"info": 0x3498DB, "warning": 0xF39C12, "critical": 0xE74C3C}.get(level, 0x95A5A6)
        payload = {
            "embeds": [{
                "title": title,
                "description": message,
                "color": color,
                "footer": {"text": "DOCSight"},
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }]
        }
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()

    def _send_email(self, title: str, message: str, level: str):
        """Send via SMTP."""
        host = self._get("notify_email_smtp_host")
        port = int(self._get("notify_email_smtp_port") or 587)
        user = self._get("notify_email_smtp_user")
        password = self._get("notify_email_smtp_password")
        sender = self._get("notify_email_from") or user
        recipient = self._get("notify_email_to")
        use_tls = self._get("notify_email_tls") != "false"

        if not recipient:
            log.warning("Email notification skipped: no recipient configured")
            return

        msg = MIMEMultipart()
        msg["From"] = sender
        msg["To"] = recipient
        msg["Subject"] = f"[DOCSight] {title}"
        msg.attach(MIMEText(message, "plain", "utf-8"))

        if use_tls:
            server = smtplib.SMTP(host, port, timeout=10)
            server.starttls()
        else:
            server = smtplib.SMTP(host, port, timeout=10)

        if user:
            server.login(user, password)
        server.send_message(msg)
        server.quit()

    def _send_gotify(self, title: str, message: str, level: str):
        """Send via Gotify push notification server."""
        url = self._get("notify_gotify_url").rstrip("/")
        token = self._get("notify_gotify_token")
        priority = {"info": 2, "warning": 5, "critical": 8}.get(level, 5)
        r = requests.post(
            f"{url}/message",
            params={"token": token},
            json={
                "title": title,
                "message": message,
                "priority": priority,
            },
            timeout=10,
        )
        r.raise_for_status()

    def _send_ntfy(self, title: str, message: str, level: str):
        """Send via ntfy.sh or self-hosted ntfy."""
        url = self._get("notify_ntfy_url")
        token = self._get("notify_ntfy_token")
        priority = {"info": "default", "warning": "high", "critical": "urgent"}.get(level, "default")
        headers = {
            "Title": title,
            "Priority": priority,
            "Tags": "satellite,docsight",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        r = requests.post(url, data=message.encode("utf-8"), headers=headers, timeout=10)
        r.raise_for_status()


def build_health_notification(analysis: dict, prev_health: str | None = None) -> tuple[str, str, str] | None:
    """Build a notification message from health analysis.

    Returns (title, message, level) or None if no notification needed.
    """
    summary = analysis.get("summary", {})
    health = summary.get("health", "good")

    # Only notify on degradation or persistent poor
    if health == "good":
        return None

    issues = summary.get("health_issues", [])
    if not issues:
        return None

    level = "critical" if health == "poor" else "warning"
    title = f"DOCSIS Health: {health.upper()}"

    lines = [f"Connection health changed to {health}."]
    for issue in issues:
        if "ds_power" in issue:
            lines.append(f"• DS Power: {summary.get('ds_power_min')}/{summary.get('ds_power_max')} dBmV")
        elif "us_power" in issue:
            lines.append(f"• US Power: {summary.get('us_power_max')} dBmV")
        elif "snr" in issue:
            lines.append(f"• SNR: {summary.get('ds_snr_min')} dB")
        elif "uncorr" in issue:
            lines.append(f"• Uncorrectable Errors: {summary.get('ds_uncorrectable_errors'):,}")

    return title, "\n".join(lines), level


def build_digest(analysis: dict, watchdog_events: list | None = None,
                 ping_stats: dict | None = None) -> tuple[str, str]:
    """Build a scheduled health digest message.

    Returns (subject, body).
    """
    summary = analysis.get("summary", {})
    health = summary.get("health", "unknown")

    lines = [
        "📊 DOCSight Health Digest",
        f"Overall Health: {health.upper()}",
        "",
        "Signal Summary:",
        f"  DS Channels: {summary.get('ds_total', 0)}",
        f"  DS Power: {summary.get('ds_power_min')}..{summary.get('ds_power_max')} dBmV (avg {summary.get('ds_power_avg')})",
        f"  DS SNR: {summary.get('ds_snr_min')}..{summary.get('ds_snr_avg')} dB",
        f"  Correctable Errors: {summary.get('ds_correctable_errors', 0):,}",
        f"  Uncorrectable Errors: {summary.get('ds_uncorrectable_errors', 0):,}",
        f"  US Channels: {summary.get('us_total', 0)}",
        f"  US Power: {summary.get('us_power_min')}..{summary.get('us_power_max')} dBmV (avg {summary.get('us_power_avg')})",
    ]

    if watchdog_events:
        lines += ["", "Recent Watchdog Events:"]
        for evt in watchdog_events[-5:]:
            lines.append(f"  • {evt.get('type', '?')}: {evt.get('message', '')}")

    if ping_stats:
        lines += [
            "",
            "Ping Statistics:",
            f"  Avg Latency: {ping_stats.get('avg_ms', 0):.1f} ms",
            f"  Packet Loss: {ping_stats.get('loss_pct', 0):.1f}%",
        ]

    return "DOCSight Health Digest", "\n".join(lines)
