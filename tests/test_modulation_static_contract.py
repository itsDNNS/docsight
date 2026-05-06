"""Static UI contracts for the modulation performance module."""

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
