"""Every HTML string written by DOCSight's scripts goes through docsightHTML()."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SINK = re.compile(r"\.(?:innerHTML|outerHTML)\s*\+?=(?!=)\s*+(?!docsightHTML\()|insertAdjacentHTML\(\s*'[a-z]+'\s*,\s*+(?!docsightHTML\()|parseFromString\((?!docsightHTML\()")


def test_html_sinks_use_the_docsight_policy():
    offenders = [
        f"{path.relative_to(ROOT)}:{text.count(chr(10), 0, match.start()) + 1}"
        for path in sorted((ROOT / "app").rglob("*.js"))
        if "vendor" not in path.parts
        for text in [path.read_text(encoding="utf-8")]
        for match in SINK.finditer(text)
    ]
    assert offenders == []
