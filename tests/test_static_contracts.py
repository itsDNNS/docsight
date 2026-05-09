"""Static UI/CSS contract tests."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEWS_CSS = ROOT / "app" / "static" / "css" / "views.css"
CORRELATION_JS = ROOT / "app" / "static" / "js" / "correlation.js"
SW_JS = ROOT / "app" / "static" / "sw.js"


def test_correlation_timeline_sticky_header_uses_opaque_surface():
    css = VIEWS_CSS.read_text(encoding="utf-8")
    header_block = css[css.index("#correlation-table thead th") : css.index("#correlation-table tbody tr")]

    assert "position: sticky" in header_block
    assert "background: var(--card-bg" in header_block
    assert "rgba(0,0,0,0.15)" not in header_block
    assert "z-index: 3" in header_block


def test_correlation_table_uses_stable_desktop_columns():
    css = VIEWS_CSS.read_text(encoding="utf-8")
    table_block = css[css.index("#correlation-table {") : css.index("#correlation-table thead tr")]

    assert "table-layout: fixed" in table_block
    assert ".correlation-cell-timestamp" in css
    assert ".correlation-cell-source" in css
    assert ".correlation-cell-message" in css
    assert ".correlation-cell-details" in css


def test_correlation_legend_matches_home_signal_order_and_labels():
    js = CORRELATION_JS.read_text(encoding="utf-8")

    ds_idx = js.index("metric: 'dsPower'")
    us_idx = js.index("metric: 'txPower'")
    snr_idx = js.index("metric: 'snr'")

    assert ds_idx < us_idx < snr_idx
    assert "T.chart_ds_power || 'DS Power (dBmV)'" in js
    assert "T.chart_us_power || 'US Power (dBmV)'" in js
    assert "T.chart_snr || 'SNR (dB)'" in js


def test_correlation_chart_omits_standalone_snr_axis_labels():
    js = CORRELATION_JS.read_text(encoding="utf-8")

    assert "ctx.fillText(s + ' dB'" not in js
    assert "T.chart_snr_axis || 'SNR (dB)'" not in js


def test_correlation_event_type_filter_applies_to_table_and_chart():
    js = CORRELATION_JS.read_text(encoding="utf-8")

    assert "function _corrEventTypeAllowed" in js
    assert "_corrFilteredEvents(events)" in js
    table_block = js[js.index("function renderCorrelationTable") :]
    assert "_corrEventTypeAllowed(e)" in table_block

    popover_block = js[js.index("cb.addEventListener('change'") : js.index("// Close on outside click")]
    assert "renderCorrelationChart(data)" in popover_block
    assert "renderCorrelationTable(data)" in popover_block


def test_static_cache_version_was_bumped_for_correlation_assets():
    sw_js = SW_JS.read_text(encoding="utf-8")

    assert "var CACHE_VERSION = 'v9';" in sw_js
