"""Shared components are defined once, in components.css."""

import functools
import re
import subprocess
from pathlib import Path

import pytest

from app.theme_catalog import DEPRECATED_ALIASES

ROOT = Path(__file__).resolve().parents[1]
OWNER = "app/static/css/components.css"
# Base button and its variants; context rules such as `.modal-footer .btn` stay allowed.
BUTTON_RULE = re.compile(
    r"(?m)^\s*\.btn(?:-(?:primary|secondary|ghost|danger|accent|muted|sm|small))?(?::[a-z-]+(?:\([^)]*\))?)*(?:\s+svg)?\s*[{,]"
)
# Form fields and the toggle switch, including their states and light-mode variants.
FORM_RULE = re.compile(
    r"(?m)^\s*(?:\[data-theme=\"light\"\]\s+)?(?:\.form-(?:field|label|hint|input|select|grid)|\.toggle(?:-slider)?)(?![\w-])[^{,]*[{,]"
)

# The card and the glass surface.
CARD_RULE = re.compile(
    r"(?m)^\s*(?:\[data-theme=\"light\"\]\s+)?(?:\.card(?:-(?:header|title-group|title|subtitle|icon))?|\.glass)(?![\w-])(?::[a-z-]+)*(?:\s+(?:svg|i|>\s*div))?\s*[{,]"
)

# The badge and its color variants.
BADGE_RULE = re.compile(
    r"(?m)^\s*\.badge(?:-(?:good|tolerated|warn|warning|crit|critical|info|muted|success|danger))?(?![\w-])[^{]*[{,]"
)

# The segmented control and its options.
SEGMENTED_RULE = re.compile(r"(?m)^\s*(?:\[data-theme=\"light\"\]\s+)?\.segmented(?:-option)?(?![\w-])[^{,]*[{,]")

# The data table and its variants.
DATA_TABLE_RULE = re.compile(r"(?m)^\s*\.data-table(?:-[a-z]+)?(?![\w-])[^{,]*[{,]")

# Tables that are not data tables on purpose, by file and the table's id or first class:
# the per-target Connection Monitor stats render as a stat grid.
TABLES_WITHOUT_COMPONENT = {
    ("app/modules/connection_monitor/static/js/connection-monitor-charts.js", "cm-target-table"),
}

# The dialog: overlay, panel and its parts.
DIALOG_RULE = re.compile(r"(?m)^\s*\.modal(?:-overlay|-wide|-header|-close|-hint|-body|-footer(?:-start)?)?(?![\w-])[^{,]*[{,]")

# Dialogs that are not standard dialogs on purpose: the chart zoom fills the screen with a chart,
# the command palette is a search field over its results, the mobile glossary picker is a bottom sheet.
DIALOGS_WITHOUT_COMPONENT = {"chart-zoom-overlay", "command-palette", "glossary-mobile-picker"}

# The toast and its tones.
TOAST_RULE = re.compile(r"(?m)^\s*\.toast(?:-(?:success|error|info))?(?![\w-])[^{,]*[{,]")

# The save bar.
SAVE_BAR_RULE = re.compile(r"(?m)^\s*(?:\[data-theme=\"light\"\]\s+)?\.save-bar(?:-[a-z]+)?(?![\w-])[^{,]*[{,]")


@functools.cache
def _app_files():
    return subprocess.run(["git", "ls-files", "app"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()


def _tracked(*suffixes):
    return [path for path in _app_files() if path.endswith(suffixes) and "/vendor/" not in path]


@pytest.mark.parametrize("rule", [
    BUTTON_RULE, FORM_RULE, CARD_RULE, SAVE_BAR_RULE, TOAST_RULE, BADGE_RULE, SEGMENTED_RULE, DATA_TABLE_RULE, DIALOG_RULE,
], ids=["buttons", "form-fields-and-toggle", "cards", "save-bar", "toast", "badges", "segmented-control", "data-table", "dialog"])
def test_component_is_defined_only_in_the_component_stylesheet(rule):
    offenders = [
        f"{path}: {match.group(0).strip()}"
        for path in _tracked(".css") if path != OWNER
        for match in rule.finditer((ROOT / path).read_text(encoding="utf-8"))
    ]
    assert offenders == []
    assert rule.search((ROOT / OWNER).read_text(encoding="utf-8"))


# One-sided edges and inset side shadows; status shows through icon, badge, text color or tint.
SIDE_EDGE = re.compile(r"(?:border-(?:left|inline-start)(?:-color)?|box-shadow)\s*:\s*([^;}]*)")
COLORED = re.compile(r"var\(--(?:accent|amethyst|good|warn|crit|sapphire)")


def _is_side_stripe(prop, value):
    if prop.startswith("box-shadow"):
        # A layer offset sideways only, without blur, paints a stripe, inset or outside.
        layers = re.split(r",(?![^(]*\))", value)
        return any(re.match(r"\s*(?:inset\s+)?-?[1-9]\d*px\s+0(?:px)?\s+0(?:px)?\s", layer) for layer in layers)
    if "transparent" in value.split("solid")[-1]:
        return False  # CSS triangles and hidden edges
    width = re.match(r"\s*(\d+)px", value)
    return bool(COLORED.search(value)) or (width is not None and int(width.group(1)) > 2)


def test_no_stylesheet_marks_status_with_a_colored_side_stripe():
    offenders = [
        f"{path}: {match.group(0).strip()}"
        for path in _tracked(".css")
        for match in SIDE_EDGE.finditer((ROOT / path).read_text(encoding="utf-8"))
        if _is_side_stripe(match.group(0), match.group(1))
    ]
    assert offenders == []


def test_the_retired_pill_tab_classes_are_gone():
    sources = _tracked(".css", ".js", ".html")
    # Class usage only; `trend-tabs` survives as an element id.
    retired = re.compile(r"\.(?:trend-tabs?|pill-tab)(?![\w-])|class=\"[^\"]*\b(?:trend-tabs?|pill-tab)(?![\w-])|'(?:trend-tab|pill-tab)'")
    offenders = [path for path in sources if retired.search((ROOT / path).read_text(encoding="utf-8"))]
    assert offenders == []


def test_segmented_groups_carry_no_layout_classes():
    # Layout classes on the group itself override its display and gap; wrap the group instead.
    groups = [
        (path, match.group(1))
        for path in _app_files() if path.endswith(".html")
        for match in re.finditer(r'class="([^"]*\bsegmented\b(?!-)[^"]*)"', (ROOT / path).read_text(encoding="utf-8"))
    ]
    assert groups
    assert [(path, classes) for path, classes in groups if classes not in ("segmented", "segmented segmented-fill")] == []


def _tables():
    """Yield (path, classes, name) for every table in templates and scripts."""
    for path in _tracked(".html", ".js"):
        lines = (ROOT / path).read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            for tag in re.findall(r"<table\b[^>]*>", line):
                classes = re.search(r'class="([^"]*)"', tag)
                ident = re.search(r'id="([^"]*)"', tag)
                classes = classes.group(1).split() if classes else []
                yield path, classes, ident.group(1) if ident else (classes[0] if classes else "")
            if "createElement('table')" in line:
                assigned = re.search(r"className\s*=\s*'([^']*)'", " ".join(lines[index:index + 3]))
                classes = assigned.group(1).split() if assigned else []
                yield path, classes, classes[0] if classes else ""


def test_tables_use_the_data_table_component():
    tables = list(_tables())
    missing = sorted({(path, name) for path, classes, name in tables if "data-table" not in classes})
    assert [entry for entry in missing if entry not in TABLES_WITHOUT_COMPONENT] == []
    # Every listed exception must still exist.
    assert sorted(TABLES_WITHOUT_COMPONENT - set(missing)) == []


def test_every_css_variable_in_use_is_defined():
    """A var() of an undefined name ignores the theme: its fallback, or nothing, applies instead."""
    sources = _tracked(".css", ".js", ".html", ".json")
    defined, used = set(), {}
    for path in sources:
        text = (ROOT / path).read_text(encoding="utf-8")
        defined.update(re.findall(r"(--[A-Za-z0-9-]+)\s*:", text))  # stylesheets and inline custom properties
        defined.update(re.findall(r"\"(--[A-Za-z0-9-]+)\"\s*:", text))  # theme catalogs
        defined.update(re.findall(r"setProperty\(\s*[\"'](--[A-Za-z0-9-]+)", text))  # values set at runtime
        for name in re.findall(r"var\((--[A-Za-z0-9-]+)", text):
            used.setdefault(name, set()).add(path)
    assert {name: sorted(paths) for name, paths in used.items() if name not in defined} == {}


def test_dialogs_use_the_dialog_component():
    dialogs = []
    for path in _tracked(".html", ".js"):
        text = (ROOT / path).read_text(encoding="utf-8")
        # Real dialog elements carry attributes; a bare "<dialog>" is prose in a comment.
        dialogs += [(path, tag) for tag in re.findall(r"<dialog\s[^>]+>", text)]
        if "createElement('dialog')" in text:
            dialogs += [(path, f'class="{name}"') for name in re.findall(r"dialog\.className\s*=\s*'([^']*)'", text)]
    assert dialogs

    def classes(tag):
        found = re.search(r'class="([^"]*)"', tag)
        return found.group(1).split() if found else []

    offenders = [
        (path, tag) for path, tag in dialogs
        if "modal-overlay" not in classes(tag) and not DIALOGS_WITHOUT_COMPONENT & set(classes(tag))
    ]
    assert offenders == []


# Tokens kept without a use: the largest radius step and the side safe-area insets complete their sets.
UNUSED_TOKENS_ALLOWED = {"--radius-xl", "--safe-left", "--safe-right"}


def test_every_base_token_is_used():
    sources = _tracked(".css", ".js", ".html")
    used = set()
    for path in sources:
        text = (ROOT / path).read_text(encoding="utf-8")
        used.update(re.findall(r"var\((--[A-Za-z0-9-]+)", text))
        used.update(re.findall(r"getPropertyValue\(\s*[\"'](--[A-Za-z0-9-]+)", text))
    defined = set(re.findall(r"(--[A-Za-z0-9-]+)\s*:", (ROOT / "app/static/css/tokens.css").read_text(encoding="utf-8")))
    # Deprecated aliases stay for community styles and themes.
    assert sorted(defined - used - UNUSED_TOKENS_ALLOWED - set(DEPRECATED_ALIASES)) == []
    assert UNUSED_TOKENS_ALLOWED <= defined
