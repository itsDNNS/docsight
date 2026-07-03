"""Regression tests for public defensive-review documentation fixtures."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SECRET_PATTERNS = [
    re.compile(r"dsk_[A-Za-z0-9_-]{12,}"),
    re.compile(r"ghp_[A-Za-z0-9_]{20,}"),
    re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*=\s*['\"][^'\"]{8,}['\"]"),
]

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
