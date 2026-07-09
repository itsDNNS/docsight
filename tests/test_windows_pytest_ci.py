"""Static checks for the portable Windows pytest CI lane."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEST_WORKFLOW = ROOT / ".github" / "workflows" / "test.yml"
WINDOWS_TEST_LOCK = ROOT / "packaging" / "windows" / "requirements-test-windows.txt"
QA_CHECKLIST = ROOT / "packaging" / "windows" / "QA-CHECKLIST.md"


def job_block(workflow_text: str, job_name: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(job_name)}:\n(?P<body>.*?)(?=^  [A-Za-z0-9_-]+:|\Z)",
        workflow_text,
    )
    assert match, f"job not found: {job_name}"
    return match.group("body")


def test_linux_pytest_job_keeps_existing_test_command():
    workflow = TEST_WORKFLOW.read_text(encoding="utf-8")
    linux_job = job_block(workflow, "test")

    assert "runs-on: ubuntu-latest" in linux_job
    assert "pip install --require-hashes -r requirements-test.txt" in linux_job
    assert "python -m pytest tests/ -v --tb=short --ignore=tests/e2e" in linux_job
    assert "-m \"not linux_only\"" not in linux_job


def test_windows_pytest_job_runs_portable_subset_with_windows_lock():
    workflow = TEST_WORKFLOW.read_text(encoding="utf-8")
    windows_job = job_block(workflow, "test-windows")

    assert "runs-on: windows-latest" in windows_job
    assert "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0" in windows_job
    assert "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1" in windows_job
    assert "python-version: \"3.13\"" in windows_job
    assert "cache-dependency-path: packaging/windows/requirements-test-windows.txt" in windows_job
    assert "pip install --require-hashes -r packaging/windows/requirements-test-windows.txt" in windows_job
    assert 'python -m pytest tests/ -v --tb=short --ignore=tests/e2e -m "not linux_only"' in windows_job


def test_windows_test_lock_contains_marker_only_windows_dependency():
    lock_text = WINDOWS_TEST_LOCK.read_text(encoding="utf-8")

    assert "--python-platform windows --python-version 3.13 packaging/windows/requirements-test-windows.in" in lock_text
    assert "colorama==0.4.6" in lock_text
    assert "pytest==9.1.1" in lock_text
    assert "soupsieve==2.8.4" in lock_text
    assert "tzdata==2026.2" in lock_text


def test_linux_only_marker_is_registered_and_reasoned():
    marker_config = (ROOT / "pytest.ini").read_text(encoding="utf-8")
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            ROOT / "tests" / "test_module_paths.py",
            ROOT / "tests" / "modules" / "connection_monitor" / "test_probe.py",
            ROOT / "tests" / "modules" / "connection_monitor" / "test_traceroute_probe.py",
        )
    )

    assert "linux_only:" in marker_config
    assert source.count("pytest.mark.linux_only") == 3
    assert "reason=\"Container runtime path and Docker entrypoint contracts are Linux-only.\"" in source
    assert "reason=\"ICMP helper compile probe requires Linux C networking headers and gcc.\"" in source
    assert "reason=\"Traceroute helper compile probe requires Linux C networking headers and gcc.\"" in source


def test_manual_qa_checklist_covers_desktop_release_risks():
    checklist = QA_CHECKLIST.read_text(encoding="utf-8")
    lower = checklist.lower()

    for required in (
        "sha256",
        "smartscreen",
        "double-click",
        "demo mode",
        "glossary",
        "evidence journey",
        "real modem",
        "tcp-based checks",
        "sleep or hibernate",
        "second time",
        "%localappdata%\\docsight",
        "uninstall",
    ):
        assert required in lower
