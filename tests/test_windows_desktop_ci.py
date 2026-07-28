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
        "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
        "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97",
        "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
        "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c",
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
    assert 'gh release upload "$TAG_NAME" --repo "$GITHUB_REPOSITORY"' in release_block
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


def test_smoke_script_runs_copied_bundle_from_hostile_temp_path():
    script = SMOKE_SCRIPT.read_text(encoding="utf-8")

    smoke_root = re.search(r"(?m)^\$SmokeRoot\s*=(?P<assignment>.+)$", script)
    assert smoke_root
    smoke_root_assignment = smoke_root.group("assignment")
    assert '"DOCSight smoke "' in smoke_root_assignment
    code_point = re.search(r"\[char\]0x(?P<hex>[0-9A-Fa-f]+)", smoke_root_assignment)
    assert code_point
    assert int(code_point.group("hex"), 16) > 127
    assert "Copy-Item -LiteralPath $BundleDir" in script
    assert "$Executable = Join-Path $LaunchBundleDir" in script
    assert "-WorkingDirectory $LaunchBundleDir" in script
    assert script.index("Copy-Item -LiteralPath $BundleDir") < script.index(
        "Start-Process -FilePath $Executable"
    )


def test_smoke_script_proves_reports_route_before_seeding_generic_state():
    script = SMOKE_SCRIPT.read_text(encoding="utf-8")

    assert "/api/report" in script
    assert "$EmptyReportResponse.StatusCode -ne 404" in script
    assert '$EmptyReportPayload.error -ne "No data available"' in script
    assert "/api/config" in script
    assert 'modem_type = "generic"' in script
    assert "$SetupPayload.success -ne $true" in script
    assert script.index("$EmptyReportResponse") < script.index("$SetupResponse")


def test_smoke_script_checks_real_pdf_response_from_packaged_process():
    script = SMOKE_SCRIPT.read_text(encoding="utf-8")

    assert "Add-Type -AssemblyName System.Net.Http" in script
    assert "$PdfResponse.ContentType" in script
    assert '"application/pdf"' in script
    assert "$PdfResponse.Bytes" in script
    assert '"%PDF-"' in script
    assert script.index("$SetupResponse") < script.index("$PdfResponse")


def test_smoke_script_rejects_reports_import_errors_and_preserves_cleanup():
    script = SMOKE_SCRIPT.read_text(encoding="utf-8")

    assert "docsight\\.reports" in script
    assert "failed to import routes" in script
    assert "No module named" in script
    assert "unittest" in script
    assert script.index("$PdfResponse.ContentType") < script.index("$LogText")
    assert re.search(
        r"}\s*catch\s*{\s*Write-SmokeLog\s*throw\s*}\s*finally\s*{",
        script,
    )
    assert "Stop-Process -Id $Process.Id -Force" in script
    assert "$env:LOCALAPPDATA = $PreviousLocalAppData" in script
    assert "Remove-Item -Recurse -Force $SmokeRoot" in script


def test_step_block_helper_does_not_capture_next_step():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    build_block = named_step_block(workflow, "Build portable package")

    assert "Smoke-test built package" not in build_block
