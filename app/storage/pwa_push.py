"""Storage helpers for browser PWA Web Push subscriptions."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import urlparse


class PwaPushMixin:
    """Persist browser Push API subscriptions."""

    @staticmethod
    def _utc_now_iso() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _normalize_subscription(subscription: dict) -> dict:
        if not isinstance(subscription, dict):
            raise ValueError("Subscription must be an object")
        endpoint = str(subscription.get("endpoint") or "").strip()
        keys = subscription.get("keys") or {}
        if not endpoint:
            raise ValueError("Subscription endpoint is required")
        parsed_endpoint = urlparse(endpoint)
        if parsed_endpoint.scheme != "https" or not parsed_endpoint.netloc:
            raise ValueError("Subscription endpoint must be an HTTPS URL")
        if not isinstance(keys, dict) or not keys.get("p256dh") or not keys.get("auth"):
            raise ValueError("Subscription keys are required")
        normalized = dict(subscription)
        normalized["endpoint"] = endpoint
        normalized["keys"] = {"p256dh": str(keys["p256dh"]), "auth": str(keys["auth"])}
        if "expirationTime" in subscription:
            normalized["expirationTime"] = subscription.get("expirationTime")
        return normalized

    def upsert_pwa_push_subscription(self, subscription: dict, user_agent: str = "") -> dict:
        normalized = self._normalize_subscription(subscription)
        endpoint = normalized["endpoint"]
        now = self._utc_now_iso()
        payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO pwa_push_subscriptions
                    (endpoint, subscription_json, user_agent, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(endpoint) DO UPDATE SET
                    subscription_json = excluded.subscription_json,
                    user_agent = excluded.user_agent,
                    updated_at = excluded.updated_at
                """,
                (endpoint, payload, user_agent or "", now, now),
            )
            row = conn.execute(
                """
                SELECT id, endpoint, subscription_json, user_agent, created_at, updated_at
                FROM pwa_push_subscriptions
                WHERE endpoint = ?
                """,
                (endpoint,),
            ).fetchone()
        return self._row_to_pwa_subscription(row)

    @staticmethod
    def _row_to_pwa_subscription(row) -> dict:
        return {
            "id": row[0],
            "endpoint": row[1],
            "subscription": json.loads(row[2]),
            "user_agent": row[3] or "",
            "created_at": row[4],
            "updated_at": row[5],
        }

    def list_pwa_push_subscriptions(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, endpoint, subscription_json, user_agent, created_at, updated_at
                FROM pwa_push_subscriptions
                ORDER BY id ASC
                """
            ).fetchall()
        return [self._row_to_pwa_subscription(row) for row in rows]

    def count_pwa_push_subscriptions(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM pwa_push_subscriptions").fetchone()
        return int(row[0] if row else 0)

    def delete_pwa_push_subscription(self, endpoint: str) -> bool:
        endpoint = str(endpoint or "").strip()
        if not endpoint:
            return False
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM pwa_push_subscriptions WHERE endpoint = ?", (endpoint,))
        return cur.rowcount > 0
