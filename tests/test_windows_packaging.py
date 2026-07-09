"""Static packaging contract tests for the Windows Desktop Preview build."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINDOWS_PACKAGING = ROOT / "packaging" / "windows"


def test_windows_packaging_files_exist():
    for relative in (
        "docsight_desktop.py",
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


def test_build_lock_contains_windows_pyinstaller_dependencies():
    lock_text = (WINDOWS_PACKAGING / "requirements-build.txt").read_text(encoding="utf-8")

    assert "pefile==" in lock_text
    assert "pywin32-ctypes==" in lock_text
    assert "sys_platform == 'win32'" in lock_text


def test_runtime_windows_lock_contains_windows_marked_dependencies():
    lock_text = (WINDOWS_PACKAGING / "requirements-runtime-windows.txt").read_text(encoding="utf-8")

    assert "click==8.3.1" in lock_text
    assert "colorama==0.4.6" in lock_text
    assert "tzdata==2026.2" in lock_text


def test_docker_context_excludes_windows_packaging():
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert "packaging" in {line.strip("/") for line in dockerignore.splitlines()}


def test_gitignore_excludes_windows_build_outputs():
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "packaging/windows/build/" in gitignore
    assert "packaging/windows/dist/" in gitignore
