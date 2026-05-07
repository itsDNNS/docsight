"""Static UI contracts for the modulation performance module."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULATION_JS = ROOT / "app" / "modules" / "modulation" / "static" / "main.js"
MODULATION_CSS = ROOT / "app" / "modules" / "modulation" / "static" / "style.css"
I18N_DIR = ROOT / "app" / "modules" / "modulation" / "i18n"


def test_distribution_day_bars_drill_into_intraday_detail():
    js = MODULATION_JS.read_text(encoding="utf-8")

    assert "function attachModulationDayClick" in js
    assert "attachModulationDayClick(chart, container, days)" in js
    assert "chart.posToVal" in js
    assert "modDrillIntoDay(day.date)" in js


def test_low_qam_trend_uses_fixed_percent_scale():
    js = MODULATION_JS.read_text(encoding="utf-8")

    assert "lowqam: { range: [0, 100] }" in js


def test_clickable_distribution_chart_has_pointer_cursor():
    css = MODULATION_CSS.read_text(encoding="utf-8")

    assert ".modulation-clickable-chart" in css
    assert "cursor: pointer" in css


def test_low_qam_hint_does_not_use_stale_global_16qam_threshold():
    js = MODULATION_JS.read_text(encoding="utf-8")

    assert "low_qam_denominator_hint" in js
    assert "\u2264 16QAM" not in js
    assert "\\u2264 16QAM" not in js


def test_low_qam_denominator_hint_is_localized_for_all_modulation_languages():
    for path in I18N_DIR.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        assert "low_qam_denominator_hint" in text, path.name


def test_distribution_chart_uses_context_aware_qam_color_helper():
    """Distribution chart color selection must be context-aware (per protocol group),
    not a global-only QAM_COLORS lookup. Issue #444."""
    js = MODULATION_JS.read_text(encoding="utf-8")

    assert "function qamColorForContext" in js, (
        "Expected helper qamColorForContext(mod, pg) for protocol-aware coloring"
    )

    render_match = re.search(
        r"function renderGroupDistChart\([^)]*\)\s*\{(.*?)\n\}\s*\n",
        js,
        re.DOTALL,
    )
    assert render_match, "Could not locate renderGroupDistChart body"
    body = render_match.group(1)

    assert "qamColorForContext(" in body, (
        "renderGroupDistChart must use the context-aware helper"
    )
    assert "QAM_COLORS[layer.mod]" not in body, (
        "renderGroupDistChart must not use the global QAM_COLORS map directly"
    )


def test_us_docsis_31_64qam_is_critical_and_128qam_is_warning():
    """US DOCSIS 3.1 upstream context: 64QAM and below in red family,
    128QAM amber/warning, 256QAM and above green/healthy. Issue #444."""
    js = MODULATION_JS.read_text(encoding="utf-8")

    assert "function qamColorForContext" in js, "qamColorForContext must be defined"

    map_match = re.search(
        r"(QAM_COLORS_US_DOCSIS_31|US_DOCSIS_31[A-Z_]*)\s*=\s*\{([^}]+)\}",
        js,
    )
    assert map_match, (
        "Expected a US DOCSIS 3.1 context color map (e.g. QAM_COLORS_US_DOCSIS_31)"
    )
    ctx_map = map_match.group(2)

    def color_for(level):
        m = re.search(r"'" + re.escape(level) + r"'\s*:\s*'(#[0-9a-fA-F]{6})'", ctx_map)
        assert m, f"US DOCSIS 3.1 context map missing entry for {level}"
        return m.group(1).lower()

    red_family = {"#ef4444", "#dc2626", "#b91c1c", "#f87171", "#fb7185"}
    amber_family = {"#f59e0b", "#fbbf24", "#d97706", "#f97316"}
    green_family = {"#22c55e", "#16a34a", "#15803d", "#86efac", "#14b8a6"}

    assert color_for("64QAM") in red_family, (
        "US DOCSIS 3.1 context: 64QAM must use a red-family hex"
    )
    assert color_for("128QAM") in amber_family, (
        "US DOCSIS 3.1 context: 128QAM must use an amber/warning hex"
    )
    assert color_for("256QAM") in green_family, (
        "US DOCSIS 3.1 context: 256QAM must use a green/healthy hex"
    )


def test_global_us_docsis_30_64qam_color_is_unchanged():
    """The global QAM_COLORS map must keep 64QAM at its existing yellow value
    so US DOCSIS 3.0 upstream is not painted red by default. Issue #444."""
    js = MODULATION_JS.read_text(encoding="utf-8")

    qam_colors_match = re.search(
        r"var QAM_COLORS\s*=\s*\{(.*?)\};",
        js,
        re.DOTALL,
    )
    assert qam_colors_match, "QAM_COLORS map must remain defined"
    qam_block = qam_colors_match.group(1)

    assert re.search(r"'64QAM'\s*:\s*'#eab308'", qam_block), (
        "Global QAM_COLORS['64QAM'] must remain '#eab308' for US DOCSIS 3.0"
    )


def test_low_qam_legend_hint_helper_is_context_aware():
    """A context-aware legend/helper text helper must exist so US DOCSIS 3.1
    upstream charts can explain why 64QAM is shown as Low-QAM. Issue #444."""
    js = MODULATION_JS.read_text(encoding="utf-8")

    assert "function lowQamLegendHintForContext" in js, (
        "Expected helper lowQamLegendHintForContext(pg)"
    )

    helper_match = re.search(
        r"function isUsDocsis31Upstream\([^)]*\)\s*\{(.*?)\n\}",
        js,
        re.DOTALL,
    )
    assert helper_match, "isUsDocsis31Upstream must be defined"
    assert "_modDirection" not in helper_match.group(1), (
        "Context classification must use the response render context, not mutable global direction"
    )
    assert "data-direction" in js and "data-docsis-version" in js, (
        "Protocol group markup should expose render context for scoped browser assertions"
    )


def test_low_qam_legend_hint_key_is_localized_for_all_modulation_languages():
    """Every modulation locale must define the DOCSIS 3.1 Low-QAM legend hint
    so the new context-aware copy is translatable. Issue #444."""
    for path in I18N_DIR.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        assert "low_qam_legend_hint_d31_us" in text, path.name
