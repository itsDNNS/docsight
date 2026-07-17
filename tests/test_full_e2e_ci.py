"""Regression checks for the full browser E2E workflow contract."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "full-e2e.yml"


def test_full_e2e_workflow_contract():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert workflow.count("cron:") == 1
    assert '- cron: "23 3 * * 1"' in workflow
    assert "workflow_dispatch:" in workflow
    assert "types: [opened, synchronize, reopened, labeled]" in workflow

    trigger_block = workflow[workflow.index("on:") : workflow.index("permissions:")]
    assert "paths:" not in trigger_block

    assert "if: github.event_name == 'pull_request'" in workflow
    assert "pull-requests: read" in workflow
    assert "browser: ${{ steps.filter.outputs.browser }}" in workflow
    assert (
        "dorny/paths-filter@7b450fff21473bca461d4b92ce414b9d0420d706"
        in workflow
    )
    for path in (
        "app/templates/**",
        "app/static/**",
        "app/modules/**",
        "app/web.py",
        "tests/e2e/**",
        "requirements.txt",
        ".github/workflows/full-e2e.yml",
    ):
        assert path in workflow

    assert "!cancelled()" in workflow
    assert "needs: changes" in workflow
    assert "contains(github.event.pull_request.labels.*.name, 'full-e2e')" in workflow
    assert "needs.changes.outputs.browser == 'true'" in workflow
    assert "TZ=UTC python -m pytest -q tests/e2e --tb=short" in workflow
    assert "actions/upload-artifact" in workflow
    assert "if: always()" in workflow
    assert "name: full-e2e-artifacts" in workflow
    assert "if-no-files-found: ignore" in workflow
    assert "test-results/" in workflow
    assert "playwright-report/" in workflow
    assert "tests/e2e/screenshots/" in workflow
