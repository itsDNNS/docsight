"""Settings markup takes its styles from stylesheets and its behavior from scripts."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INLINE = re.compile(r"""\s(style|on[a-z]+)\s*=\s*["']""")


def _settings_templates():
    yield ROOT / "app" / "templates" / "settings.html"
    yield from sorted((ROOT / "app" / "templates" / "settings").glob("*.html"))
    yield from sorted((ROOT / "app" / "modules").glob("*/templates/*_settings.html"))


def test_settings_templates_have_no_inline_styles_or_handlers():
    offenders = [
        f"{path.relative_to(ROOT)}:{text.count(chr(10), 0, match.start()) + 1}: {match.group(1)}"
        for path in _settings_templates()
        for text in [path.read_text(encoding="utf-8")]
        for match in INLINE.finditer(text)
    ]
    assert offenders == []
