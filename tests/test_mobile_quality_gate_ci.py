"""Regression checks for the mobile viewport quality gate wiring."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "test.yml"
README = ROOT / "README.md"


def test_ci_runs_focused_mobile_viewport_quality_gate():
    """CI should run the dedicated mobile Playwright gate on PRs and main pushes."""
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "mobile-e2e:" in workflow
    assert "pytest-playwright==0.7.2" in workflow
    assert "playwright==1.58.0" in workflow
    assert "python -m playwright install --with-deps chromium" in workflow
    assert "tests/e2e/test_mobile_quality_gate.py" in workflow


def test_mobile_quality_gate_is_documented_for_local_runs():
    """Developers should have a local command for the same mobile gate CI uses."""
    readme = README.read_text(encoding="utf-8")

    assert "Mobile viewport quality gate" in readme
    assert "pytest-playwright==0.7.2 playwright==1.58.0" in readme
    assert "pytest -q tests/e2e/test_mobile_quality_gate.py" in readme
