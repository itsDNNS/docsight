"""Static checks for the Windows Desktop Preview GitHub Actions workflow."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "windows-desktop.yml"
SMOKE_SCRIPT = ROOT / "packaging" / "windows" / "smoke_test.ps1"


def named_step_block(workflow_text: str, step_name: str) -> str:
    match = re.search(
        rf"(?m)^      - name: {re.escape(step_name)}\n(?P<body>(?:        .*\n)*)",
        workflow_text,
    )
    assert match, f"step not found: {step_name}"
    return match.group("body")


def test_windows_desktop_workflow_triggers_and_permissions():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "pull_request:" in workflow
    assert "push:" in workflow
    assert "branches: [main]" in workflow
    assert "release:" in workflow
    assert "types: [published]" in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "attach-release-assets:" in workflow
    assert "permissions:\n      contents: write" in workflow


def test_windows_desktop_workflow_scopes_push_paths():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    for required_path in (
        "app/**",
        "packaging/windows/**",
        "requirements.txt",
        ".github/workflows/windows-desktop.yml",
    ):
        assert required_path in workflow


def test_windows_desktop_workflow_uses_sha_pinned_actions():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    for action in (
        "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0",
        "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1",
        "actions/upload-artifact@b7c566a772e6b6bfb58ed0dc250532a479d7789f",
        "actions/download-artifact@018cc2cf5baa6db3ef3c5f8a56943fffe632ef53",
    ):
        assert action in workflow

    assert not re.search(r"uses: actions/[\w-]+@v\d+", workflow)


def test_windows_desktop_workflow_builds_smokes_and_uploads_bundle():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    build_block = named_step_block(workflow, "Build portable package")
    smoke_block = named_step_block(workflow, "Smoke-test built package")
    upload_block = named_step_block(workflow, "Upload desktop artifact")

    assert "packaging/windows/build.ps1" in build_block
    assert "-Version \"${{ steps.version.outputs.version }}\"" in build_block
    assert "packaging/windows/smoke_test.ps1" in smoke_block
    assert "-BundleDir packaging/windows/dist/DOCSight" in smoke_block
    assert "-ExpectedVersion \"${{ steps.version.outputs.version }}\"" in smoke_block
    assert "DOCSight-Desktop-Preview-win64-*.zip" in upload_block
    assert "DOCSight-Desktop-Preview-win64-*.zip.sha256" in upload_block


def test_windows_desktop_workflow_attaches_release_assets():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    release_block = named_step_block(workflow, "Attach assets to release")
    assert "GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}" in release_block
    assert "TAG_NAME: ${{ github.event.release.tag_name }}" in release_block
    assert "gh release upload" in release_block
    assert "release-assets/*.zip" in release_block
    assert "release-assets/*.sha256" in release_block


def test_smoke_script_launches_built_exe_and_checks_loopback_health():
    script = SMOKE_SCRIPT.read_text(encoding="utf-8")

    assert "DOCSight.exe" in script
    assert "Start-Process -FilePath $Executable" in script
    assert "Invoke-RestMethod -Uri $HealthUrl" in script
    assert "$Payload.status -ne \"ok\"" in script
    assert "$Payload.version -ne $ExpectedVersion" in script
    assert "Get-NetTCPConnection -State Listen -LocalPort $Port" in script
    assert "LocalAddress -eq \"127.0.0.1\"" in script
    assert "DOCSIGHT_SKIP_BROWSER" in script
    assert "python -m app.main" not in script


def test_step_block_helper_does_not_capture_next_step():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    build_block = named_step_block(workflow, "Build portable package")

    assert "Smoke-test built package" not in build_block
