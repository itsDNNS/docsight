"""Static checks for the Windows Desktop Preview GitHub Actions workflow."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "windows-desktop.yml"
SMOKE_SCRIPT = ROOT / "packaging" / "windows" / "smoke_test.ps1"


def named_step_block(workflow_text: str, step_name: str) -> str:
    match = re.search(
        rf"(?ms)^      - name: {re.escape(step_name)}\n"
        r"(?P<body>.*?)(?=^      - name: |\Z)",
        workflow_text,
    )
    assert match, f"step not found: {step_name}"
    return match.group("body")


def named_step_run_script(workflow_text: str, step_name: str) -> str:
    block = named_step_block(workflow_text, step_name)
    marker = "        run: |\n"
    assert marker in block, f"run script not found: {step_name}"
    return textwrap.dedent(block.split(marker, maxsplit=1)[1])


def run_release_verification(
    tmp_path: Path,
    assets: list[str],
    *,
    gh_exit_codes: list[int] | None = None,
    download_exit_code: int = 0,
    published_checksum: str | None = None,
) -> subprocess.CompletedProcess[str]:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    script = named_step_run_script(workflow, "Verify published release assets")
    zip_content = b"deterministic Windows Preview ZIP fixture\n"
    expected_zip_hash = hashlib.sha256(zip_content).hexdigest()
    gh_stub = tmp_path / "gh"
    gh_stub.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$1" == "release" && "$2" == "view" ]]; then\n'
        '  attempt="$(<"$GH_STUB_ATTEMPT_FILE")"\n'
        '  attempt=$((attempt + 1))\n'
        '  printf "%s" "$attempt" > "$GH_STUB_ATTEMPT_FILE"\n'
        '  IFS=, read -r -a exit_codes <<< "$GH_STUB_EXIT_CODES"\n'
        '  exit_code_index=$((attempt - 1))\n'
        '  if ((exit_code_index >= ${#exit_codes[@]})); then\n'
        '    exit_code_index=$((${#exit_codes[@]} - 1))\n'
        "  fi\n"
        '  exit_code="${exit_codes[$exit_code_index]}"\n'
        '  if ((exit_code == 0)); then\n'
        '    printf "%s" "$GH_STUB_ASSETS"\n'
        "  fi\n"
        '  exit "$exit_code"\n'
        "fi\n"
        'if [[ "$1" == "release" && "$2" == "download" ]]; then\n'
        '  if ((GH_STUB_DOWNLOAD_EXIT_CODE != 0)); then\n'
        '    exit "$GH_STUB_DOWNLOAD_EXIT_CODE"\n'
        "  fi\n"
        "  shift 3\n"
        '  download_dir=""\n'
        "  patterns=()\n"
        "  while (($#)); do\n"
        '    case "$1" in\n'
        "      --repo)\n"
        "        shift 2\n"
        "        ;;\n"
        "      --dir)\n"
        '        download_dir="$2"\n'
        "        shift 2\n"
        "        ;;\n"
        "      --pattern)\n"
        '        patterns+=("$2")\n'
        '        printf "%s\\n" "$2" >> "$GH_STUB_DOWNLOAD_PATTERNS_FILE"\n'
        "        shift 2\n"
        "        ;;\n"
        "      *)\n"
        '        printf "unexpected gh argument: %s\\n" "$1" >&2\n'
        "        exit 64\n"
        "        ;;\n"
        "    esac\n"
        "  done\n"
        '  mkdir -p "$download_dir"\n'
        '  for pattern in "${patterns[@]}"; do\n'
        '    case "$pattern" in\n'
        '      "$EXPECTED_ZIP")\n'
        '        printf "%s" "$GH_STUB_ZIP_CONTENT" > "$download_dir/$EXPECTED_ZIP"\n'
        "        ;;\n"
        '      "$EXPECTED_SHA256")\n'
        '        printf "%s\\n" "$GH_STUB_PUBLISHED_CHECKSUM" > "$download_dir/$EXPECTED_SHA256"\n'
        "        ;;\n"
        "      *)\n"
        '        printf "unexpected download pattern: %s\\n" "$pattern" >&2\n'
        "        exit 65\n"
        "        ;;\n"
        "    esac\n"
        "  done\n"
        "  exit 0\n"
        "fi\n"
        'printf "unexpected gh command: %s\\n" "$*" >&2\n'
        "exit 64\n",
        encoding="utf-8",
    )
    gh_stub.chmod(0o755)
    sleep_stub = tmp_path / "sleep"
    sleep_stub.write_text(
        "#!/usr/bin/env bash\n"
        'printf "%s\\n" "$*" >> "$SLEEP_STUB_CALLS_FILE"\n',
        encoding="utf-8",
    )
    sleep_stub.chmod(0o755)
    attempt_file = tmp_path / "gh-attempt"
    attempt_file.write_text("0", encoding="utf-8")
    sleep_calls_file = tmp_path / "sleep-calls"
    download_patterns_file = tmp_path / "download-patterns"
    verification_tmp_root = tmp_path / "verification-tmp"
    verification_tmp_root.mkdir()

    expected_base = "DOCSight-Desktop-Preview-win64-v1.2.3"
    env = {
        **os.environ,
        "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
        "GH_STUB_ASSETS": "\n".join(assets),
        "GH_STUB_EXIT_CODES": ",".join(
            str(exit_code) for exit_code in (gh_exit_codes or [0])
        ),
        "GH_STUB_ATTEMPT_FILE": str(attempt_file),
        "GH_STUB_DOWNLOAD_EXIT_CODE": str(download_exit_code),
        "GH_STUB_DOWNLOAD_PATTERNS_FILE": str(download_patterns_file),
        "GH_STUB_ZIP_CONTENT": zip_content.decode("ascii"),
        "GH_STUB_PUBLISHED_CHECKSUM": (
            expected_zip_hash if published_checksum is None else published_checksum
        ),
        "SLEEP_STUB_CALLS_FILE": str(sleep_calls_file),
        "TMPDIR": str(verification_tmp_root),
        "GH_TOKEN": "test-token",
        "TAG_NAME": "v1.2.3",
        "EXPECTED_ZIP": f"{expected_base}.zip",
        "EXPECTED_SHA256": f"{expected_base}.zip.sha256",
        "GITHUB_REPOSITORY": "itsDNNS/docsight",
    }
    return subprocess.run(
        ["bash", "-e", "-c", script],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )


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
    artifact_block = named_step_block(workflow, "Resolve artifact name")
    upload_block = named_step_block(workflow, "Upload desktop artifact")

    assert "packaging/windows/build.ps1" in build_block
    assert "-Version \"${{ steps.version.outputs.version }}\"" in build_block
    assert "packaging/windows/smoke_test.ps1" in smoke_block
    assert "-BundleDir packaging/windows/dist/DOCSight" in smoke_block
    assert "-ExpectedVersion \"${{ steps.version.outputs.version }}\"" in smoke_block
    assert (
        '"asset-base=DOCSight-Desktop-Preview-win64-$safeVersion"'
        in artifact_block
    )
    assert "asset-base: ${{ steps.artifact.outputs.asset-base }}" in workflow
    assert (
        "packaging/windows/dist/${{ steps.artifact.outputs.asset-base }}.zip"
        in upload_block
    )
    assert (
        "packaging/windows/dist/${{ steps.artifact.outputs.asset-base }}.zip.sha256"
        in upload_block
    )
    assert "DOCSight-Desktop-Preview-win64-*.zip" not in upload_block


def test_windows_desktop_workflow_attaches_release_assets():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    release_block = named_step_block(workflow, "Attach assets to release")
    assert "GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}" in release_block
    assert "TAG_NAME: ${{ github.event.release.tag_name }}" in release_block
    assert "ASSET_BASE: ${{ needs.build.outputs.asset-base }}" in release_block
    assert 'gh release upload "$TAG_NAME"' in release_block
    assert '"release-assets/$ASSET_BASE.zip"' in release_block
    assert '"release-assets/$ASSET_BASE.zip.sha256"' in release_block
    assert "release-assets/*" not in release_block


def test_windows_desktop_workflow_verifies_exact_published_release_assets():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    verify_block = named_step_block(workflow, "Verify published release assets")
    assert "GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}" in verify_block
    assert "TAG_NAME: ${{ github.event.release.tag_name }}" in verify_block
    assert "EXPECTED_ZIP: ${{ needs.build.outputs.asset-base }}.zip" in verify_block
    assert (
        "EXPECTED_SHA256: ${{ needs.build.outputs.asset-base }}.zip.sha256"
        in verify_block
    )
    assert 'gh release view "$TAG_NAME"' in verify_block
    assert "--json assets" in verify_block
    assert "--jq '.assets[].name'" in verify_block
    assert "max_attempts=3" in verify_block
    assert 'if release_assets_output="$(' in verify_block
    assert 'sleep "$((2 ** attempt))"' in verify_block
    assert "Failed after $max_attempts attempts." in verify_block
    assert 'mapfile -t release_assets <<< "$release_assets_output"' in verify_block
    assert verify_block.index('if release_assets_output="$(') < verify_block.index(
        "mapfile -t release_assets"
    )
    assert 'case "$asset" in' in verify_block
    assert '"$EXPECTED_ZIP")' in verify_block
    assert '"$EXPECTED_SHA256")' in verify_block
    assert 'asset_lowercase="${asset,,}"' in verify_block
    assert "docsight-desktop-preview-win64-*)" in verify_block
    assert "expected_zip_count != 1" in verify_block
    assert "expected_sha256_count != 1" in verify_block
    assert 'verification_dir="$(mktemp -d)"' in verify_block
    assert 'trap \'rm -rf -- "$verification_dir"\' EXIT' in verify_block
    assert 'gh release download "$TAG_NAME"' in verify_block
    assert '--pattern "$EXPECTED_ZIP"' in verify_block
    assert '--pattern "$EXPECTED_SHA256"' in verify_block
    assert 'sha256sum -- "$zip_path"' in verify_block
    assert '"${actual_hash,,}" != "${expected_hash,,}"' in verify_block
    assert verify_block.index("expected_sha256_count != 1") < verify_block.index(
        'gh release download "$TAG_NAME"'
    )


@pytest.mark.linux_only
def test_windows_desktop_release_verification_fails_closed_when_gh_fails(tmp_path):
    result = run_release_verification(tmp_path, [], gh_exit_codes=[42])

    assert result.returncode != 0
    assert "Unable to read published release assets." in result.stdout
    assert "Failed after 3 attempts." in result.stdout
    assert (tmp_path / "gh-attempt").read_text(encoding="utf-8") == "3"
    assert (tmp_path / "sleep-calls").read_text(encoding="utf-8") == "2\n4\n"


@pytest.mark.linux_only
def test_windows_desktop_release_verification_retries_transient_gh_failure(
    tmp_path,
):
    result = run_release_verification(
        tmp_path,
        [
            "DOCSight-Desktop-Preview-win64-v1.2.3.zip",
            "DOCSight-Desktop-Preview-win64-v1.2.3.zip.sha256",
        ],
        gh_exit_codes=[42, 0],
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Retrying (1/3)." in result.stdout
    assert (tmp_path / "gh-attempt").read_text(encoding="utf-8") == "2"
    assert (tmp_path / "sleep-calls").read_text(encoding="utf-8") == "2\n"


@pytest.mark.linux_only
def test_windows_desktop_release_verification_rejects_empty_asset_output(tmp_path):
    result = run_release_verification(tmp_path, [])

    assert result.returncode != 0
    assert "Published release returned no assets." in result.stdout


@pytest.mark.linux_only
def test_windows_desktop_release_verification_allows_unrelated_assets(tmp_path):
    result = run_release_verification(
        tmp_path,
        [
            "DOCSight-Desktop-Preview-win64-v1.2.3.zip",
            "DOCSight-Desktop-Preview-win64-v1.2.3.zip.sha256",
            "docsight-linux-v1.2.3.tar.gz",
            "another-product-v1.2.3.zip.asc",
            "release-notes.json",
        ],
    )

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.linux_only
def test_windows_desktop_release_verification_downloads_only_exact_expected_assets(
    tmp_path,
):
    result = run_release_verification(
        tmp_path,
        [
            "DOCSight-Desktop-Preview-win64-v1.2.3.zip",
            "DOCSight-Desktop-Preview-win64-v1.2.3.zip.sha256",
        ],
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert (
        tmp_path / "download-patterns"
    ).read_text(encoding="utf-8").splitlines() == [
        "DOCSight-Desktop-Preview-win64-v1.2.3.zip",
        "DOCSight-Desktop-Preview-win64-v1.2.3.zip.sha256",
    ]
    assert list((tmp_path / "verification-tmp").iterdir()) == []


@pytest.mark.linux_only
def test_windows_desktop_release_verification_fails_closed_on_download_error(
    tmp_path,
):
    result = run_release_verification(
        tmp_path,
        [
            "DOCSight-Desktop-Preview-win64-v1.2.3.zip",
            "DOCSight-Desktop-Preview-win64-v1.2.3.zip.sha256",
        ],
        download_exit_code=42,
    )

    assert result.returncode != 0
    assert (
        "Unable to download the expected published Windows Preview assets."
        in result.stdout
    )
    assert list((tmp_path / "verification-tmp").iterdir()) == []


@pytest.mark.linux_only
def test_windows_desktop_release_verification_rejects_checksum_mismatch(tmp_path):
    result = run_release_verification(
        tmp_path,
        [
            "DOCSight-Desktop-Preview-win64-v1.2.3.zip",
            "DOCSight-Desktop-Preview-win64-v1.2.3.zip.sha256",
        ],
        published_checksum="0" * 64,
    )

    assert result.returncode != 0
    assert "does not match its published checksum." in result.stdout
    assert list((tmp_path / "verification-tmp").iterdir()) == []


@pytest.mark.linux_only
@pytest.mark.parametrize("published_checksum", ["", "not-a-sha256"])
def test_windows_desktop_release_verification_rejects_empty_or_invalid_checksum(
    tmp_path,
    published_checksum,
):
    result = run_release_verification(
        tmp_path,
        [
            "DOCSight-Desktop-Preview-win64-v1.2.3.zip",
            "DOCSight-Desktop-Preview-win64-v1.2.3.zip.sha256",
        ],
        published_checksum=published_checksum,
    )

    assert result.returncode != 0
    assert "checksum is empty or invalid." in result.stdout


@pytest.mark.linux_only
def test_windows_desktop_release_verification_compares_checksum_case_insensitively(
    tmp_path,
):
    zip_content = b"deterministic Windows Preview ZIP fixture\n"
    result = run_release_verification(
        tmp_path,
        [
            "DOCSight-Desktop-Preview-win64-v1.2.3.zip",
            "DOCSight-Desktop-Preview-win64-v1.2.3.zip.sha256",
        ],
        published_checksum=hashlib.sha256(zip_content).hexdigest().upper(),
    )

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.linux_only
@pytest.mark.parametrize(
    "extra_asset",
    [
        "DOCSight-Desktop-Preview-win64-v1.2.2.zip",
        "DOCSight-Desktop-Preview-win64-v1.2.2.zip.sha256",
        "docsight-desktop-preview-win64-v1.2.2.zip",
        "DOCSight-Desktop-Preview-win64-v1.2.2.zip.asc",
    ],
)
def test_windows_desktop_release_verification_rejects_stale_preview_assets(
    tmp_path,
    extra_asset,
):
    result = run_release_verification(
        tmp_path,
        [
            "DOCSight-Desktop-Preview-win64-v1.2.3.zip",
            "DOCSight-Desktop-Preview-win64-v1.2.3.zip.sha256",
            extra_asset,
        ],
    )

    assert result.returncode != 0
    assert f"unexpected Windows Preview asset: {extra_asset}" in result.stdout
    assert not (tmp_path / "download-patterns").exists()


@pytest.mark.linux_only
@pytest.mark.parametrize(
    "assets",
    [
        ["DOCSight-Desktop-Preview-win64-v1.2.3.zip"],
        ["DOCSight-Desktop-Preview-win64-v1.2.3.zip.sha256"],
        [
            "DOCSight-Desktop-Preview-win64-v1.2.3.zip",
            "DOCSight-Desktop-Preview-win64-v1.2.3.zip",
            "DOCSight-Desktop-Preview-win64-v1.2.3.zip.sha256",
        ],
        [
            "DOCSight-Desktop-Preview-win64-v1.2.3.zip",
            "DOCSight-Desktop-Preview-win64-v1.2.3.zip.sha256",
            "DOCSight-Desktop-Preview-win64-v1.2.3.zip.sha256",
        ],
    ],
)
def test_windows_desktop_release_verification_requires_each_expected_asset_once(
    tmp_path,
    assets,
):
    result = run_release_verification(tmp_path, assets)

    assert result.returncode != 0
    assert "must contain exactly one expected Windows Preview" in result.stdout
    assert not (tmp_path / "download-patterns").exists()


def test_windows_desktop_workflow_does_not_delete_release_assets_by_pattern():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "gh release delete-asset" not in workflow
    assert not re.search(
        r"(?im)^[ \t]*(?:rm|unlink|remove-item)\b[^\n]*[*?\[]",
        workflow,
    )


@pytest.mark.linux_only
@pytest.mark.parametrize(
    "step_name",
    ["Attach assets to release", "Verify published release assets"],
)
def test_windows_desktop_bash_run_blocks_have_valid_syntax(step_name):
    workflow = WORKFLOW.read_text(encoding="utf-8")
    script = named_step_run_script(workflow, step_name)

    result = subprocess.run(
        ["bash", "-n"],
        check=False,
        capture_output=True,
        input=script,
        text=True,
    )

    assert result.returncode == 0, result.stderr


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
