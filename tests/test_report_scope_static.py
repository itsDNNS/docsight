"""Static contracts for the Evidence Journey fixed report window handoff."""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_JS = ROOT / "app/modules/evidence/static/main.js"
REPORT_JS = ROOT / "app/static/js/utils.js"
REPORT_TEMPLATE = ROOT / "app/templates/index.html"
REPORT_I18N = ROOT / "app/modules/reports/i18n"


def _function(source: str, name: str, next_name: str) -> str:
    match = re.search(
        rf"function {re.escape(name)}\([^)]*\) \{{(?P<body>.*?)\n\}}\s*function {re.escape(next_name)}\(",
        source,
        re.DOTALL,
    )
    assert match, f"could not isolate {name}"
    return match.group("body")


def test_evidence_report_action_passes_the_canonical_payload_scope() -> None:
    source = EVIDENCE_JS.read_text(encoding="utf-8")

    assert "openReportModal(_evidenceReportScope(_evidenceLastPayload))" in source
    assert "window: payload.window" in source
    assert "items: payload.items" in source
    assert "summary: payload.summary" in source
    assert "incident_id: payload.window.incident_id" in source
    assert "openReportModal();" not in _function(source, "_evidenceRunAction", "_evidenceBuildUrl")


def test_report_modal_keeps_direct_rolling_and_scoped_fixed_modes_separate() -> None:
    source = REPORT_JS.read_text(encoding="utf-8")

    assert "function openReportModal(scope)" in source
    assert "reportScope = scope === undefined ? null : scope;" in source
    assert "report-days-field" in source
    assert "report-fixed-scope" in source
    assert "reportScope && reportScope.window" in source
    assert "fixedScope.hidden = !isFixed" in source
    assert "daysField.hidden = isFixed" in source
    assert "days.disabled = isFixed" in source


def test_complaint_and_pdf_share_exact_window_parameter_construction() -> None:
    source = REPORT_JS.read_text(encoding="utf-8")
    builder = _function(source, "buildReportRequestParams", "generateComplaint")
    complaint = _function(source, "generateComplaint", "generateBnetzComplaint")
    pdf = _function(source, "downloadReport", "copyExport")

    assert "params.set('from', reportScope.window.from)" in builder
    assert "params.set('to', reportScope.window.to)" in builder
    assert "params.set('days'" in builder
    assert "if (reportScope)" in builder
    assert "else" in builder
    assert "buildReportRequestParams()" in complaint
    assert "buildReportRequestParams()" in pdf
    assert "params.set('days'" not in complaint
    assert "params.set('days'" not in pdf


def test_fixed_complaint_response_mismatch_blocks_preview_on_step_one() -> None:
    source = REPORT_JS.read_text(encoding="utf-8")

    assert "function reportResponseMatchesScope(data)" in source
    assert "data.window.from === reportScope.window.from" in source
    assert "data.window.to === reportScope.window.to" in source
    assert "throw new Error(T.report_window_mismatch" in source
    assert source.index("reportResponseMatchesScope(data)") < source.index(
        "document.getElementById('report-step1').style.display = 'none'"
    )


def test_change_window_closes_then_uses_evidence_owned_focus_callback() -> None:
    source = REPORT_JS.read_text(encoding="utf-8")
    evidence = EVIDENCE_JS.read_text(encoding="utf-8")
    change = _function(source, "changeReportProblemWindow", "resetReportModalState")

    assert "window.DOCSightModal.close('report-modal')" in change
    assert "scope.changeWindow()" in change
    assert change.index("window.DOCSightModal.close") < change.index("scope.changeWindow()")
    assert "switchView('evidence')" in evidence
    assert "payload.window.kind === 'incident' ? 'evidence-incident-id' : 'evidence-from'" in evidence
    assert ".focus({preventScroll: false})" in evidence


def test_fixed_scope_markup_is_semantic_live_and_supporting_evidence_is_separate() -> None:
    template = REPORT_TEMPLATE.read_text(encoding="utf-8")

    assert 'id="report-fixed-scope"' in template
    assert 'aria-labelledby="report-fixed-period-title"' in template
    assert 'id="report-period-from"' in template and "<time" in template
    assert 'id="report-period-to"' in template
    assert 'id="report-readiness-list"' in template
    assert 'onclick="changeReportProblemWindow()"' in template
    assert 'id="report-supporting-evidence-title"' in template
    assert 'id="report-builder-status"' in template and 'aria-live="polite"' in template
    assert 'id="report-complaint-text"' in template
    assert "report_builder_privacy_note" in template


def test_report_scope_catalog_keys_match_for_all_shipped_locales() -> None:
    paths = sorted(REPORT_I18N.glob("*.json"))
    assert len(paths) == 24
    catalogs = {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in paths}
    expected_keys = set(catalogs["en"])
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

    assert added <= expected_keys
    for language, catalog in catalogs.items():
        assert set(catalog) == expected_keys, language
        assert all(catalog[key].strip() for key in added), language
        if language != "en":
            assert catalog["report_window_mismatch"] != catalogs["en"]["report_window_mismatch"], language
            assert sum(catalog[key] != catalogs["en"][key] for key in added) >= 12, language
