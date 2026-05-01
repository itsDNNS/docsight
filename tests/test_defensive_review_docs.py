"""Regression tests for the maintainer defensive review checklist."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECURITY_MD = ROOT / "SECURITY.md"

REQUIRED_BOUNDARIES = {
    "modem/router response parsing": ["tests/test_vodafone_station_tg.py", "tests/test_driver_registry.py"],
    "import/export paths": ["tests/test_import_parser.py", "tests/test_report.py"],
    "local authentication/session handling": ["tests/test_auth.py", "tests/test_security_hardening.py"],
    "token and credential storage": ["tests/test_security_hardening.py", "tests/test_config.py"],
    "mqtt/home assistant integration payloads": ["tests/test_notifier.py"],
    "module/plugin manifest loading": ["tests/test_module_install_api.py", "tests/test_modules_api.py"],
    "docker/self-hosted runtime defaults": ["tests/test_config.py", "tests/e2e/test_auth.py"],
    "rate limiting or abuse resistance": ["tests/test_auth.py", "tests/test_smart_capture_guardrails.py"],
    "test fixtures and documentation examples": ["tests/test_defensive_review_docs.py"],
}

SECRET_PATTERNS = [
    re.compile(r"dsk_[A-Za-z0-9_-]{12,}"),
    re.compile(r"ghp_[A-Za-z0-9_]{20,}"),
    re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*=\s*['\"][^'\"]{8,}['\"]"),
]


def test_security_policy_has_defensive_review_checklist():
    text = SECURITY_MD.read_text(encoding="utf-8").lower()

    assert "defensive review checklist" in text
    for boundary in REQUIRED_BOUNDARIES:
        assert boundary in text


def test_defensive_review_checklist_references_existing_tests():
    text = SECURITY_MD.read_text(encoding="utf-8")

    for boundary, test_paths in REQUIRED_BOUNDARIES.items():
        for rel_path in test_paths:
            assert rel_path in text, f"{boundary} should reference {rel_path}"
            assert (ROOT / rel_path).exists(), f"referenced test path missing: {rel_path}"


def test_public_docs_and_text_fixtures_do_not_contain_reusable_secret_examples():
    scanned = []
    candidates = list((ROOT / "docs").rglob("*")) + list((ROOT / "tests").rglob("*"))
    candidates.extend(ROOT.glob("*.md"))

    for candidate in candidates:
        if not candidate.is_file() or candidate.suffix.lower() not in {".md", ".py", ".json", ".txt", ".csv", ".html", ".yaml", ".yml"}:
            continue
        rel = candidate.relative_to(ROOT).as_posix()
        text = candidate.read_text(encoding="utf-8", errors="ignore")
        scanned.append(rel)
        for pattern in SECRET_PATTERNS:
            assert not pattern.search(text), f"secret-like reusable example in {rel}"

    assert "SECURITY.md" in scanned
    assert "tests/test_defensive_review_docs.py" in scanned
