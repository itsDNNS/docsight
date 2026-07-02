"""API token management mixin."""

import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from werkzeug.security import generate_password_hash, check_password_hash

from ..tz import utc_now


_TOKEN_PREFIX_LENGTH = 8
_LAST_USED_WRITE_INTERVAL = timedelta(seconds=60)


def _parse_utc_timestamp(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _should_refresh_last_used(previous, current):
    previous_dt = _parse_utc_timestamp(previous)
    current_dt = _parse_utc_timestamp(current)
    if previous_dt is None or current_dt is None:
        return True
    return current_dt - previous_dt >= _LAST_USED_WRITE_INTERVAL


class TokenMethods:

    def create_api_token(self, name):
        """Create a new API token. Returns (token_id, plaintext_token)."""
        raw = secrets.token_urlsafe(48)
        plaintext = "dsk_" + raw
        prefix = plaintext[:_TOKEN_PREFIX_LENGTH]
        token_hash = generate_password_hash(plaintext)
        created_at = utc_now()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO api_tokens (name, token_hash, token_prefix, created_at) VALUES (?, ?, ?, ?)",
                (name, token_hash, prefix, created_at),
            )
            return cur.lastrowid, plaintext

    def validate_api_token(self, token):
        """Validate a Bearer token. Returns token info dict or None."""
        prefix = (token or "")[:_TOKEN_PREFIX_LENGTH]
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT id, name, token_hash, token_prefix, created_at, last_used_at
                FROM api_tokens
                WHERE revoked = 0 AND token_prefix = ?
                """,
                (prefix,),
            ).fetchall()
            for row in rows:
                if check_password_hash(row["token_hash"], token):
                    now = utc_now()
                    if _should_refresh_last_used(row["last_used_at"], now):
                        conn.execute("UPDATE api_tokens SET last_used_at = ? WHERE id = ?", (now, row["id"]))
                    return {
                        "id": row["id"],
                        "name": row["name"],
                        "token_prefix": row["token_prefix"],
                        "created_at": row["created_at"],
                    }
        return None

    def get_api_tokens(self):
        """Return list of all tokens (without hashes) for UI display."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, name, token_prefix, created_at, last_used_at, revoked FROM api_tokens ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def revoke_api_token(self, token_id):
        """Soft-revoke a token. Returns True if a token was revoked."""
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE api_tokens SET revoked = 1 WHERE id = ? AND revoked = 0",
                (token_id,),
            )
            return cur.rowcount > 0
