"""Static packaging contract tests for the Windows Desktop Preview build."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINDOWS_PACKAGING = ROOT / "packaging" / "windows"
CODE_SIGNING_POLICY = ROOT / "CODE_SIGNING.md"
WINDOWS_WORKFLOW = ROOT / ".github" / "workflows" / "windows-desktop.yml"


def safe_version_rule(text: str, assignment: str) -> tuple[str, str]:
    match = re.search(
        rf"{re.escape(assignment)}.*?-replace\s+"
        r"'(?P<pattern>[^']+)',\s*'(?P<replacement>[^']*)'",
        text,
    )
    assert match, f"safe-version replacement not found for {assignment}"
    return match.group("pattern"), match.group("replacement")


def test_windows_packaging_files_exist():
    for relative in (
        "docsight_desktop.py",
        "tray.py",
        "docsight.spec",
        "build.ps1",
        "requirements-build.in",
        "requirements-build.txt",
        "requirements-runtime-windows.in",
        "requirements-runtime-windows.txt",
        "requirements-test-windows.in",
        "requirements-test-windows.txt",
        "smoke_test.ps1",
        "README.md",
        "QA-CHECKLIST.md",
    ):
        assert (WINDOWS_PACKAGING / relative).is_file()


def test_pyinstaller_spec_collects_app_tree_and_version_file():
    spec_text = (WINDOWS_PACKAGING / "docsight.spec").read_text(encoding="utf-8")

    assert "collect_app_datas()" in spec_text
    assert "collect_app_hiddenimports()" in spec_text
    assert "VERSION_FILE" in spec_text
    assert "(str(VERSION_FILE), \".\")" in spec_text
    assert "docsight-icmp-helper" not in spec_text
    assert "docsight-traceroute-helper" not in spec_text


def test_pyinstaller_spec_bundles_tk_and_keeps_test_exclusion():
    spec_path = WINDOWS_PACKAGING / "docsight.spec"
    spec_text = spec_path.read_text(encoding="utf-8")
    tree = ast.parse(spec_text, filename=str(spec_path))
    analysis_call = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Analysis"
    )
    excludes_keyword = next(
        keyword for keyword in analysis_call.keywords if keyword.arg == "excludes"
    )
    exclusions = ast.literal_eval(excludes_keyword.value)

    assert '"tkinter"' in spec_text
    assert '"tkinter.ttk"' in spec_text
    assert "tkinter" not in exclusions
    assert "pytest" in exclusions
    assert "unittest" not in exclusions


def test_pyinstaller_spec_disables_windowed_tracebacks():
    spec_text = (WINDOWS_PACKAGING / "docsight.spec").read_text(encoding="utf-8")

    assert "disable_windowed_traceback=True" in spec_text
    assert "disable_windowed_traceback=False" not in spec_text


def test_build_script_uses_hash_pinned_requirements_and_creates_zip_hash():
    script = (WINDOWS_PACKAGING / "build.ps1").read_text(encoding="utf-8")

    assert "--require-hashes" in script
    assert "requirements-runtime-windows.txt" in script
    assert "requirements-build.txt" in script
    assert "Invoke-Checked" in script
    assert "[System.IO.Path]::IsPathRooted($OutputDirectory)" in script
    assert "[System.Text.UTF8Encoding]::new($false)" in script
    assert "PyInstaller" in script
    assert "DOCSight-Desktop-Preview-win64-$SafeVersion.zip" in script
    assert "Compress-Archive -Path $BundleDir" in script
    assert "Get-FileHash -Algorithm SHA256" in script


def test_workflow_and_build_script_apply_the_same_versioned_zip_convention():
    build_script = (WINDOWS_PACKAGING / "build.ps1").read_text(encoding="utf-8")
    workflow = WINDOWS_WORKFLOW.read_text(encoding="utf-8")
    build_rule = safe_version_rule(build_script, "return ($Value")
    workflow_rule = safe_version_rule(workflow, '$safeVersion = "')
    versions = {
        "v1.2.3": "v1.2.3",
        "2026-07-28_rc.1": "2026-07-28_rc.1",
        "v1.2.3+build 7": "v1.2.3-build-7",
        "release/1:beta?x": "release-1-beta-x",
        "ä/1": "--1",
    }

    for version, expected_safe_version in versions.items():
        expected_name = (
            f"DOCSight-Desktop-Preview-win64-{expected_safe_version}.zip"
        )
        build_name = (
            "DOCSight-Desktop-Preview-win64-"
            f"{re.sub(build_rule[0], build_rule[1], version)}.zip"
        )
        workflow_name = (
            "DOCSight-Desktop-Preview-win64-"
            f"{re.sub(workflow_rule[0], workflow_rule[1], version)}.zip"
        )
        assert build_name == expected_name
        assert workflow_name == expected_name


def test_build_lock_contains_windows_pyinstaller_dependencies():
    lock_text = (WINDOWS_PACKAGING / "requirements-build.txt").read_text(encoding="utf-8")

    assert "pefile==" in lock_text
    assert "pywin32-ctypes==" in lock_text
    assert "sys_platform == 'win32'" in lock_text


def test_runtime_windows_lock_contains_windows_marked_dependencies():
    lock_text = (WINDOWS_PACKAGING / "requirements-runtime-windows.txt").read_text(encoding="utf-8")

    assert "click==8.4.2" in lock_text
    assert "colorama==0.4.6" in lock_text
    assert "tzdata==2026.2" in lock_text
    assert "pystray==0.19.5" in lock_text


def test_both_windows_locks_pin_tray_and_transitive_dependency_hashes():
    for lock_name in (
        "requirements-runtime-windows.txt",
        "requirements-test-windows.txt",
    ):
        lock_text = (WINDOWS_PACKAGING / lock_name).read_text(encoding="utf-8")
        assert "pystray==0.19.5 \\\n    --hash=sha256:" in lock_text
        assert "six==1.17.0 \\\n    --hash=sha256:" in lock_text


def test_pyinstaller_spec_bundles_native_tray_adapter():
    spec_text = (WINDOWS_PACKAGING / "docsight.spec").read_text(encoding="utf-8")

    assert '"tray"' in spec_text
    assert '"pystray"' in spec_text
    assert '"pystray._win32"' in spec_text


def test_docker_context_excludes_windows_packaging():
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert "packaging" in {line.strip("/") for line in dockerignore.splitlines()}


def test_gitignore_excludes_windows_build_outputs():
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "packaging/windows/build/" in gitignore
    assert "packaging/windows/dist/" in gitignore


def test_windows_code_signing_policy_public_contract():
    policy = CODE_SIGNING_POLICY.read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    windows_readme = (WINDOWS_PACKAGING / "README.md").read_text(encoding="utf-8")
    normalized_policy = " ".join(policy.split())
    policy_lower = normalized_policy.lower()
    windows_readme_lower = " ".join(windows_readme.split()).lower()
    attribution = (
        "Free code signing provided by SignPath.io, "
        "certificate by SignPath Foundation"
    )
    conditional_heading = "## Conditional provider attribution"
    status_text, conditional_text = policy.split(conditional_heading, maxsplit=1)

    assert policy.startswith("# Code signing policy\n")
    assert attribution not in status_text
    assert attribution in conditional_text
    assert (
        "will apply only if provider approval and onboarding succeed"
        in policy_lower
    )
    assert "windows artifacts remain unsigned" in policy_lower
    assert "still in progress" in policy_lower
    assert "official tagged release" in policy_lower
    for excluded_context in ("pull request", "fork", "untrusted context"):
        assert excluded_context in policy_lower
    assert "not eligible for signing" in policy_lower
    assert "source-control account" in policy_lower
    assert "future signing-approval account" in policy_lower
    assert "must use multi-factor authentication (mfa)" in policy_lower
    for approval_check in (
        "release source",
        "workflow result",
        "artifact identity",
        "expected version",
    ):
        assert approval_check in policy_lower
    assert "## Revocation and incidents" in policy
    assert "stop approving and publishing" in policy_lower
    assert "request revocation" in policy_lower
    assert "impact and verification guidance" in policy_lower
    assert "https://github.com/itsDNNS/docsight/releases" in policy
    assert "[SECURITY.md](SECURITY.md)" in policy
    assert '<a href="CODE_SIGNING.md">Code signing</a>' in readme
    assert "[code signing policy](../../CODE_SIGNING.md)" in windows_readme
    assert "preview artifacts are unsigned" in windows_readme_lower
    assert "provider onboarding is pending" in windows_readme_lower
