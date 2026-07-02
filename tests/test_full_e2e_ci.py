"""Regression checks for the scheduled/labeled full browser E2E gate."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "full-e2e.yml"


def test_full_e2e_workflow_is_scheduled_and_label_gated():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "schedule:" in workflow
    assert "workflow_dispatch:" in workflow
    assert "contains(github.event.pull_request.labels.*.name, 'full-e2e')" in workflow
    assert "TZ=UTC python -m pytest -q tests/e2e --tb=short" in workflow
    assert "actions/upload-artifact" in workflow
    assert "tests/e2e/screenshots/" in workflow
