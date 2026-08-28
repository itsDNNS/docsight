"""Schema migration for persisted German TKG claim drafts."""

from app.storage.migrations import Migration, table_columns, table_exists

from .rules_data import RULESET_DE_TKG58


_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS de_tkg_claim_drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'completed')),
    window_from TEXT,
    window_to TEXT,
    origin TEXT NOT NULL DEFAULT 'manual' CHECK (origin IN ('manual', 'telemetry', 'incident')),
    fault_report_received_date TEXT,
    fault_report_channel TEXT,
    ticket_ref TEXT,
    restored_date TEXT,
    monthly_fee_cents INTEGER,
    confirmed_days_json TEXT NOT NULL DEFAULT '[]',
    eligibility_json TEXT NOT NULL DEFAULT '{}',
    prior_credit_json TEXT NOT NULL DEFAULT '{}',
    letter_text TEXT,
    rules_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_demo INTEGER NOT NULL DEFAULT 0
)
"""


_REQUIRED_COLUMNS = {
    "id", "status", "window_from", "window_to", "origin",
    "fault_report_received_date", "fault_report_channel", "ticket_ref",
    "restored_date", "monthly_fee_cents", "confirmed_days_json",
    "eligibility_json", "prior_credit_json", "letter_text", "rules_version",
    "created_at", "updated_at", "is_demo",
}


def _applied(conn):
    return table_exists(conn, "de_tkg_claim_drafts") and _REQUIRED_COLUMNS <= table_columns(
        conn, "de_tkg_claim_drafts"
    )


def _apply(conn):
    conn.execute(_CREATE_TABLE)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_de_tkg_claim_drafts_updated "
        "ON de_tkg_claim_drafts(updated_at DESC, id DESC)"
    )


def _rules_version_applied(_conn):
    return False


def _apply_rules_version(conn):
    conn.execute(
        "UPDATE de_tkg_claim_drafts SET rules_version = ?, letter_text = NULL "
        "WHERE rules_version <> ?",
        (RULESET_DE_TKG58.rules_version, RULESET_DE_TKG58.rules_version),
    )


MIGRATIONS = (
    Migration("de-tkg-compensation-0001-baseline", _apply, _applied),
    Migration(
        "de-tkg-compensation-0002-rules-version",
        _apply_rules_version,
        _rules_version_applied,
    ),
)
