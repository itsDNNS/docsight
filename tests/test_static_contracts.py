"""Static UI/CSS contract tests."""

import json
import os
import re
import subprocess
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEWS_CSS = ROOT / "app" / "static" / "css" / "views.css"
CORRELATION_JS = ROOT / "app" / "static" / "js" / "correlation.js"
CHART_ENGINE_JS = ROOT / "app" / "static" / "js" / "chart-engine.js"
TRENDS_JS = ROOT / "app" / "static" / "js" / "trends.js"
CHANNELS_JS = ROOT / "app" / "static" / "js" / "channels.js"
MODULATION_MAIN_JS = ROOT / "app" / "modules" / "modulation" / "static" / "main.js"
MODULATION_TEMPLATE = ROOT / "app" / "modules" / "modulation" / "templates" / "modulation_tab.html"
SW_JS = ROOT / "app" / "static" / "sw.js"
MAIN_CSS = ROOT / "app" / "static" / "css" / "main.css"
INDEX_HTML = ROOT / "app" / "templates" / "index.html"
NOTIFICATIONS_HTML = ROOT / "app" / "templates" / "settings" / "notifications.html"
APP_I18N_DIR = ROOT / "app" / "i18n"
EUROPEAN_LANGUAGE_PACK = {
    "bg", "cs", "da", "de", "el", "en", "es", "et", "fi", "fr",
    "ga", "hr", "hu", "it", "lt", "lv", "nb", "nl", "pl", "pt",
    "ro", "sk", "sl", "sv",
}
I18N_PLACEHOLDER_RE = re.compile(
    r"(</?[A-Za-z][^>]*>|&[a-zA-Z0-9#]+;|\{\{[^}]+\}\}|\{[^}]+\}|%\([^)]+\)[sd]|%[sd])"
)
I18N_PROTECTED_LITERALS = {"Apprise", "DOCSight", "dBmV", "Smokeping"}
I18N_EMPTY_TAG_RE = re.compile(r"<([A-Za-z][^>]*)>\s*</\1>")
I18N_LEADING_SENTINEL_RE = re.compile(r"^\s*@")
CM_CSS = ROOT / "app" / "modules" / "connection_monitor" / "static" / "style.css"
CM_DETAIL_JS = ROOT / "app" / "modules" / "connection_monitor" / "static" / "js" / "connection-monitor-detail.js"
CM_CHARTS_JS = ROOT / "app" / "modules" / "connection_monitor" / "static" / "js" / "connection-monitor-charts.js"
CM_CARD_JS = ROOT / "app" / "modules" / "connection_monitor" / "static" / "js" / "connection-monitor-card.js"
SEGMENT_UTILIZATION_JS = ROOT / "app" / "static" / "js" / "segment-utilization.js"
BQM_CHART_JS = ROOT / "app" / "modules" / "bqm" / "static" / "js" / "bqm-chart.js"
COMPARISON_MAIN_JS = ROOT / "app" / "modules" / "comparison" / "static" / "main.js"


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
    assert "_corrEventAllowed(e)" in table_block

    popover_block = js[js.index("cb.addEventListener('change'") : js.index("// Close on outside click")]
    assert "renderCorrelationChart(data)" in popover_block
    assert "renderCorrelationTable(data)" in popover_block


def test_correlation_event_severity_filter_applies_to_table_and_chart():
    js = CORRELATION_JS.read_text(encoding="utf-8")

    assert "var _corrEventSeverityFilter = {};" in js
    assert "function _corrEventSeverityAllowed" in js
    assert "function _corrEventAllowed" in js
    assert "function _corrEscapeAttr" in js
    assert "_CORR_SEVERITIES.indexOf(severity) !== -1 ? severity : 'info'" in js
    assert "_corrFilteredEvents(events)" in js
    filtered_block = js[js.index("function _corrFilteredEvents") : js.index("// Re-render chart")]
    assert "_corrEventAllowed(e)" in filtered_block
    table_block = js[js.index("function renderCorrelationTable") :]
    assert "_corrEventAllowed(e)" in table_block
    assert "data-event-severity" in js


def test_static_cache_version_was_bumped_for_ui_followup_assets():
    sw_js = SW_JS.read_text(encoding="utf-8")

    assert "var CACHE_VERSION = 'v38';" in sw_js
    assert "/static/css/main.css" in sw_js
    assert "/static/js/channels.js" in sw_js
    assert "/modules/docsight.connection_monitor/static/style.css" in sw_js
    assert "/modules/docsight.connection_monitor/static/js/connection-monitor-detail.js" in sw_js
    assert "/modules/docsight.modulation/static/main.js" in sw_js


def test_home_signal_family_sparklines_use_data_keys():
    template = INDEX_HTML.read_text(encoding="utf-8")
    sparklines_js = (ROOT / "app" / "static" / "js" / "sparklines.js").read_text(encoding="utf-8")

    assert "data-spark-key=\"{{ spark_key }}\"" in template
    assert "querySelectorAll('canvas.metric-spark[data-spark-key]')" in sparklines_js
    assert "canvas.dataset.sparkKey" in sparklines_js


def test_home_signal_family_modulation_rows_stack_below_status():
    css = MAIN_CSS.read_text(encoding="utf-8")
    start = css.index(".dashboard-view .metrics-grid .metric-modulation-row")
    block = css[start : css.index(".dashboard-view .metrics-grid .metric-context", start)]

    assert "display: block" in block
    assert "clear: both" in block
    assert "width: 100%" in block


def test_home_metric_range_bars_are_bottom_aligned_across_cards():
    css = MAIN_CSS.read_text(encoding="utf-8")
    card_block = css[
        css.index(".dashboard-view .metrics-grid .metric-card.glass {") :
        css.index(".dashboard-view .metrics-grid .metric-card.glass:hover")
    ]
    range_block = css[
        css.index(".dashboard-view .metrics-grid .metric-range-viz {") :
        css.index(".dashboard-view .metrics-grid .metric-range-caption", css.index(".dashboard-view .metrics-grid .metric-range-viz {"))
    ]

    assert "display: flex" in card_block
    assert "flex-direction: column" in card_block
    assert "margin-top: auto" in range_block
    assert "padding-top: 8px" in range_block


def test_home_signal_family_hint_uses_available_desktop_width():
    css = MAIN_CSS.read_text(encoding="utf-8")
    header_block = css[
        css.index(".dashboard-section-header > span {") :
        css.index(".dashboard-section-context", css.index(".dashboard-section-header > span {"))
    ]

    assert "max-width: min(72ch, calc(100vw - 24rem))" in header_block
    assert "text-wrap: pretty" in header_block
    assert "max-width: 38ch" not in header_block


def test_channels_weather_overlay_contract_is_wired():
    template = INDEX_HTML.read_text(encoding="utf-8")
    channels_js = CHANNELS_JS.read_text(encoding="utf-8")

    assert 'id="channel-temp-toggle-btn"' in template
    assert 'id="compare-temp-toggle-btn"' in template
    assert "function _getChannelWeatherRange" in channels_js
    assert "function _alignWeatherToChannelTimestamps" in channels_js
    assert "function _fetchChannelWeatherForTimestamps" in channels_js
    assert "function _updateChannelTempToggle" in channels_js
    assert "function _updateCompareTempToggle" in channels_js
    assert "_renderChannelTimelineCharts()" in channels_js
    assert "_renderCompareCharts()" in channels_js
    assert "tempData: _lastChannelWeather" in channels_js
    assert "tempData: _lastCompareWeather" in channels_js


def test_channels_modulation_charts_receive_temperature_overlay_options():
    channels_js = CHANNELS_JS.read_text(encoding="utf-8")
    timeline_block = channels_js[
        channels_js.index("renderChart('chart-ch-modulation'") : channels_js.index("function loadChannelTimeline")
    ]
    compare_block = channels_js[
        channels_js.index("renderChart('chart-cmp-modulation'") : channels_js.index("function loadCompareCharts")
    ]

    assert "tempData:" in timeline_block
    assert "tempByTimestamp" in timeline_block
    assert "tempByTimestamp[d.timestamp] = _lastChannelWeather[idx]" in channels_js
    assert "tempData:" in compare_block
    assert "_lastCompareWeather" in compare_block


def test_channels_chart_contracts_disable_implicit_points_and_zoom_fill():
    channels_js = CHANNELS_JS.read_text(encoding="utf-8")
    chart_engine = CHART_ENGINE_JS.read_text(encoding="utf-8")
    zoom_block = chart_engine[chart_engine.index("function openChartZoom") :]

    assert "showPoints: false" in channels_js[channels_js.index("var powerDatasets") : channels_js.index("renderChart('chart-ch-power'")]
    assert "showPoints: false" in channels_js[channels_js.index("var powerDatasets = _compareChannels.map") : channels_js.index("renderChart('chart-cmp-power'")]
    assert "var zoomShowPoints = ds.showPoints;" in zoom_block
    assert "if (zoomShowPoints === undefined) zoomShowPoints = n <= 30 && !isBar;" in zoom_block
    assert "points: { show: zoomShowPoints" in zoom_block
    assert "fill: isBar ? (ds.color || '#a855f7') + 'cc' : (ds.fill || (!isMulti && !isBar ? 'rgba(168,85,247,0.15)' : undefined))" not in zoom_block
    assert "fill: isBar ? (ds.color || '#a855f7') + 'cc' : (ds.fill || undefined)" in zoom_block


def test_channels_controls_and_compare_titles_are_standardized():
    template = INDEX_HTML.read_text(encoding="utf-8")
    channel_toggle = template[template.index('id="channel-temp-toggle-btn"') : template.index('id="channel-compare-controls"')]
    compare_toggle = template[template.index('id="compare-temp-toggle-btn"') : template.index('id="channel-no-data"')]
    compare_charts = template[template.index('id="compare-charts"') : template.index('id="compare-errors-card"')]

    assert "<svg" in channel_toggle
    assert "<svg" in compare_toggle
    assert "{{ t.power_dbmv }}" in compare_charts
    assert "{{ t.snr_db }}" in compare_charts
    assert "{{ t.power_history }}" not in compare_charts
    assert "{{ t.snr_history }}" not in compare_charts


def test_chart_time_range_controls_use_normalized_existing_ranges():
    template = INDEX_HTML.read_text(encoding="utf-8")
    cm_template = (ROOT / "app" / "modules" / "connection_monitor" / "templates" / "connection_monitor_detail.html").read_text(encoding="utf-8")
    expected_labels = ["1h", "6h", "1d", "2d", "3d", "7d", "30d", "90d"]
    expected_values = ["1h", "6h", "1d", "2d", "3d", "7d", "30d", "90d"]
    expected_seconds = ["3600", "21600", "86400", "172800", "259200", "604800", "2592000", "7776000"]

    def block(source, start, end):
        start_idx = source.index(start)
        return source[start_idx : source.index(end, start_idx)]

    def button_texts(html):
        return re.findall(r"<button[^>]*>([^<{]+)</button>", html)

    def data_values(html):
        return re.findall(r"data-(?:range|value)=\"([^\"]+)\"", html)

    controls = {
        "trend": block(template, 'id="trend-tabs"', '</div>'),
        "correlation": block(template, 'id="correlation-tabs"', '</div>'),
        "channel": block(template, 'id="channel-time-tabs"', '</div>'),
        "compare": block(template, 'id="compare-time-tabs"', '</div>'),
    }
    for name, html in controls.items():
        assert button_texts(html) == expected_labels, name
        assert data_values(html) == expected_values, name

    cm_picker = block(cm_template, 'class="cm-range-picker', '</div>')
    assert "trend-tabs" in cm_picker
    assert button_texts(cm_picker) == expected_labels
    assert re.findall(r"data-cm-range=\"([^\"]+)\"", cm_picker) == expected_seconds


def test_chart_axis_label_formatter_contract_is_range_normalized():
    script = f"""
const fs = require('fs');
const vm = require('vm');
const code = fs.readFileSync({str(CHART_ENGINE_JS)!r}, 'utf8');
const context = {{ console: console, window: {{ devicePixelRatio: 1 }} }};
vm.createContext(context);
vm.runInContext(code, context);
const fmt = context.docsightFormatXAxisLabel;
if (typeof fmt !== 'function') {{
  throw new Error('docsightFormatXAxisLabel is not defined');
}}
const tsMs = Date.UTC(2026, 0, 2, 3, 4, 0);
const tsSec = Math.floor(tsMs / 1000);
const cases = [
  [tsMs, '1h', '03:04'],
  [tsMs, '6h', '03:04'],
  [tsMs, '1d', '03:04'],
  [tsMs, '2d', '01-02 03:04'],
  [tsMs, '3d', '01-02 03:04'],
  [tsMs, '7d', '01-02 03:04'],
  [tsMs, '30d', '01-02'],
  [tsMs, '90d', '01-02'],
  [tsMs, 'bqm', '03:04'],
  [tsSec, 24, '03:04'],
  [tsSec, 168, '01-02 03:04'],
  [tsSec, 720, '01-02'],
  [tsSec, '168', '01-02 03:04'],
  [tsSec, '720', '01-02'],
  [tsSec, '86400s', '03:04'],
  [tsSec, '604800s', '01-02 03:04'],
  [tsSec, '2592000s', '01-02'],
  [tsSec, 2160, '01-02'],
];
for (const [ts, range, expected] of cases) {{
  const actual = fmt(ts, range);
  if (actual !== expected) {{
    throw new Error(`${{range}} expected ${{expected}} but got ${{actual}}`);
  }}
}}
"""
    env = os.environ.copy()
    env["TZ"] = "UTC"
    result = subprocess.run(["node", "-e", script], cwd=ROOT, env=env, text=True, capture_output=True, check=False)

    assert result.returncode == 0, result.stderr + result.stdout


def test_chart_axis_labels_use_shared_formatter_across_graphs():
    chart_engine = CHART_ENGINE_JS.read_text(encoding="utf-8")
    graph_sources = {
        "trends": TRENDS_JS,
        "channels": CHANNELS_JS,
        "correlation": CORRELATION_JS,
        "connection_monitor": CM_CHARTS_JS,
        "segment_utilization": SEGMENT_UTILIZATION_JS,
        "bqm": BQM_CHART_JS,
        "comparison": COMPARISON_MAIN_JS,
    }

    assert "function docsightFormatXAxisLabel" in chart_engine
    assert "function docsightFormatXAxisLabels" in chart_engine
    for name, path in graph_sources.items():
        js = path.read_text(encoding="utf-8")
        assert "docsightFormatXAxisLabel" in js or "docsightFormatXAxisLabels" in js, name

    legacy_patterns = {
        "DD.MM axis labels": r"return dd \+ '\\.' \+ mo|return day \+ '\\.' \+ month|p2\(d\.getDate\(\)\) \+ '\\.'",
        "slash date axis labels": r"getMonth\(\) \+ 1\) \+ '/' \+ d\.getDate",
        "manual ISO axis labels": r"substring\(5, 16\)\.replace\('T', ' '\)|substring\(11, 16\)|formatDateDE\(d\.date\)",
        "relative comparison hour labels": r"hourLabels\.map\(function\(h\) \{ return h \+ hrsLabel; \}\)",
    }
    offenders = []
    for name, path in graph_sources.items():
        js = path.read_text(encoding="utf-8")
        for label, pattern in legacy_patterns.items():
            if re.search(pattern, js):
                offenders.append(f"{name}: {label}")

    assert offenders == []


def test_modulation_range_control_uses_normalized_labels_while_preserving_today():
    template = MODULATION_TEMPLATE.read_text(encoding="utf-8")
    range_tabs = template[template.index('id="modulation-range-tabs"') : template.index('</div>', template.index('id="modulation-range-tabs"'))]
    labels_by_days = {
        days: re.sub(r"\s+", " ", label).strip()
        for days, label in re.findall(r'<button class="trend-tab(?: active)?" data-days="(\d+)">(.*?)</button>', range_tabs, re.S)
    }

    assert set(labels_by_days) == {"1", "7", "30"}
    assert labels_by_days["1"] == "{{ t.get('docsight.modulation.today', 'Today') }}"
    assert labels_by_days["7"] == "7d"
    assert labels_by_days["30"] == "30d"


def test_channels_legacy_days_hashes_normalize_to_range_tabs():
    channels_js = CHANNELS_JS.read_text(encoding="utf-8")

    assert "function _normalizeChannelRangeValue" in channels_js
    assert "if (/^\\d+$/.test(raw)) raw = raw + 'd';" in channels_js
    assert "var allowed = ['1h', '6h', '1d', '2d', '3d', '7d', '30d', '90d'];" in channels_js
    assert "return allowed.indexOf(raw) !== -1 ? raw : '1d';" in channels_js
    assert "_normalizeChannelRangeValue(params.range || params.days || '1d')" in channels_js


def test_trend_title_uses_rolling_range_without_stale_date_suffix():
    trends_js = TRENDS_JS.read_text(encoding="utf-8")

    assert "title.textContent = (T.signal_trends || 'Signal Trends') + ' (' + label + ')'" in trends_js
    assert "formatDateDE(date)" not in trends_js
    assert "&date=" not in trends_js


def test_hero_chart_fetches_normalized_one_day_range():
    hero_chart_js = (ROOT / "app" / "static" / "js" / "hero-chart.js").read_text(encoding="utf-8")

    assert "fetch('/api/trends?range=1d')" in hero_chart_js
    assert "fetch('/api/trends?range=week')" not in hero_chart_js


def test_temperature_controls_are_consistently_after_time_range_controls_without_new_selectors():
    template = INDEX_HTML.read_text(encoding="utf-8")
    trend_header = template[template.index('id="view-trends"') : template.index('id="trend-no-data"')]
    channel_controls = template[template.index('id="channel-timeline-controls"') : template.index('id="channel-compare-controls"')]
    compare_controls = template[template.index('id="channel-compare-controls"') : template.index('id="channel-no-data"')]
    correlation_header = template[template.index('id="view-correlation"') : template.index('id="correlation-loading"')]

    assert trend_header.index('id="trend-tabs"') < trend_header.index('id="temp-toggle-btn"')
    assert channel_controls.index('id="channel-time-tabs"') < channel_controls.index('id="channel-temp-toggle-btn"')
    assert compare_controls.index('id="compare-time-tabs"') < compare_controls.index('id="compare-temp-toggle-btn"')
    assert 'correlation-temp-toggle' not in correlation_header


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
    assert "maxXTicks: 4" in channels_js


def test_chart_zoom_uses_bounded_index_ticks_instead_of_all_samples():
    js = CHART_ENGINE_JS.read_text(encoding="utf-8")
    zoom_block = js[js.index("function openChartZoom") :]

    assert "function buildEvenIndexTicks" in js
    assert "calculateMaxXTicks(params.labels, w, zoomYAxisSize, 10)" in zoom_block
    assert "var zoomXSplits = buildEvenIndexTicks(n, zoomMaxTicks);" in zoom_block
    assert "for (var i = 0; i < n; i++) o.push(i); return o;" not in zoom_block
    assert "filter: xTickValues" not in zoom_block


def test_trend_single_metric_charts_fill_to_visible_axis_floor():
    chart_engine = CHART_ENGINE_JS.read_text(encoding="utf-8")
    trends = TRENDS_JS.read_text(encoding="utf-8")
    snr_block = trends[trends.index("renderChart('chart-ds-snr'") : trends.index("renderChart('chart-us-power'")]

    assert "function fillToScaleMin" in chart_engine
    assert "if (ds.fillTo !== undefined && ds.fillTo !== null) s.fillTo = ds.fillTo;" in chart_engine
    assert "fill: isBar ? (ds.color || '#a855f7') + 'cc' : (ds.fill || undefined)" in chart_engine
    assert "var POWER_TREND_FILL" in trends
    assert "fill: POWER_TREND_FILL" in snr_block
    assert "fillTo: fillToScaleMin" in snr_block
    assert trends.count("fill: POWER_TREND_FILL") >= 3


def test_connection_monitor_card_treats_no_enabled_targets_as_no_data():
    js = CM_CARD_JS.read_text(encoding="utf-8")
    no_enabled_block = js[js.index("if (enabled.length === 0)") : js.index("var ok = enabled.filter")]

    assert "statusEl.textContent = '—';" in no_enabled_block
    assert "detailsEl.textContent = '';" in no_enabled_block


def test_modulation_overview_charts_bound_daily_x_axis_ticks():
    js = MODULATION_MAIN_JS.read_text(encoding="utf-8")
    dist_block = js[js.index("function renderGroupDistChart") : js.index("function attachModulationDayClick")]
    trend_block = js[js.index("function renderGroupTrendChart") : js.index("/* ── Intraday")]

    assert "function buildModulationXAxisTicks" in js
    assert "calculateMaxXTicks(labels, width" in js
    assert "buildEvenIndexTicks(labels.length" in js
    assert "var xSplits = buildModulationXAxisTicks(labels, w);" in dist_block
    assert "var xSplits = buildModulationXAxisTicks(labels, w);" in trend_block
    assert "splits: function() { return xSplits; }" in dist_block
    assert "splits: function() { return xSplits; }" in trend_block
    assert "splits: function() { return xData; }" not in dist_block
    assert "splits: function() { return xData; }" not in trend_block


def test_downstream_channel_modulation_column_exposes_health_classification():
    template = INDEX_HTML.read_text(encoding="utf-8")
    ds_table_block = template[template.index("DOWNSTREAM CHANNELS") : template.index("UPSTREAM CHANNELS")]

    assert '<td data-health="{{ ch.modulation_health or \'good\' }}">{{ ch.modulation }}</td>' in ds_table_block


def test_notification_settings_expose_channel_change_warning_cooldown():
    template = NOTIFICATIONS_HTML.read_text(encoding="utf-8")

    assert "cooldown_row('channel_change', t.notify_event_channel_change, 'info'" in template
    assert "cooldown_row('channel_change', t.notify_event_channel_change, 'warning'" in template


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
        "dashboard_modulation_context",
        "dashboard_modulation_open_detail",
        "dashboard_modulation_unavailable",
        "dashboard_modulation_missing_hint",
        "dashboard_modulation_normal",
        "dashboard_modulation_us_cause",
        "dashboard_modulation_ds_detail_hint",
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


def test_european_language_pack_files_cover_core_and_modules():
    """Every built-in i18n catalog participates in the European language pack."""
    i18n_dirs = [APP_I18N_DIR] + sorted((ROOT / "app" / "modules").glob("*/i18n"))
    offenders = []
    for i18n_dir in i18n_dirs:
        if not (i18n_dir / "en.json").exists():
            continue
        present = {path.stem for path in i18n_dir.glob("*.json") if path.stem != "template"}
        missing = sorted(EUROPEAN_LANGUAGE_PACK - present)
        if missing:
            offenders.append(f"{i18n_dir.relative_to(ROOT)} missing {', '.join(missing)}")

    assert offenders == []


def test_european_language_pack_metadata_and_key_parity():
    """Core locale files are selectable and structurally complete."""
    en = json.loads((APP_I18N_DIR / "en.json").read_text(encoding="utf-8-sig"))
    expected_keys = set(en.keys())
    offenders = []
    for code in sorted(EUROPEAN_LANGUAGE_PACK):
        path = APP_I18N_DIR / f"{code}.json"
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        meta = data.get("_meta", {})
        if not meta.get("language_name") or meta.get("language_name") == code:
            offenders.append(f"{code}: missing native language_name")
        if not meta.get("flag"):
            offenders.append(f"{code}: missing flag")
        missing = sorted(expected_keys - set(data.keys()))
        extra = sorted(set(data.keys()) - expected_keys)
        if missing or extra:
            offenders.append(f"{code}: missing={missing[:5]} extra={extra[:5]}")

    assert offenders == []


def test_european_language_pack_preserves_catalog_contracts():
    """Every catalog keeps key, list, and placeholder contracts intact."""
    offenders = []

    def walk(path_label, source, target):
        if isinstance(source, dict) and isinstance(target, dict):
            missing = sorted(set(source) - set(target))
            extra = sorted(set(target) - set(source))
            if missing or extra:
                offenders.append(f"{path_label}: missing={missing[:5]} extra={extra[:5]}")
            for key in source:
                if key in target:
                    walk(f"{path_label}.{key}", source[key], target[key])
        elif isinstance(source, list) and isinstance(target, list):
            if len(source) != len(target) and not path_label.endswith(".isp_options"):
                offenders.append(f"{path_label}: list length {len(target)} != {len(source)}")
            for idx, (source_item, target_item) in enumerate(zip(source, target)):
                walk(f"{path_label}[{idx}]", source_item, target_item)
        elif isinstance(source, str) and isinstance(target, str):
            if "ZXQ" in target or "@@@" in target:
                offenders.append(f"{path_label}: leaked translation sentinel")
            if I18N_LEADING_SENTINEL_RE.search(target):
                offenders.append(f"{path_label}: leaked leading translation sentinel")
            if I18N_EMPTY_TAG_RE.search(target):
                offenders.append(f"{path_label}: empty HTML tag")
            for literal in I18N_PROTECTED_LITERALS:
                if literal in source and literal not in target:
                    offenders.append(f"{path_label}: missing protected literal {literal}")
            source_placeholders = Counter(I18N_PLACEHOLDER_RE.findall(source))
            target_placeholders = Counter(I18N_PLACEHOLDER_RE.findall(target))
            if source_placeholders != target_placeholders:
                offenders.append(f"{path_label}: placeholder mismatch")

    i18n_dirs = [APP_I18N_DIR] + sorted((ROOT / "app" / "modules").glob("*/i18n"))
    for i18n_dir in i18n_dirs:
        source_path = i18n_dir / "en.json"
        if not source_path.exists():
            continue
        source = json.loads(source_path.read_text(encoding="utf-8-sig"))
        for code in sorted(EUROPEAN_LANGUAGE_PACK):
            path = i18n_dir / f"{code}.json"
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            walk(f"{path.relative_to(ROOT)}", source, data)

    assert offenders == []


def test_dashboard_insight_layout_uses_safe_responsive_columns():
    css = MAIN_CSS.read_text(encoding="utf-8")

    assert "grid-template-columns: 42px minmax(0, 1fr);" in css
    assert "grid-column: 2;" in css
    assert "minmax(280px, 1fr) minmax(230px" not in css


def test_dashboard_modulation_layout_is_sidecar_not_below_channel_health():
    css = MAIN_CSS.read_text(encoding="utf-8")
    template = INDEX_HTML.read_text(encoding="utf-8")
    visual_block = css[css.index(".dashboard-hero .hero-visual-row {") : css.index(".dashboard-hero .hero-chart-wrap {")]
    health_block = css[css.index(".dashboard-hero .hero-channel-health {") : css.index(".dashboard-hero .hero-channel-health-head")]

    assert "grid-template-columns: var(--hero-side-col) minmax(150px, 180px) minmax(0, 1fr);" in visual_block
    assert "align-items: start;" in visual_block
    assert "grid-column: 2;" in css[css.index(".dashboard-hero .hero-modulation-context {") : css.index(".dashboard-hero .hero-modulation-head {")]
    assert "<aside class=\"hero-channel-health" in template
    assert template.index('class="hero-channel-health"') < template.index('class="hero-modulation-context"') < template.index('class="hero-chart-wrap"')
    assert "grid-template-rows: auto minmax(0, 1fr);" not in health_block


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
