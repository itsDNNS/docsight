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


def test_us_docsis_31_low_qam_colors_are_easy_to_distinguish():
    """Adjacent low-QAM levels need enough palette separation for screenshots.
    Issue #447."""
    js = MODULATION_JS.read_text(encoding="utf-8")
    map_match = re.search(
        r"QAM_COLORS_US_DOCSIS_31\s*=\s*\{([^}]+)\}",
        js,
    )
    assert map_match, "Expected US DOCSIS 3.1 context color map"
    ctx_map = map_match.group(1)

    def color_for(level):
        m = re.search(r"'" + re.escape(level) + r"'\s*:\s*'(#[0-9a-fA-F]{6})'", ctx_map)
        assert m, f"US DOCSIS 3.1 context map missing entry for {level}"
        return m.group(1).lower()

    assert color_for("32QAM") in {"#dc2626", "#b91c1c"}, (
        "US DOCSIS 3.1 context: 32QAM should use a darker red than 64QAM"
    )
    assert color_for("64QAM") in {"#fb7185", "#f87171", "#ef4444"}, (
        "US DOCSIS 3.1 context: 64QAM should remain red-family but distinct from 32QAM"
    )
    assert color_for("32QAM") != color_for("64QAM"), (
        "US DOCSIS 3.1 context: 32QAM and 64QAM must not share a color"
    )


def test_us_docsis_30_upstream_uses_own_healthy_64qam_palette():
    """US DOCSIS 3.0 upstream has a different visual semantic: 64QAM is
    the healthy maximum, 32QAM is reduced/warning, and 16QAM and below are low.
    Issue #447."""
    js = MODULATION_JS.read_text(encoding="utf-8")

    assert "function isUsDocsis30Upstream" in js, (
        "Expected explicit US DOCSIS 3.0 upstream context helper"
    )
    map_match = re.search(
        r"QAM_COLORS_US_DOCSIS_30\s*=\s*\{([^}]+)\}",
        js,
    )
    assert map_match, "Expected US DOCSIS 3.0 upstream context color map"
    ctx_map = map_match.group(1)

    def color_for(level):
        m = re.search(r"'" + re.escape(level) + r"'\s*:\s*'(#[0-9a-fA-F]{6})'", ctx_map)
        assert m, f"US DOCSIS 3.0 context map missing entry for {level}"
        return m.group(1).lower()

    assert color_for("64QAM") in {"#22c55e", "#16a34a", "#15803d", "#86efac"}, (
        "US DOCSIS 3.0 upstream: 64QAM must read as healthy/green"
    )
    assert color_for("32QAM") in {"#f59e0b", "#f97316", "#d97706", "#fbbf24"}, (
        "US DOCSIS 3.0 upstream: 32QAM must read as warning/reduced modulation"
    )
    assert color_for("16QAM") in {"#ef4444", "#dc2626", "#b91c1c", "#f87171"}, (
        "US DOCSIS 3.0 upstream: 16QAM and below must read as low/degraded"
    )


def test_us_docsis_30_upstream_context_does_not_match_downstream():
    """The DOCSIS 3.0 upstream palette must stay scoped to upstream groups.
    Downstream DOCSIS 3.0 keeps the default/global chart colors. Issue #447."""
    js = MODULATION_JS.read_text(encoding="utf-8")
    helper_match = re.search(
        r"function isUsDocsis30Upstream\([^)]*\)\s*\{(.*?)\n\}",
        js,
        re.DOTALL,
    )
    assert helper_match, "isUsDocsis30Upstream must be defined"
    helper_body = helper_match.group(1)
    assert "direction === 'us'" in helper_body, (
        "DOCSIS 3.0 context coloring must be scoped to upstream only"
    )
    assert "String(pg.docsis_version || '') === '3.0'" in helper_body, (
        "DOCSIS 3.0 context coloring must require the 3.0 protocol group"
    )


def test_global_us_docsis_30_64qam_color_is_unchanged():
    """The global QAM_COLORS map must keep 64QAM at its existing yellow value
    so non-contextual/default charts are unchanged. Issue #444/#447."""
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


def test_docsis_30_upstream_legend_hint_key_is_localized_for_all_modulation_languages():
    """Every modulation locale must define the DOCSIS 3.0 upstream legend hint.
    Issue #447."""
    for path in I18N_DIR.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        assert "low_qam_legend_hint_d30_us" in text, path.name
