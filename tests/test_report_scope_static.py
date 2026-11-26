"""Locale catalog contract for the Evidence Journey fixed report window handoff."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_I18N = ROOT / "app/modules/reports/i18n"


def test_report_scope_copy_is_translated_for_all_shipped_locales() -> None:
    paths = sorted(REPORT_I18N.glob("*.json"))
    assert len(paths) == 24
    catalogs = {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in paths}
    added = {
        "report_fixed_period_title",
        "report_change_problem_window",
        "report_readiness_title",
        "report_status_present",
        "report_status_stale",
        "report_status_missing",
        "report_status_optional",
        "report_status_not_applicable",
        "report_status_unavailable",
        "report_supporting_evidence_title",
        "report_supporting_evidence_hint",
        "report_window_mismatch",
        "report_fixed_scope_invalid",
    }

    for language, catalog in catalogs.items():
        if language != "en":
            assert catalog["report_window_mismatch"] != catalogs["en"]["report_window_mismatch"], language
            assert sum(catalog[key] != catalogs["en"][key] for key in added) >= 12, language
