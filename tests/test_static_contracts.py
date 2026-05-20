"""Static UI/CSS contract tests."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEWS_CSS = ROOT / "app" / "static" / "css" / "views.css"
CORRELATION_JS = ROOT / "app" / "static" / "js" / "correlation.js"
CHART_ENGINE_JS = ROOT / "app" / "static" / "js" / "chart-engine.js"
CHANNELS_JS = ROOT / "app" / "static" / "js" / "channels.js"
SW_JS = ROOT / "app" / "static" / "sw.js"
MAIN_CSS = ROOT / "app" / "static" / "css" / "main.css"
INDEX_HTML = ROOT / "app" / "templates" / "index.html"
APP_I18N_DIR = ROOT / "app" / "i18n"
CM_CSS = ROOT / "app" / "modules" / "connection_monitor" / "static" / "style.css"
CM_DETAIL_JS = ROOT / "app" / "modules" / "connection_monitor" / "static" / "js" / "connection-monitor-detail.js"
CM_CHARTS_JS = ROOT / "app" / "modules" / "connection_monitor" / "static" / "js" / "connection-monitor-charts.js"


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


def test_static_cache_version_was_bumped_for_ui_followup_assets():
    sw_js = SW_JS.read_text(encoding="utf-8")

    assert "var CACHE_VERSION = 'v11';" in sw_js
    assert "/static/css/main.css" in sw_js
    assert "/modules/docsight.connection_monitor/static/style.css" in sw_js
    assert "/modules/docsight.connection_monitor/static/js/connection-monitor-detail.js" in sw_js


def test_chart_engine_has_configurable_axis_padding_for_long_qam_labels():
    js = CHART_ENGINE_JS.read_text(encoding="utf-8")
    channels_js = CHANNELS_JS.read_text(encoding="utf-8")

    assert "DEFAULT_Y_AXIS_SIZE" in js
    assert "DEFAULT_ZOOM_Y_AXIS_SIZE" in js
    assert "DEFAULT_X_EDGE_PADDING" in js
    assert "function calculateXEdgePadding" in js
    assert "function calculateMaxXTicks" in js
    assert "opts.yAxisSize" in js
    assert "params.opts.zoomYAxisSize" in js
    assert "xData[0] - xEdgePadding" in js
    assert "xData[xData.length - 1] + xEdgePadding" in js
    assert "calculateMaxXTicks(labels, width, yAxisSize" in js
    assert "yAxisSize: 72" in channels_js
    assert "zoomYAxisSize: 80" in channels_js


def test_chart_zoom_uses_bounded_index_ticks_instead_of_all_samples():
    js = CHART_ENGINE_JS.read_text(encoding="utf-8")
    zoom_block = js[js.index("function openChartZoom") :]

    assert "function buildEvenIndexTicks" in js
    assert "calculateMaxXTicks(params.labels, w, zoomYAxisSize, 10)" in zoom_block
    assert "var zoomXSplits = buildEvenIndexTicks(n, zoomMaxTicks);" in zoom_block
    assert "for (var i = 0; i < n; i++) o.push(i); return o;" not in zoom_block
    assert "filter: xTickValues" not in zoom_block


def test_dashboard_i18n_keys_exist_in_all_language_files():
    required_keys = {
        "dashboard_signal_trend",
        "dashboard_signal_scope",
        "dashboard_channel_health",
        "dashboard_section_channels",
        "dashboard_section_overview",
        "dashboard_key_metrics",
        "dashboard_key_metrics_hint",
        "dashboard_channel_details",
        "dashboard_channel_details_hint",
    }
    template = INDEX_HTML.read_text(encoding="utf-8")
    missing_from_template = [key for key in required_keys if key not in template]
    assert missing_from_template == []

    offenders = []
    for path in sorted(APP_I18N_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        missing = sorted(required_keys - data.keys())
        if missing:
            offenders.append(f"{path.name}: {', '.join(missing)}")

    assert offenders == []


def test_dashboard_insight_layout_uses_safe_responsive_columns():
    css = MAIN_CSS.read_text(encoding="utf-8")

    assert "grid-template-columns: 42px minmax(0, 1fr);" in css
    assert "grid-column: 2;" in css
    assert "minmax(280px, 1fr) minmax(230px" not in css


def test_connection_monitor_mobile_pinned_bar_stays_hidden_by_default():
    css = CM_CSS.read_text(encoding="utf-8")
    mobile_block = css[css.index("@media (max-width: 760px)") :]

    assert ".cm-pinned-bar," not in mobile_block
    assert ".cm-pinned-bar {\n        display: flex;" not in mobile_block


def test_connection_monitor_no_data_clears_range_bound_panels():
    js = CM_DETAIL_JS.read_text(encoding="utf-8")
    show_block = js[js.index("function showNoData") : js.index("function hideNoData")]

    assert "cm-stats-cards" in show_block
    assert "cm-outage-panel" in show_block
    assert "textContent = ''" in show_block


def test_connection_monitor_interactions_expose_keyboard_and_state():
    js = CM_DETAIL_JS.read_text(encoding="utf-8")

    assert "setAttribute('aria-pressed'" in js
    assert "cm-pinned-chip" in js
    assert "removeBtn = document.createElement('button')" in js
    assert "removedActiveDay" in js
    assert "var toggleBtn = document.createElement('button')" in js
    assert "toggleBtn.setAttribute('aria-expanded'" in js
    assert "tr.tabIndex = 0" not in js
    assert "tr.setAttribute('role', 'button')" not in js


def test_connection_monitor_availability_and_table_semantics_are_accessible():
    js = CM_CHARTS_JS.read_text(encoding="utf-8")
    css = CM_CSS.read_text(encoding="utf-8")

    assert "container.setAttribute('role', 'img')" in js
    assert "container.setAttribute('aria-label'" in js
    assert "dataset.lAvailability" in js
    assert "removeAttribute('aria-label')" in CM_DETAIL_JS.read_text(encoding="utf-8")
    assert "cm-visually-hidden" in css
    assert "#cm-per-target-stats .cm-target-table thead {\n    display: none;" not in css
