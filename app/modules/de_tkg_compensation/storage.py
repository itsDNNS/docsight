"""Isolated main-database storage for German TKG claim drafts."""

from __future__ import annotations

import json

from app.storage.migrations import run_migrations
from app.storage.sqlite import open_read, write_transaction
from app.tz import utc_now

from .migrations import MIGRATIONS
from .rules_data import RULESET_DE_TKG58


_DB_FIELDS = (
    "status", "window_from", "window_to", "origin",
    "fault_report_received_date", "fault_report_channel", "ticket_ref",
    "restored_date", "monthly_fee_cents", "confirmed_days_json",
    "eligibility_json", "prior_credit_json", "letter_text", "rules_version",
)
_JSON_FIELDS = {
    "confirmed_days_json": "confirmed_days",
    "eligibility_json": "eligibility",
    "prior_credit_json": "prior_credit",
}
_LETTER_FACT_DB_FIELDS = set(_DB_FIELDS) - {"status", "letter_text"}


class ClaimStorage:
    def __init__(self, db_path: str):
        self.db_path = db_path
        run_migrations(db_path, MIGRATIONS)

    @staticmethod
    def _encode(payload: dict) -> dict:
        values = dict(payload)
        for db_field, api_field in _JSON_FIELDS.items():
            if api_field in values:
                values[db_field] = json.dumps(
                    values.pop(api_field), ensure_ascii=False, sort_keys=True,
                    separators=(",", ":"),
                )
        return {key: values[key] for key in _DB_FIELDS if key in values}

    @staticmethod
    def _decode(row) -> dict | None:
        if row is None:
            return None
        result = dict(row)
        for db_field, api_field in _JSON_FIELDS.items():
            raw = result.pop(db_field, None)
            result[api_field] = json.loads(raw or ("[]" if api_field == "confirmed_days" else "{}"))
        result["is_demo"] = bool(result.get("is_demo"))
        return result

    def create(self, payload: dict, *, is_demo: bool) -> dict:
        now = utc_now()
        values = self._encode(payload)
        values.setdefault("status", "draft")
        values.setdefault("origin", "manual")
        values.setdefault("confirmed_days_json", "[]")
        values.setdefault("eligibility_json", "{}")
        values.setdefault("prior_credit_json", "{}")
        values.setdefault("rules_version", RULESET_DE_TKG58.rules_version)
        values.update({"created_at": now, "updated_at": now, "is_demo": int(is_demo)})
        columns = tuple(values)
        placeholders = ", ".join("?" for _ in columns)
        with write_transaction(self.db_path) as conn:
            cursor = conn.execute(
                f"INSERT INTO de_tkg_claim_drafts ({', '.join(columns)}) VALUES ({placeholders})",  # noqa: S608
                tuple(values[column] for column in columns),
            )
            claim_id = cursor.lastrowid
        return self.get(claim_id)

    def list(self) -> list[dict]:
        with open_read(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM de_tkg_claim_drafts ORDER BY updated_at DESC, id DESC"
            ).fetchall()
        return [self._decode(row) for row in rows]

    def get(self, claim_id: int) -> dict | None:
        with open_read(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM de_tkg_claim_drafts WHERE id = ?", (claim_id,)
            ).fetchone()
        return self._decode(row)

    def update(self, claim_id: int, payload: dict) -> dict | None:
        values = self._encode(payload)
        if not values:
            return self.get(claim_id)
        with write_transaction(self.db_path) as conn:
            current = conn.execute(
                "SELECT * FROM de_tkg_claim_drafts WHERE id = ?", (claim_id,)
            ).fetchone()
            if current is None:
                return None
            if any(
                field in values and values[field] != current[field]
                for field in _LETTER_FACT_DB_FIELDS
            ):
                values["letter_text"] = None
                values["status"] = "draft"
            values["updated_at"] = utc_now()
            assignments = ", ".join(f"{column} = ?" for column in values)
            changed = conn.execute(
                f"UPDATE de_tkg_claim_drafts SET {assignments} WHERE id = ?",  # noqa: S608
                (*values.values(), claim_id),
            ).rowcount
        return self.get(claim_id) if changed else None

    def delete(self, claim_id: int) -> bool:
        with write_transaction(self.db_path) as conn:
            changed = conn.execute(
                "DELETE FROM de_tkg_claim_drafts WHERE id = ?", (claim_id,)
            ).rowcount
        return changed > 0
