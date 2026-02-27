"""API token management mixin."""

import secrets
import sqlite3

from werkzeug.security import generate_password_hash, check_password_hash

from ..tz import utc_now


class TokenMixin:

    def create_api_token(self, name):
        """Create a new API token. Returns (token_id, plaintext_token)."""
        raw = secrets.token_urlsafe(48)
        plaintext = "dsk_" + raw
        prefix = plaintext[:8]
        token_hash = generate_password_hash(plaintext)
        created_at = utc_now()
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "INSERT INTO api_tokens (name, token_hash, token_prefix, created_at) VALUES (?, ?, ?, ?)",
                (name, token_hash, prefix, created_at),
            )
            return cur.lastrowid, plaintext

    def validate_api_token(self, token):
        """Validate a Bearer token. Returns token info dict or None."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, name, token_hash, token_prefix, created_at, last_used_at FROM api_tokens WHERE revoked = 0"
            ).fetchall()
            for row in rows:
                if check_password_hash(row["token_hash"], token):
                    now = utc_now()
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
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, name, token_prefix, created_at, last_used_at, revoked FROM api_tokens ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def revoke_api_token(self, token_id):
        """Soft-revoke a token. Returns True if a token was revoked."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "UPDATE api_tokens SET revoked = 1 WHERE id = ? AND revoked = 0",
                (token_id,),
            )
            return cur.rowcount > 0
