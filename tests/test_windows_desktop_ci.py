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
PYINSTALLER_SPEC = ROOT / "packaging" / "windows" / "docsight.spec"
WINDOWS_README = ROOT / "packaging" / "windows" / "README.md"
WINDOWS_QA_CHECKLIST = ROOT / "packaging" / "windows" / "QA-CHECKLIST.md"
WINDOWS_PREVIEW_DOC = ROOT / "docs" / "windows-desktop-preview.md"


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
    assert "  build:\n    timeout-minutes: 30\n    runs-on: windows-latest" in workflow
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
    assert "OwningProcess -eq $Process.Id" in script
    assert "Get-PeMachine -Path $Executable" in script
    assert "0x8664" in script
    assert "-WindowStyle Hidden" not in script
    assert "DOCSIGHT_SKIP_BROWSER" in script
    assert "DOCSIGHT_SMOKE_INJECT_STARTUP_FAILURE" in script
    assert "DOCSight\\logs\\launcher.log" in script
    assert "DOCSight\\logs\\runtime.log" in script
    assert "python -m app.main" not in script


def test_pyinstaller_collects_desktop_runtime_ownership_modules():
    spec_text = PYINSTALLER_SPEC.read_text(encoding="utf-8")
    launcher = (ROOT / "packaging" / "windows" / "docsight_desktop.py").read_text(
        encoding="utf-8"
    )
    instance = (ROOT / "packaging" / "windows" / "desktop_instance.py").read_text(
        encoding="utf-8"
    )
    platform = (ROOT / "packaging" / "windows" / "desktop_platform.py").read_text(
        encoding="utf-8"
    )
    endpoint = (ROOT / "app" / "desktop_runtime.py").read_text(encoding="utf-8")

    assert '"desktop_instance"' in spec_text
    assert '"desktop_platform"' in spec_text
    assert '"tray"' in spec_text
    assert '"pystray._win32"' in spec_text
    assert "from desktop_instance import" in launcher
    assert "collect_app_hiddenimports()" in spec_text
    assert (ROOT / "app" / "desktop_runtime.py").is_file()
    assert (ROOT / "app" / "desktop_runtime_contract.py").is_file()
    assert "from app.desktop_runtime_contract import" in instance
    assert "from desktop_platform import" in instance
    assert "desktop_instance" not in platform
    assert "packaging" not in endpoint


def test_launcher_normal_mainloop_exit_runs_runtime_cleanup():
    launcher = (ROOT / "packaging" / "windows" / "docsight_desktop.py").read_text(
        encoding="utf-8"
    )

    assert "root.mainloop()" in launcher
    assert "view.shutdown.request()" in launcher
    assert "self.server_lifecycle.close" in launcher
    assert "worker.join(self.timeout_seconds)" in launcher
    assert "self.cleanup" in launcher


def test_smoke_script_requires_one_owned_ipv4_loopback_listener():
    script = SMOKE_SCRIPT.read_text(encoding="utf-8")

    assert "$Connections.Count -ne 1" in script
    assert "$OwnedLoopbackListeners.Count -ne 1" in script
    assert '$_.LocalAddress -eq "127.0.0.1"' in script
    assert "$_.OwningProcess -eq $Process.Id" in script
    assert "Expected exactly one listener on runtime port" in script
    assert "Expected exactly one 127.0.0.1:$RuntimePort listener owned by DOCSight" in script


def test_smoke_script_executes_single_instance_runtime_handoff_scenarios():
    script = SMOKE_SCRIPT.read_text(encoding="utf-8")

    assert "[System.Net.Sockets.TcpListener]::new" in script
    assert "$ForeignListener.Start()" in script
    assert '$RuntimeStateFile = Join-Path $LocalAppData "DOCSight\\runtime.json"' in script
    assert "$LaunchOne = Start-Process" in script
    assert "$LaunchTwo = Start-Process" in script
    assert "$ThirdProcess = Start-Process" in script
    assert "did not hand off and exit" in script
    assert "did not reuse the running desktop instance" in script
    assert "adopted the foreign listener" in script
    assert "outside 8765-8775" in script
    assert "-BearerToken ([string]$RuntimeState.instance_token)" in script
    assert "accepted the wrong instance token" in script
    assert "$Process.StartTime.ToUniversalTime().ToFileTimeUtc()" in script
    assert "process start time does not match" in script
    assert "Second or third launch replaced" in script
    assert "crash-leftover runtime record was not replaced" in script


def test_smoke_script_prints_both_logs_and_rejects_runtime_import_degradation():
    script = SMOKE_SCRIPT.read_text(encoding="utf-8")

    assert (
        '$RuntimeLogFile = Join-Path $LocalAppData "DOCSight\\logs\\runtime.log"'
        in script
    )
    assert "Get-Content -LiteralPath $LauncherLogFile -Tail 200" in script
    assert "Get-Content -LiteralPath $RuntimeLogFile -Tail 200" in script
    assert "if (-not (Test-Path -LiteralPath $RuntimeLogFile))" in script
    assert "Get-Content -LiteralPath $RuntimeLogFile -Raw" in script
    assert "failed to import routes" in script
    assert "No module named" in script
    assert "Write-Host $RuntimeLogText" not in script


def test_smoke_script_proves_injected_startup_recovery_without_browser():
    script = SMOKE_SCRIPT.read_text(encoding="utf-8")

    assert '$env:DOCSIGHT_SKIP_BROWSER = "1"' in script
    assert '$env:DOCSIGHT_SMOKE_INJECT_STARTUP_FAILURE = "1"' in script
    assert '"Phase: Prepare local data"' in script
    assert '"Recovery available: app_thread_failure"' in script
    assert '"failure type: RuntimeError"' in script
    assert "if ($Process.HasExited)" in script
    assert "instead of keeping recovery available" in script
    assert "$Process.Refresh()" in script
    assert "$Process.MainWindowHandle -eq [IntPtr]::Zero" in script
    assert '$Process.MainWindowTitle -cne "DOCSight"' in script
    assert "-WindowStyle Hidden" not in script


def test_smoke_script_uses_fresh_launcher_log_for_injected_recovery():
    script = SMOKE_SCRIPT.read_text(encoding="utf-8")
    launches = [
        match.start()
        for match in re.finditer(
            r"Start-Process -FilePath \$Executable -WorkingDirectory "
            r"\$LaunchBundleDir -PassThru",
            script,
        )
    ]

    assert len(launches) == 5
    first_graceful_quit = script.index(
        'CycleName "First packaged cycle"', launches[2]
    )
    second_cycle = launches[3]
    second_graceful_quit = script.index(
        'CycleName "Second packaged cycle"', second_cycle
    )
    remove_first_log = script.index(
        "Remove-Item -LiteralPath $LauncherLogFile -Force", second_graceful_quit
    )
    injected_launch = launches[4]
    prepare_phase_assertion = script.index(
        '"Phase: Prepare local data"',
        injected_launch,
    )
    assert (
        launches[0]
        < first_graceful_quit
        < second_cycle
        < second_graceful_quit
        < remove_first_log
        < injected_launch
    )
    assert injected_launch < prepare_phase_assertion
    assert injected_launch < script.index("$Process.MainWindowHandle", injected_launch)
    assert injected_launch < script.index("$Process.MainWindowTitle", injected_launch)


def test_smoke_script_restores_all_injection_environment_variables():
    script = SMOKE_SCRIPT.read_text(encoding="utf-8")
    finally_block = script.rsplit("} finally {", maxsplit=1)[1]

    variables = (
        ("STARTUP", "Startup"),
        ("BROWSER", "Browser"),
        ("NO_PORT", "NoPort"),
    )
    for environment_suffix, variable_suffix in variables:
        environment_name = f"DOCSIGHT_SMOKE_INJECT_{environment_suffix}_FAILURE"
        assert (
            f"$PreviousInjected{variable_suffix}Failure = $env:{environment_name}"
            in script
        )
        assert (
            f"$env:{environment_name} = $PreviousInjected{variable_suffix}Failure"
            in finally_block
        )
    assert (
        "$PreviousSmokeQuitSentinel = $env:DOCSIGHT_SMOKE_QUIT_SENTINEL"
        in script
    )
    assert (
        "$env:DOCSIGHT_SMOKE_QUIT_SENTINEL = $PreviousSmokeQuitSentinel"
        in finally_block
    )


def test_smoke_script_proves_two_shared_command_graceful_quit_cycles():
    script = SMOKE_SCRIPT.read_text(encoding="utf-8")

    assert '$env:DOCSIGHT_SMOKE_QUIT_SENTINEL = $SmokeQuitSentinel' in script
    assert script.count("Request-GracefulQuit `") == 2
    assert 'CycleName "First packaged cycle"' in script
    assert 'CycleName "Second packaged cycle"' in script
    assert "did not exit through the graceful quit command" in script
    assert "left its selected port listening after graceful quit" in script
    assert "left runtime.json after graceful quit" in script
    assert "A packaged DOCSight process remained after graceful quit" in script
    assert "The DOCSight owner created an unexpected child process" in script
    assert "Assert-DataFilesReopen" in script
    assert "Second packaged cycle could not reopen the persisted setup" in script
    assert "Second packaged cycle setup write failed" in script
    assert "two graceful open/write/quit cycles" in script


def test_windows_docs_describe_smoke_and_log_sharing_contracts():
    readme = WINDOWS_README.read_text(encoding="utf-8")
    qa_checklist = WINDOWS_QA_CHECKLIST.read_text(encoding="utf-8")
    preview_doc = WINDOWS_PREVIEW_DOC.read_text(encoding="utf-8")
    combined_docs = "\n".join((readme, qa_checklist, preview_doc))
    normalized_docs = " ".join(combined_docs.split())

    assert "from **Start DOCSight** onward" in readme
    assert "from **Start DOCSight** onward" in qa_checklist
    assert "from **Start DOCSight** onward" in preview_doc
    assert "exactly one listener" in combined_docs
    assert "route/import" in combined_docs
    assert "fresh **Prepare local data** evidence" in combined_docs
    assert "nonzero main-window handle" in combined_docs
    assert "title exactly `DOCSight`" in combined_docs
    assert "sanitized" in combined_docs
    assert "shareable" in combined_docs
    assert "review it before sharing" in combined_docs
    assert "Linux tests only enforce its\nstatic contract" in preview_doc
    assert "runs later on `windows-latest`" in preview_doc
    assert "`Global\\` namespace" in combined_docs
    assert "current user's SID" in combined_docs
    assert "independent process-token SID lookup" in normalized_docs
    assert "both SID lookups fail, startup fails safely" in normalized_docs
    assert "mutex name always remains SID-derived" in normalized_docs
    assert "Different Windows users" in combined_docs
    assert "process creation time" in combined_docs
    assert "token-authenticated" in combined_docs
    assert "second/third-launch handoff" in combined_docs
    assert "ordinary `/health`" in combined_docs
    assert "`127.0.0.1`" in combined_docs
    assert "must not run alongside another DOCSight desktop instance" in readme
    assert (
        "!docs/windows-desktop-preview.md"
        in (ROOT / ".gitignore").read_text(encoding="utf-8")
    )


def test_windows_qa_keeps_all_precise_failure_injection_invocations():
    qa_checklist = WINDOWS_QA_CHECKLIST.read_text(encoding="utf-8")

    for environment_name in (
        "DOCSIGHT_SMOKE_INJECT_STARTUP_FAILURE",
        "DOCSIGHT_SMOKE_INJECT_NO_PORT_FAILURE",
        "DOCSIGHT_SMOKE_INJECT_BROWSER_FAILURE",
    ):
        assert f'$env:{environment_name} = "1"' in qa_checklist
        assert f"Remove-Item Env:{environment_name}," in qa_checklist
    assert qa_checklist.count('$env:DOCSIGHT_SKIP_BROWSER = "1"') == 3
    assert qa_checklist.count("Env:DOCSIGHT_SKIP_BROWSER -ErrorAction") == 3
    assert qa_checklist.count(".\\DOCSight.exe") == 3


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


def test_smoke_script_preserves_cleanup_after_real_reports_route_checks():
    script = SMOKE_SCRIPT.read_text(encoding="utf-8")

    assert script.index("$EmptyReportResponse") < script.index("$SetupResponse")
    assert script.index("$SetupResponse") < script.index("$PdfResponse.ContentType")
    assert re.search(
        r"}\s*catch\s*{\s*Write-SmokeLog\s*throw\s*}\s*finally\s*{",
        script,
    )
    assert "Stop-Process -Id $CleanupProcess.Id -Force" in script
    assert "$env:LOCALAPPDATA = $PreviousLocalAppData" in script
    assert "Remove-Item -Recurse -Force $SmokeRoot" in script


def test_windows_build_and_workflow_require_x64_python():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    build_script = (ROOT / "packaging" / "windows" / "build.ps1").read_text(
        encoding="utf-8"
    )

    assert "architecture: x64" in workflow
    assert "struct.calcsize('P')" in build_script
    assert 'PointerSize -ne "8"' in build_script


def test_step_block_helper_does_not_capture_next_step():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    build_block = named_step_block(workflow, "Build portable package")

    assert "Smoke-test built package" not in build_block
