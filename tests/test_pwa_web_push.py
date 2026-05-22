"""PWA Web Push notification regression coverage."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.config import ConfigManager, PASSWORD_MASK
from app.notifier import NotificationDispatcher, WebPushChannel
from app.storage import SnapshotStorage
from app import web
from app.web import app


ROOT = Path(__file__).resolve().parents[1]
SETTINGS_TEMPLATE = ROOT / "app" / "templates" / "settings" / "notifications.html"
SETTINGS_JS = ROOT / "app" / "static" / "js" / "settings.js"


VALID_SUBSCRIPTION = {
    "endpoint": "https://push.example.test/send/abc123",
    "expirationTime": None,
    "keys": {"p256dh": "public-client-key", "auth": "auth-secret"},
}


def make_storage(tmp_path: Path) -> SnapshotStorage:
    return SnapshotStorage(str(tmp_path / "docsight.db"), max_days=7)


def make_config(tmp_path: Path, **overrides) -> ConfigManager:
    cfg = ConfigManager(str(tmp_path / "config"))
    data = {
        "notify_pwa_push_enabled": True,
        "notify_pwa_push_vapid_public_key": "BEl0-public-key",
        "notify_pwa_push_vapid_private_key": "private-vapid-key",
        "notify_pwa_push_vapid_subject": "mailto:admin@example.test",
        "notify_min_severity": "warning",
        "notify_cooldown": 3600,
        "notify_cooldowns": "{}",
    }
    data.update(overrides)
    cfg.save(data)
    return cfg


def test_pwa_push_subscription_storage_upserts_lists_and_deletes(tmp_path):
    storage = make_storage(tmp_path)

    created = storage.upsert_pwa_push_subscription(VALID_SUBSCRIPTION, user_agent="Firefox")
    updated = storage.upsert_pwa_push_subscription(
        {**VALID_SUBSCRIPTION, "keys": {"p256dh": "updated", "auth": "auth-secret"}},
        user_agent="Firefox Updated",
    )

    assert created["endpoint"] == VALID_SUBSCRIPTION["endpoint"]
    assert updated["id"] == created["id"]
    subscriptions = storage.list_pwa_push_subscriptions()
    assert len(subscriptions) == 1
    assert subscriptions[0]["subscription"]["keys"]["p256dh"] == "updated"
    assert subscriptions[0]["user_agent"] == "Firefox Updated"

    assert storage.delete_pwa_push_subscription(VALID_SUBSCRIPTION["endpoint"]) is True
    assert storage.list_pwa_push_subscriptions() == []


def test_pwa_push_status_endpoint_exposes_public_key_without_private_key(tmp_path):
    storage = make_storage(tmp_path)
    storage.upsert_pwa_push_subscription(VALID_SUBSCRIPTION, user_agent="Firefox")
    cfg = make_config(tmp_path)
    web.init_storage(storage)
    web.init_config(cfg)

    resp = app.test_client().get("/api/notifications/pwa/status")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data == {
        "enabled": True,
        "configured": True,
        "public_key": "BEl0-public-key",
        "subscription_count": 1,
    }
    assert "private" not in json.dumps(data).lower()
    assert "private-vapid-key" not in json.dumps(data)


def test_pwa_push_subscribe_and_unsubscribe_api_validates_subscription(tmp_path):
    storage = make_storage(tmp_path)
    cfg = make_config(tmp_path)
    web.init_storage(storage)
    web.init_config(cfg)
    client = app.test_client()

    bad = client.post("/api/notifications/pwa/subscribe", json={"endpoint": "missing keys"})
    assert bad.status_code == 400

    insecure_subscription = {**VALID_SUBSCRIPTION, "endpoint": "http://push.example.test/send/abc123"}
    insecure = client.post("/api/notifications/pwa/subscribe", json={"subscription": insecure_subscription})
    assert insecure.status_code == 400
    assert "HTTPS" in insecure.get_json()["error"]

    subscribed = client.post("/api/notifications/pwa/subscribe", json={"subscription": VALID_SUBSCRIPTION})
    assert subscribed.status_code == 200
    assert subscribed.get_json()["success"] is True
    assert storage.count_pwa_push_subscriptions() == 1

    unsubscribed = client.post(
        "/api/notifications/pwa/unsubscribe",
        json={"endpoint": VALID_SUBSCRIPTION["endpoint"]},
    )
    assert unsubscribed.status_code == 200
    assert unsubscribed.get_json()["success"] is True
    assert storage.count_pwa_push_subscriptions() == 0


def test_config_masks_pwa_vapid_private_key(tmp_path):
    cfg = make_config(tmp_path)

    masked = cfg.get_all(mask_secrets=True)

    assert masked["notify_pwa_push_vapid_private_key"] == PASSWORD_MASK
    assert cfg.get("notify_pwa_push_vapid_private_key") == "private-vapid-key"


def test_web_push_channel_sends_safe_payload_to_all_subscriptions(tmp_path):
    storage = make_storage(tmp_path)
    storage.upsert_pwa_push_subscription(VALID_SUBSCRIPTION, user_agent="Firefox")
    channel = WebPushChannel(
        storage=storage,
        vapid_private_key="private-vapid-key",
        vapid_subject="mailto:admin@example.test",
    )

    with patch("app.notifier.webpush") as mock_webpush:
        assert channel.send({
            "severity": "critical",
            "event_type": "snr_change",
            "timestamp": "2026-05-22T10:00:00Z",
            "message": "SNR dropped",
            "details": {"secret_marker": "DO-NOT-PUSH", "threshold": 33.0},
        }) is True

    assert mock_webpush.call_count == 1
    call = mock_webpush.call_args.kwargs
    assert call["subscription_info"] == VALID_SUBSCRIPTION
    pushed = json.loads(call["data"])
    assert pushed["title"] == "DOCSight critical: Snr Change"
    assert pushed["body"] == "SNR dropped"
    assert pushed["url"] == "/?source=pwa#events"
    assert "DO-NOT-PUSH" not in call["data"]
    assert "threshold" not in call["data"]


def test_web_push_channel_removes_expired_subscriptions(tmp_path):
    storage = make_storage(tmp_path)
    storage.upsert_pwa_push_subscription(VALID_SUBSCRIPTION, user_agent="Firefox")
    channel = WebPushChannel(storage, "private-vapid-key", "mailto:admin@example.test")
    gone = RuntimeError("expired")
    gone.response = MagicMock(status_code=410)

    with patch("app.notifier.webpush", side_effect=gone):
        assert channel.send({"severity": "warning", "event_type": "test", "message": "Test"}) is False

    assert storage.list_pwa_push_subscriptions() == []


def test_settings_exposes_explicit_pwa_push_controls_without_auto_permission_prompt():
    template = SETTINGS_TEMPLATE.read_text(encoding="utf-8")
    js = SETTINGS_JS.read_text(encoding="utf-8")

    for needle in [
        'id="pwa-push-card"',
        'id="notify_pwa_push_enabled"',
        'id="notify_pwa_push_vapid_public_key"',
        'id="notify_pwa_push_vapid_private_key"',
        'id="notify_pwa_push_vapid_subject"',
        'id="pwa-push-status"',
        'onclick="subscribePwaPush()"',
        'onclick="unsubscribePwaPush()"',
    ]:
        assert needle in template
    assert 'data-saved-secret="true"' in template
    assert "function subscribePwaPush()" in js
    assert "function unsubscribePwaPush()" in js
    assert "refreshPwaPushStatus();" in js
    assert "pushManager.getSubscription()" in js
    assert "This browser is not subscribed yet" in js
    assert "Notification.requestPermission()" in js
    assert js.index("function subscribePwaPush()") < js.index("Notification.requestPermission()")


def test_dispatcher_adds_pwa_channel_and_reuses_severity_and_cooldown_controls(tmp_path):
    storage = make_storage(tmp_path)
    storage.upsert_pwa_push_subscription(VALID_SUBSCRIPTION, user_agent="Firefox")
    cfg = make_config(
        tmp_path,
        notify_min_severity="warning",
        notify_cooldowns=json.dumps({"disabled_event": 0}),
    )
    dispatcher = NotificationDispatcher(cfg, storage=storage)

    with patch("app.notifier.webpush") as mock_webpush:
        dispatcher.dispatch([
            {"timestamp": "2026-05-22T10:00:00Z", "severity": "info", "event_type": "low_info", "message": "Below", "details": {}},
            {"timestamp": "2026-05-22T10:00:01Z", "severity": "warning", "event_type": "disabled_event", "message": "Disabled", "details": {}},
            {"timestamp": "2026-05-22T10:00:02Z", "severity": "warning", "event_type": "signal_warning", "message": "Sent", "details": {}},
        ])
        dispatcher.dispatch([
            {"timestamp": "2026-05-22T10:00:03Z", "severity": "warning", "event_type": "signal_warning", "message": "Suppressed", "details": {}},
        ])

    assert mock_webpush.call_count == 1
    sent = json.loads(mock_webpush.call_args.kwargs["data"])
    assert sent["body"] == "Sent"
