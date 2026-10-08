/* ═══ DOCSight Chart Engine ═══ */
/* uPlot rendering with DOCSIS threshold zones, zoom modal, and shared chart registry */

/* ── Shared State ── */
var charts = {};
var _tempOverlayVisible = false;
var currentView = 'live';
var DEFAULT_Y_AXIS_SIZE = 58;
var DEFAULT_ZOOM_Y_AXIS_SIZE = 64;
var DEFAULT_X_EDGE_PADDING = 1.5;
var TEMP_AXIS_SIZE = 40;
/* Dense series: half a sample, enough for the outermost bar. */
var DENSE_X_EDGE_PADDING = 0.5;

/* ── Shared Helpers ── */
// TEMPERATURE_UNIT is set by index.html; default to celsius if not present
if (typeof TEMPERATURE_UNIT === 'undefined') { var TEMPERATURE_UNIT = 'celsius'; }
function fmtTemp(celsius) {
    if (celsius == null) return '';
    if (TEMPERATURE_UNIT === 'fahrenheit') return (celsius * 9 / 5 + 32).toFixed(1) + ' °F';
    return celsius.toFixed(1) + ' °C';
}
function fmtTempAxis(celsius) {
    if (celsius == null) return '';
    if (TEMPERATURE_UNIT === 'fahrenheit') return Math.round(celsius * 9 / 5 + 32) + '°';
    return celsius.toFixed(0) + '°';
}
/* Compact k/M number. With `step` (the distance between axis ticks) every label
   gets as many decimals as the step needs, so close ticks stay distinct
   ("35.08k", "35.10k" instead of "35.1k" twice). Steps that would need more than
   two decimals read better as the full number ("35,058"). */
function fmtK(v, step) {
    if (v == null) return '';
    var abs = Math.abs(v);
    var unit = abs >= 1000000 ? 1000000 : abs >= 1000 ? 1000 : 1;
    if (unit === 1) return '' + v;
    var scaled = v / unit;
    var decimals = scaled % 1 === 0 ? 0 : 1;
    if (step > 0) {
        decimals = Math.max(0, Math.ceil(-Math.log10(step / unit) - 1e-9));
        if (decimals > 2) return Math.round(v).toLocaleString(document.documentElement.lang || undefined);
    }
    return scaled.toFixed(decimals) + (unit === 1000000 ? 'M' : 'k');
}

/* uPlot axis `size` that fits the widest tick label, but never below `min`,
   the width the plot layout was estimated with. */
function docsightAxisSize(min) {
    return function(u, values, axisIdx, cycleNum) {
        var axis = u.axes[axisIdx];
        if (cycleNum > 1) return axis._size;
        var size = axis.ticks.size + axis.gap;
        var longest = (values || []).reduce(function(acc, v) { return String(v).length > acc.length ? String(v) : acc; }, '');
        if (longest) {
            u.ctx.font = axis.font[0];
            size += u.ctx.measureText(longest).width / (window.devicePixelRatio || 1);
        }
        return Math.max(min, Math.ceil(size));
    };
}

function fmtKTicks(vals) {
    var step = vals.length > 1 ? Math.abs(vals[1] - vals[0]) : 0;
    return vals.map(function(v) { return fmtK(v, step); });
}
function todayStr() {
    /* Today's date in the configured time zone (YYYY-MM-DD). */
    if (typeof DOCSIGHT_TIME_ZONE !== 'undefined' && DOCSIGHT_TIME_ZONE) {
        try {
            return new Intl.DateTimeFormat('en-CA', {
                timeZone: DOCSIGHT_TIME_ZONE, year: 'numeric', month: '2-digit', day: '2-digit'
            }).format(new Date());
        } catch (error) { /* fall back to the browser date */ }
    }
    var d = new Date();
    return d.getFullYear() + '-' + pad(d.getMonth()+1) + '-' + pad(d.getDate());
}
function pad(n) { return n < 10 ? '0' + n : '' + n; }
/* Formats a YYYY-MM-DD calendar date in the UI language. The name is kept
   for existing callers, including community modules. */
function formatDateDE(str) {
    if (typeof formatDocsightTime === 'function') return formatDocsightTime(str, 'date');
    var p = String(str || '').split('-');
    return p.length === 3 ? p[2] + '.' + p[1] + '.' + p[0] : String(str || '');
}

function docsightRangeHours(range) {
    if (range === null || range === undefined) return 24;
    if (typeof range === 'number' && isFinite(range)) return range;
    var raw = String(range || '1d').toLowerCase();
    if (raw === 'bqm') return 24;
    if (raw === 'all') return 24 * 90;
    var secondsMatch = raw.match(/^(\d+)s$/);
    if (secondsMatch) return parseInt(secondsMatch[1], 10) / 3600;
    if (/^\d+$/.test(raw)) {
        var numeric = parseInt(raw, 10);
        return numeric;
    }
    var match = raw.match(/^(\d+)(h|d)$/);
    if (!match) return 24;
    var value = parseInt(match[1], 10);
    return match[2] === 'h' ? value : value * 24;
}

function docsightTimestampDate(ts) {
    if (typeof docsightParseTime === 'function') return docsightParseTime(ts);
    if (ts instanceof Date) return ts;
    if (typeof ts === 'number') {
        return new Date(Math.abs(ts) < 100000000000 ? ts * 1000 : ts);
    }
    return new Date(ts);
}

/* Axis labels follow the UI language and the configured time zone; chart
   data is parsed with docsightParseTime() into the same zone. */
function docsightFormatAxisTime(date, style) {
    if (typeof DOCSightBrowserContracts === 'undefined') return null;
    return DOCSightBrowserContracts.formatTimestamp(date, {
        locale: document.documentElement.lang || undefined,
        timeZone: typeof DOCSIGHT_TIME_ZONE !== 'undefined' ? DOCSIGHT_TIME_ZONE : undefined,
        style: style
    });
}

function docsightFormatXAxisLabel(ts, range) {
    var d = docsightTimestampDate(ts);
    if (isNaN(d.getTime())) return '';
    var hours = docsightRangeHours(range);
    var bqm = String(range || '').toLowerCase() === 'bqm';
    var localized = docsightFormatAxisTime(d,
        bqm || hours <= 24 ? 'time' : (hours < 24 * 30 ? 'monthday-time' : 'monthday'));
    if (localized) return localized;
    var hhmm = pad(d.getHours()) + ':' + pad(d.getMinutes());
    if (String(range || '').toLowerCase() === 'bqm') return hhmm;
    var mmdd = pad(d.getMonth() + 1) + '-' + pad(d.getDate());
    if (hours <= 24) return hhmm;
    if (hours < 24 * 30) return mmdd + ' ' + hhmm;
    return mmdd;
}

function docsightFormatXAxisLabels(timestamps, range) {
    return (timestamps || []).map(function(ts) {
        return ts !== null && ts !== undefined ? docsightFormatXAxisLabel(ts, range) : '';
    });
}

function chartXRange(u) {
    var xData = u && u.data && u.data[0] ? u.data[0] : [];
    var edgePadding = u && u._docsightXEdgePadding ? u._docsightXEdgePadding : DEFAULT_X_EDGE_PADDING;
    if (!xData.length) return { min: 0, max: 0 };
    if (xData.length === 1) return { min: xData[0] - edgePadding, max: xData[0] + edgePadding };
    return { min: xData[0] - edgePadding, max: xData[xData.length - 1] + edgePadding };
}

function buildEvenIndexTicks(count, maxTicks) {
    if (count <= 0) return [];
    if (!maxTicks || maxTicks < 2) maxTicks = 2;
    if (count <= maxTicks) {
        var all = [];
        for (var ai = 0; ai < count; ai++) all.push(ai);
        return all;
    }
    var ticks = [];
    var seen = {};
    var gap = (count - 1) / (maxTicks - 1);
    for (var ti = 0; ti < maxTicks; ti++) {
        var idx = Math.round(ti * gap);
        if (idx < 0) idx = 0;
        if (idx >= count) idx = count - 1;
        if (!seen[idx]) {
            ticks.push(idx);
            seen[idx] = true;
        }
    }
    if (!seen[count - 1]) ticks.push(count - 1);
    return ticks;
}

function estimateLongestLabelWidth(labels, minWidth) {
    var longest = '';
    labels.forEach(function(label) {
        var text = label === null || label === undefined ? '' : String(label);
        if (text.length > longest.length) longest = text;
    });
    // Average glyph width of the 12px axis font.
    return Math.max(Math.ceil(longest.length * 7.5), minWidth || 40);
}

function calculateXEdgePadding(labels, xValues, chartWidth, yAxisSize, explicitPadding) {
    if (explicitPadding !== undefined && explicitPadding !== null) return explicitPadding;
    if (!labels || labels.length <= 1) return DEFAULT_X_EDGE_PADDING;
    var labelWidth = estimateLongestLabelWidth(labels, 40);
    var plotWidth = Math.max((chartWidth || 400) - (yAxisSize || DEFAULT_Y_AXIS_SIZE) - 24, 1);
    var span = labels.length - 1;
    if (xValues && xValues.length > 1) {
        var first = Number(xValues[0]);
        var last = Number(xValues[xValues.length - 1]);
        if (isFinite(first) && isFinite(last) && Math.abs(last - first) > 0) {
            span = Math.abs(last - first);
        }
    }
    var labelHalfWidthWithBreathingRoom = (labelWidth / 2) + 10;
    var padding = (labelHalfWidthWithBreathingRoom / plotWidth) * span;
    return Math.max(DEFAULT_X_EDGE_PADDING, Math.ceil(padding * 10) / 10);
}

function calculateMaxXTicks(labels, chartWidth, yAxisSize, hardMax) {
    var labelWidth = estimateLongestLabelWidth(labels, 40) + 18;
    var plotWidth = Math.max((chartWidth || 400) - (yAxisSize || DEFAULT_Y_AXIS_SIZE) - 24, 1);
    var byWidth = Math.floor(plotWidth / labelWidth);
    var cap = hardMax || 6;
    if (cap < 2) cap = 2;
    if (byWidth < 2) byWidth = 2;
    if (byWidth > cap) byWidth = cap;
    return byWidth;
}

/* ── Shared uPlot Plugins ── */
function zoomPlugin() {
    return {
        hooks: {
            init: [function(u) {
                u.over.style.cursor = 'crosshair';
            }],
            ready: [function(u) {
                u.over.addEventListener('dblclick', function() {
                    u._zoomRange = null;
                    var range = chartXRange(u);
                    u.setScale('x', range);
                });
            }],
            setSelect: [function(u) {
                var min = u.posToVal(u.select.left, 'x');
                var max = u.posToVal(u.select.left + u.select.width, 'x');
                if (max - min > 1) {
                    u._zoomRange = { min: min, max: max };
                    u.setScale('x', u._zoomRange);
                }
                u.setSelect({ left: 0, width: 0, top: 0, height: 0 }, false);
            }]
        }
    };
}

function bandPlugin(minSeriesIdx, maxSeriesIdx, color, lineSeriesIdx) {
    return {
        hooks: {
            draw: [function(u) {
                // A band belongs to its line: hiding the line hides the band.
                if (lineSeriesIdx && u.series[lineSeriesIdx] && u.series[lineSeriesIdx].show === false) return;
                var ctx = u.ctx;
                var minData = u.data[minSeriesIdx];
                var maxData = u.data[maxSeriesIdx];
                if (!minData || !maxData) return;
                ctx.save();
                ctx.beginPath();
                ctx.rect(u.bbox.left, u.bbox.top, u.bbox.width, u.bbox.height);
                ctx.clip();
                ctx.fillStyle = color;
                ctx.beginPath();
                var started = false;
                for (var i = 0; i < maxData.length; i++) {
                    if (maxData[i] != null && minData[i] != null) {
                        var x = u.valToPos(u.data[0][i], 'x', true);
                        var y = u.valToPos(maxData[i], u.series[minSeriesIdx].scale, true);
                        if (!started) {
                            ctx.moveTo(x, y);
                            started = true;
                        } else {
                            ctx.lineTo(x, y);
                        }
                    }
                }
                for (var j = minData.length - 1; j >= 0; j--) {
                    if (maxData[j] != null && minData[j] != null) {
                        var x2 = u.valToPos(u.data[0][j], 'x', true);
                        var y2 = u.valToPos(minData[j], u.series[minSeriesIdx].scale, true);
                        ctx.lineTo(x2, y2);
                    }
                }
                ctx.closePath();
                ctx.fill();
                ctx.restore();
            }]
        }
    };
}

/* ── DOCSIS Target Bands ──
   Bands behind power and SNR charts: good, tolerated, marginal and critical,
   in the theme's status colors. The last entry fixes the default y range. */
function _band(min, max, band) { return {min: min, max: max, band: band}; }
var DS_POWER_THRESHOLDS = [
    _band(-4, 13, 'good'),
    _band(-8, -4, 'tolerated'), _band(13, 20, 'tolerated'),
    _band(-15, -8, 'marginal'), _band(20, 25, 'marginal'),
    _band(-60, -15, 'critical'), _band(25, 60, 'critical'),
    {yMin: -18, yMax: 28}
];
var DS_SNR_THRESHOLDS = [
    _band(33, 100, 'good'),
    _band(29, 33, 'tolerated'),
    _band(25, 29, 'marginal'),
    _band(-100, 25, 'critical'),
    {yMin: 20, yMax: 50}
];
var US_POWER_THRESHOLDS = [
    _band(41, 47, 'good'),
    _band(35, 41, 'tolerated'), _band(47, 53, 'tolerated'),
    _band(20, 35, 'marginal'), _band(53, 60, 'marginal'),
    _band(-100, 20, 'critical'), _band(60, 160, 'critical'),
    {yMin: 17, yMax: 63}
];

/* Status token and strength per band; the token is read at draw time, so every theme applies. */
var BAND_STYLE = {
    good: ['--good', 0.12],
    tolerated: ['--tolerated', 0.14],
    marginal: ['--warn', 0.12],
    critical: ['--crit', 0.18]
};

var _themeColorProbe = null;
/* Resolves a CSS color token of the current theme to rgba() with the given alpha. */
function docsightThemeColor(token, alpha) {
    if (!document.body || typeof getComputedStyle !== 'function') return 'rgba(128,128,128,' + alpha + ')';
    if (!_themeColorProbe) {
        _themeColorProbe = document.createElement('span');
        _themeColorProbe.style.display = 'none';
        document.body.appendChild(_themeColorProbe);
    }
    _themeColorProbe.style.color = 'var(' + token + ')';
    var rgb = (getComputedStyle(_themeColorProbe).color.match(/[\d.]+/g) || [128, 128, 128]).slice(0, 3);
    return 'rgba(' + rgb.join(',') + ',' + alpha + ')';
}

/* Bars are drawn slightly translucent; colors that already carry alpha (rgba()) stay as they are. */
function barFill(color) {
    var value = color || '#a855f7';
    return /^#[0-9a-f]{6}$/i.test(value) ? value + 'cc' : value;
}

function bandFill(band) {
    var style = BAND_STYLE[band];
    return style ? docsightThemeColor(style[0], style[1]) : 'transparent';
}

/* ── Uncorrectable errors per interval ──
   Trend rows carry cumulative counters. Each interval gets the sum of the
   increases inside it; after a modem restart the counter starts again at zero,
   so a drop counts as the new value, never as a negative change. Timestamps
   are wall-clock time in the configured zone, so buckets follow its days. */
var ERROR_BUCKET_MINUTES = {'1h': 5, '6h': 15, '1d': 60, '2d': 120, '3d': 180, '7d': 360, '30d': 1440, '90d': 1440};

function docsightErrorBucketMinutes(range) {
    return ERROR_BUCKET_MINUTES[range] || 60;
}

/* Interval size for a span given in minutes, matching the range presets. */
function docsightErrorBucketMinutesForSpan(minutes) {
    var spans = [['1h', 60], ['6h', 360], ['1d', 1440], ['2d', 2880], ['3d', 4320], ['7d', 10080], ['30d', 43200]];
    for (var i = 0; i < spans.length; i++) {
        if (minutes <= spans[i][1]) return ERROR_BUCKET_MINUTES[spans[i][0]];
    }
    return 1440;
}

function docsightErrorsTitle(minutes) {
    if (minutes >= 1440) return T.trend_errors_per_day || 'Uncorrectable errors per day';
    if (minutes === 60) return T.trend_errors_per_hour || 'Uncorrectable errors per hour';
    if (minutes > 60) return (T.trend_errors_per_hours || 'Uncorrectable errors per {hours} hours').replace('{hours}', minutes / 60);
    return (T.trend_errors_per_minutes || 'Uncorrectable errors per {minutes} minutes').replace('{minutes}', minutes);
}

/* New errors between readings of a cumulative counter. A counter that drops
   was reset (modem restart), so its new value counts, never a negative change. */
function _errorIncreases(rows, key, visit) {
    var previous = null;
    (rows || []).forEach(function(row) {
        var value = row[key];
        if (value === null || value === undefined) return;
        var increase = previous === null ? 0 : (value >= previous ? value - previous : value);
        previous = value;
        visit(row, increase);
    });
}

function _wallClockMinutes(timestamp) {
    var m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/.exec(String(timestamp || ''));
    if (!m) return null;
    return Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]) / 60000;
}

function _wallClockLabel(minutes) {
    return new Date(minutes * 60000).toISOString().slice(0, 19);
}

function docsightErrorBuckets(rows, range, field) {
    var size = docsightErrorBucketMinutes(range);
    var key = field || 'ds_uncorrectable_errors';
    var buckets = [];
    _errorIncreases(rows, key, function(row, increase) {
        var minutes = _wallClockMinutes(row.timestamp);
        if (minutes === null) return;
        var start = Math.floor(minutes / size) * size;
        var last = buckets[buckets.length - 1];
        if (!last || last.start !== start) {
            last = {start: start, timestamp: _wallClockLabel(start), errors: 0};
            buckets.push(last);
        }
        last.errors += increase;
    });
    // Intervals without readings stay empty, so the bars keep their place in time.
    var filled = [];
    buckets.forEach(function(bucket) {
        var previousBucket = filled[filled.length - 1];
        for (var start = previousBucket ? previousBucket.start + size : bucket.start; start < bucket.start; start += size) {
            filled.push({start: start, timestamp: _wallClockLabel(start), errors: null});
        }
        filled.push(bucket);
    });
    return filled;
}

/* Errors per interval counted from a period's start, so two periods line up
   slot by slot in the before/after comparison. Slots without readings are null. */
function docsightErrorSlots(rows, startMs, slots, minutes, field) {
    var values = [];
    for (var i = 0; i < slots; i++) values.push(null);
    _errorIncreases(rows, field || 'uncorr_errors', function(row, increase) {
        var slot = Math.floor((Date.parse(row.timestamp) - startMs) / (minutes * 60000));
        if (!(slot >= 0 && slot < slots)) return;
        values[slot] = (values[slot] || 0) + increase;
    });
    return values;
}

/* ── Zone Plugin (uPlot hooks) ── */
function zonesPlugin(zones) {
    if (!zones) return {};
    return {
        hooks: {
            drawAxes: [function(u) {
                var ctx = u.ctx;
                var left = u.bbox.left;
                var top = u.bbox.top;
                var width = u.bbox.width;
                var height = u.bbox.height;
                ctx.save();
                ctx.beginPath();
                ctx.rect(left, top, width, height);
                ctx.clip();
                var drawn = {};
                var dpr = window.devicePixelRatio || 1;
                zones.forEach(function(z) {
                    if (z.yMin !== undefined) return; /* skip metadata entries */
                    if (z.band) {
                        var btop = u.valToPos(z.max, 'y', true);
                        var bbottom = u.valToPos(z.min, 'y', true);
                        ctx.fillStyle = bandFill(z.band);
                        ctx.fillRect(left, btop, width, bbottom - btop);
                        return;
                    }
                    if (z.fill !== false) {
                        var ztop = u.valToPos(z.max, 'y', true);
                        var zbottom = u.valToPos(z.min, 'y', true);
                        ctx.fillStyle = z.color;
                        ctx.fillRect(left, ztop, width, zbottom - ztop);
                    }
                    var lineColor = z.lineColor || z.color.replace(/[\d.]+\)$/, '0.7)');
                    var vals = z.fill === false ? [z.value] : [z.min, z.max];
                    vals.forEach(function(val) {
                        if (val === undefined || drawn[val]) return;
                        drawn[val] = true;
                        var py = u.valToPos(val, 'y', true);
                        ctx.beginPath();
                        ctx.setLineDash([6 * dpr, 4 * dpr]);
                        ctx.strokeStyle = lineColor;
                        ctx.lineWidth = 1 * dpr;
                        ctx.moveTo(left, py);
                        ctx.lineTo(left + width, py);
                        ctx.stroke();
                    });
                });
                ctx.restore();
            }]
        }
    };
}

/* ── Tooltip Plugin ── */
function tooltipPlugin(labels, tooltipLabelCallback) {
    var tooltip;
    function init(u) {
        tooltip = document.createElement('div');
        tooltip.className = 'uplot-tooltip';
        tooltip.style.display = 'none';
        u.over.appendChild(tooltip);
    }
    function buildLine(color, text) {
        var row = document.createElement('div');
        row.style.cssText = 'display:flex;align-items:center;gap:6px;';
        var marker = document.createElement('span');
        marker.style.cssText = 'width:10px;height:3px;display:inline-block;border-radius:1px;background:' + color;
        var label = document.createElement('span');
        label.textContent = text;
        row.appendChild(marker);
        row.appendChild(label);
        return row;
    }
    function setCursor(u) {
        var idx = u.cursor.idx;
        if (idx == null || labels[idx] === null) {
            tooltip.style.display = 'none';
            return;
        }
        tooltip.textContent = '';
        var header = document.createElement('div');
        header.className = 'uplot-tooltip-time';
        header.textContent = labels[idx] || '';
        tooltip.appendChild(header);
        for (var i = 1; i < u.series.length; i++) {
            var s = u.series[i];
            if (!s.show) continue;
            var val = u.data[i][idx];
            if (val == null) continue;
            var color = s._stroke || s.stroke;
            if (typeof color === 'function') color = color(u, i);
            var text;
            if (tooltipLabelCallback) {
                text = tooltipLabelCallback({
                    raw: val,
                    parsed: {y: val},
                    dataset: {label: s.label, yAxisID: s._docsightAxisID},
                    dataIndex: idx
                });
            } else {
                text = s.label + ': ' + (typeof val === 'number' ? (val === Math.floor(val) && Math.abs(val) >= 1000 ? fmtK(val) : val.toFixed(2)) : val);
            }
            tooltip.appendChild(buildLine(color, text));
        }
        tooltip.style.display = 'block';

        var left = u.cursor.left;
        var top = u.cursor.top;
        // Forced reflow to measure dimensions is intentional for tooltip positioning
        var tw = tooltip.offsetWidth;
        var th = tooltip.offsetHeight;
        var plotW = u.over.offsetWidth;
        var plotH = u.over.offsetHeight;
        var x = left + 12;
        var y = top - th - 8;
        if (x + tw > plotW) x = left - tw - 12;
        if (y < 0) y = top + 12;
        if (y + th > plotH) y = plotH - th - 4;
        tooltip.style.left = x + 'px';
        tooltip.style.top = y + 'px';
    }
    return {
        hooks: {
            init: [init],
            setCursor: [setCursor]
        }
    };
}

/* ── Touch: press and hold to read values ──
   A quick swipe keeps scrolling the page. Holding a finger still on the plot
   for a moment shows the tooltip, and moving it then slides along the values
   instead of scrolling. */
var TOUCH_HOLD_MS = 350;
var TOUCH_SLOP_PX = 10;

function docsightTouchHold(target, onPoint) {
    var timer = null;
    var scrubbing = false;
    var startX = 0;
    var startY = 0;
    function stop() {
        clearTimeout(timer);
        timer = null;
        if (scrubbing) target.classList.remove('is-scrubbing');
        scrubbing = false;
    }
    target.addEventListener('touchstart', function(event) {
        if (event.touches.length !== 1) { stop(); return; }
        var touch = event.touches[0];
        startX = touch.clientX;
        startY = touch.clientY;
        clearTimeout(timer);
        timer = setTimeout(function() {
            scrubbing = true;
            target.classList.add('is-scrubbing');
            onPoint(touch);
        }, TOUCH_HOLD_MS);
    }, {passive: true});
    target.addEventListener('touchmove', function(event) {
        var touch = event.touches[0];
        if (scrubbing) {
            event.preventDefault();
            onPoint(touch);
        } else if (Math.abs(touch.clientX - startX) > TOUCH_SLOP_PX || Math.abs(touch.clientY - startY) > TOUCH_SLOP_PX) {
            stop();
        }
    }, {passive: false});
    target.addEventListener('touchend', function(event) {
        // Lifting the finger after reading values is not a tap on the chart.
        if (scrubbing && event.cancelable) event.preventDefault();
        stop();
    }, {passive: false});
    target.addEventListener('touchcancel', stop);
    // Hold-to-read replaces the long-press menu on the plot.
    target.addEventListener('contextmenu', function(event) {
        if (scrubbing || timer) event.preventDefault();
    });
}

function touchScrubPlugin() {
    return {hooks: {init: [function(u) {
        docsightTouchHold(u.over, function(touch) {
            var rect = u.over.getBoundingClientRect();
            u.setCursor({
                left: Math.max(0, Math.min(rect.width, touch.clientX - rect.left)),
                top: Math.max(0, Math.min(rect.height, touch.clientY - rect.top))
            });
        });
    }]}};
}

/* ── Time axis and gaps ──
   Charts that pass opts.times place their points by time. A pause much longer
   than the usual interval (no polls: modem offline, DOCSight stopped) breaks the
   line and is drawn as a hatched "No data" band, so a missing hour never reads
   as a calm, continuous signal. */
var GAP_FACTOR = 3;

function _medianInterval(times) {
    var steps = [];
    for (var i = 1; i < times.length; i++) {
        var step = times[i] - times[i - 1];
        if (step > 0) steps.push(step);
    }
    if (!steps.length) return 0;
    steps.sort(function(a, b) { return a - b; });
    return steps[Math.floor(steps.length / 2)];
}

/* Inserts a null point into every series at each gap. Returns the new columns,
   the gaps, and the map from drawn points back to the caller's indices. */
function docsightTimeSeries(labels, datasets, times, tempData) {
    var interval = _medianInterval(times);
    var out = {labels: [], times: [], data: datasets.map(function() { return []; }), temp: tempData ? [] : null,
        gaps: [], original: [], interval: interval};
    for (var i = 0; i < times.length; i++) {
        var gap = i > 0 && interval > 0 ? times[i] - times[i - 1] : 0;
        if (gap > interval * GAP_FACTOR) {
            out.gaps.push({start: times[i - 1], end: times[i]});
            out.labels.push(null);
            out.times.push(times[i - 1] + Math.min(interval, gap / 2));
            out.data.forEach(function(series) { series.push(null); });
            if (out.temp) out.temp.push(null);
            out.original.push(null);
        }
        out.labels.push(labels[i]);
        out.times.push(times[i]);
        datasets.forEach(function(ds, k) { out.data[k].push(ds.data[i]); });
        if (out.temp) out.temp.push(tempData[i]);
        out.original.push(i);
    }
    return out;
}

/* Gaps in a regular series where intervals without readings are null, such as
   the error buckets: a run of at least GAP_FACTOR empty intervals is a gap. */
function docsightNullRunGaps(times, values) {
    var gaps = [];
    var runStart = -1;
    for (var i = 0; i <= values.length; i++) {
        var empty = i < values.length && values[i] == null;
        if (empty && runStart === -1) runStart = i;
        if (!empty && runStart !== -1) {
            if (i - runStart >= GAP_FACTOR && runStart > 0 && i < values.length) {
                gaps.push({start: times[runStart - 1], end: times[i]});
            }
            runStart = -1;
        }
    }
    return gaps;
}

/* Wall-clock timestamps ("2026-10-06T14:00:00") as seconds for spacing points. */
function docsightTimesFromStamps(stamps) {
    return stamps.map(function(stamp) {
        var ms = Date.parse(String(stamp || '').slice(0, 19) + 'Z');
        return isNaN(ms) ? null : ms / 1000;
    });
}

function docsightGapLabel(seconds) {
    var minutes = Math.round(seconds / 60);
    var days = Math.floor(minutes / 1440), hours = Math.floor(minutes % 1440 / 60), mins = minutes % 60;
    var text = days ? days + ' d' + (hours ? ' ' + hours + ' h' : '')
        : hours ? hours + ' h' + (mins ? ' ' + mins + ' min' : '') : mins + ' min';
    return {title: T.chart_gap_no_data || 'No data', duration: text};
}

/* Labels sit on data points at least a label apart in pixels, so uneven
   spacing in time cannot put two of them on top of each other. */
function buildTimeSplits(xData, labels, range, plotPx, labelPx) {
    var span = range[1] - range[0];
    if (!(span > 0)) return xData.slice(0, 1);
    var toPx = function(x) { return (x - range[0]) / span * plotPx; };
    var splits = [];
    var lastPx = -Infinity;
    var half = labelPx / 2;
    for (var i = 0; i < xData.length; i++) {
        if (labels[i] === null) continue;
        var px = toPx(xData[i]);
        if (px < half - 4 || px > plotPx - half + 4) continue;
        if (px - lastPx < labelPx + 18) continue;
        splits.push(xData[i]);
        lastPx = px;
    }
    return splits;
}

function gapBandsPlugin(gaps) {
    return {hooks: {drawAxes: [function(u) {
        if (!gaps.length) return;
        var ctx = u.ctx;
        var dpr = window.devicePixelRatio || 1;
        var stroke = docsightThemeColor('--text-secondary', 0.35);
        var text = docsightThemeColor('--text-secondary', 1);
        gaps.forEach(function(gap) {
            var x0 = Math.max(u.valToPos(gap.start, 'x', true), u.bbox.left);
            var x1 = Math.min(u.valToPos(gap.end, 'x', true), u.bbox.left + u.bbox.width);
            if (x1 - x0 < 2) return;
            ctx.save();
            ctx.beginPath();
            ctx.rect(x0, u.bbox.top, x1 - x0, u.bbox.height);
            ctx.clip();
            ctx.strokeStyle = stroke;
            ctx.lineWidth = dpr;
            for (var x = x0 - u.bbox.height; x < x1; x += 8 * dpr) {
                ctx.beginPath();
                ctx.moveTo(x, u.bbox.top + u.bbox.height);
                ctx.lineTo(x + u.bbox.height, u.bbox.top);
                ctx.stroke();
            }
            // One line if it fits, else title over duration, else the hatching alone.
            var label = docsightGapLabel(gap.end - gap.start);
            ctx.font = (11 * dpr) + 'px system-ui';
            var lines = [label.title + ' · ' + label.duration];
            var room = x1 - x0 - 12 * dpr;
            if (ctx.measureText(lines[0]).width > room) lines = [label.title, label.duration];
            var width = Math.max.apply(null, lines.map(function(line) { return ctx.measureText(line).width; }));
            if (width <= room) {
                var mid = (x0 + x1) / 2;
                ctx.fillStyle = docsightThemeColor('--card', 0.9);
                ctx.fillRect(mid - width / 2 - 4 * dpr, u.bbox.top + 6 * dpr, width + 8 * dpr, (4 + 14 * lines.length) * dpr);
                ctx.fillStyle = text;
                ctx.textAlign = 'center';
                ctx.textBaseline = 'top';
                lines.forEach(function(line, i) {
                    ctx.fillText(line, mid, u.bbox.top + (8 + 14 * i) * dpr);
                });
            }
            ctx.restore();
        });
    }]}};
}

/* ── Click a point ──
   A click (not a drag) on the plot reports the point under the cursor, and the
   chart can mark one point with a vertical line, e.g. while its snapshot is open. */
function pointClickPlugin(onClick) {
    return {hooks: {
        init: [function(u) {
            var downX = null;
            u.over.classList.add('is-point-clickable');
            u.over.addEventListener('mousedown', function(event) { downX = event.clientX; });
            u.over.addEventListener('click', function(event) {
                var moved = downX !== null && Math.abs(event.clientX - downX) > 4;
                downX = null;
                if (moved || u.cursor.idx == null) return;
                onClick(u.cursor.idx, u);
            });
        }],
        draw: [function(u) {
            var idx = u._docsightMarkedIdx;
            if (idx == null || u.data[0][idx] == null) return;
            var x = u.valToPos(u.data[0][idx], 'x', true);
            var ctx = u.ctx;
            ctx.save();
            ctx.strokeStyle = docsightThemeColor('--accent', 1);
            ctx.lineWidth = 2 * (window.devicePixelRatio || 1);
            ctx.beginPath();
            ctx.moveTo(x, u.bbox.top);
            ctx.lineTo(x, u.bbox.top + u.bbox.height);
            ctx.stroke();
            ctx.restore();
        }]
    }};
}

function docsightMarkChartPoint(canvasId, idx) {
    var chart = charts[canvasId];
    if (!chart) return;
    if (idx != null && chart._docsightOriginal) idx = chart._docsightOriginal.indexOf(idx);
    chart._docsightMarkedIdx = idx === -1 ? null : idx;
    chart.redraw(false, false);
}

/* ── Helper: prepare uPlot container from canvas/div element ── */
function prepareContainer(canvasId) {
    var el = document.getElementById(canvasId);
    if (!el) return null;
    var container;
    if (el.tagName === 'CANVAS') {
        container = document.createElement('div');
        container.id = canvasId;
        container.style.width = '100%';
        el.parentNode.replaceChild(container, el);
    } else {
        container = el;
        container.textContent = '';
        container.style.width = '100%';
    }
    return container;
}

/* ── Render Chart ── */
function renderChart(canvasId, labels, datasets, type, zones, opts) {
    var existing = charts[canvasId];
    // Save zoom state before potential destroy — restore after recreate
    var savedZoom = existing && existing._zoomRange ? existing._zoomRange : null;

    // Fix container height before destroy to prevent scroll jump from DOM reflow
    var containerEl = document.getElementById(canvasId);
    var savedHeight = 0;
    if (existing && containerEl) {
        savedHeight = containerEl.offsetHeight;
        containerEl.style.minHeight = savedHeight + 'px';
    }

    if (existing) { existing.destroy(); delete charts[canvasId]; }
    var container = prepareContainer(canvasId);
    if (!container) return;

    var isDark = document.documentElement.getAttribute('data-theme') !== 'light';
    var gridColor = isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)';
    var textColor = isDark ? '#888' : '#666';
    var isBar = type === 'bar';
    var yAxisSize = opts && opts.yAxisSize ? opts.yAxisSize : DEFAULT_Y_AXIS_SIZE;
    var width = container.offsetWidth || 400;
    var params = {labels: labels, datasets: datasets, type: type, zones: zones, opts: opts};

    /* Time axis: points by time, gaps break the line (see docsightTimeSeries). */
    var timeSeries = opts && opts.times && opts.times.length === labels.length && opts.times.every(function(t) { return t != null; })
        ? docsightTimeSeries(labels, datasets, opts.times, opts.tempData || null) : null;
    if (timeSeries) {
        labels = timeSeries.labels;
        datasets = datasets.map(function(ds, k) { return Object.assign({}, ds, {data: timeSeries.data[k]}); });
        if (opts.tempData) opts = Object.assign({}, opts, {tempData: timeSeries.temp});
    }
    var n = labels.length;

    /* Build columnar data: [xIndices, series1, series2, ...] */
    var xData = timeSeries ? timeSeries.times.slice() : (opts && opts.xData ? opts.xData.slice() : []);
    if (!xData.length) {
        for (var xi = 0; xi < n; xi++) xData.push(xi);
    }
    var uData = [xData];
    var allDatasets = datasets.slice();

    /* Temperature overlay */
    var tempData = opts && opts.tempData && _tempOverlayVisible ? opts.tempData : null;
    var hasTemp = tempData && tempData.some(function(v) { return v !== null; }) && !isBar;

    /* Label spacing needs the plot width: the y axis plus any axis on the right. */
    var axesPx = yAxisSize + (hasTemp ? TEMP_AXIS_SIZE : 0);
    if (opts && opts.axes) opts.axes.forEach(function(axis) { axesPx += axis.size || 0; });
    var xEdgePadding = calculateXEdgePadding(labels, xData, width, axesPx, opts && opts.xEdgePadding);

    allDatasets.forEach(function(ds) { uData.push(ds.data); });
    if (hasTemp) uData.push(tempData);

    /* Series config */
    var uSeries = [{ label: 'X', value: function(u, v) { return labels[v] || ''; } }];

    /* Determine bar path renderer */
    var barPaths = isBar ? uPlot.paths.bars({size: [0.7, 50], gap: 1}) : null;

    allDatasets.forEach(function(ds) {
        // A single reading has no line to draw, so it shows as a dot.
        var showPoints = ds.showPoints;
        if (showPoints === undefined) showPoints = n === 1 && !isBar;
        var s = {
            label: ds.label,
            stroke: ds.color || 'rgba(168,85,247,0.9)',
            width: ds.lineWidth !== undefined ? ds.lineWidth : (isBar ? 0 : 2),
            fill: isBar ? barFill(ds.color) : (ds.fill || undefined),
            points: { show: showPoints, size: ds.pointSize || 6 },
            spanGaps: ds.spanGaps !== undefined ? ds.spanGaps : false,
            show: ds.show !== undefined ? ds.show : true,
        };
        if (ds.hideInLegend) s.class = 'docsight-legend-hidden';
        if (ds.fillTo !== undefined && ds.fillTo !== null) s.fillTo = ds.fillTo;
        if (ds.scale) s.scale = ds.scale;
        if (isBar) {
            s.paths = barPaths;
            s.points = { show: false };
        }
        if (ds.stepped) {
            s.paths = uPlot.paths.stepped({ align: -1 });
            s.width = 2;
        }
        if (ds.dashed) {
            s.dash = [5, 5];
        }
        uSeries.push(s);
    });

    if (hasTemp) {
        var tempSeries = {
            label: T.temperature || 'Temperature',
            stroke: 'rgba(249,115,22,0.7)',
            width: 1.5,
            dash: [5, 3],
            scale: 'temp',
            points: { show: false },
            spanGaps: true
        };
        tempSeries._docsightAxisID = 'y-temp';
        uSeries.push(tempSeries);
    }

    /* Tooltip callback */
    var tooltipLabelCallback = null;
    if (opts && opts.tooltipLabelCallback) {
        tooltipLabelCallback = opts.tooltipLabelCallback;
    } else if (hasTemp) {
        tooltipLabelCallback = function(ctx) {
            var val = ctx.parsed.y;
            if (val == null) return '';
            if (ctx.dataset.yAxisID === 'y-temp') return ctx.dataset.label + ': ' + fmtTemp(val);
            return ctx.dataset.label + ': ' + val;
        };
    }

    /* Scales */
    var yRange = [null, null];
    if (zones) {
        var zoneMeta = zones.find(function(z) { return z.yMin !== undefined; });
        if (zoneMeta) {
            yRange = [zoneMeta.yMin, zoneMeta.yMax];
        }
    }
    if (opts && opts.yMin !== undefined) yRange[0] = opts.yMin;
    if (opts && opts.yMax !== undefined) yRange[1] = opts.yMax;

    var zoomable = opts && opts.zoomable;
    var scales = {
        x: { time: false },
        y: {}
    };
    if (zoomable) {
        /* Zoom-aware: auto off so setScale isn't overridden by data range */
        scales.x.auto = false;
        scales.x.range = function(u, dmin, dmax) {
            if (u._zoomRange) return [u._zoomRange.min, u._zoomRange.max];
            var range = chartXRange(u);
            return [range.min, range.max];
        };
    } else {
        scales.x.range = function() {
            if (xData.length <= 1) return [(xData[0] || 0) - xEdgePadding, (xData[0] || 0) + xEdgePadding];
            return [xData[0] - xEdgePadding, xData[xData.length - 1] + xEdgePadding];
        };
    }
    if (yRange[0] !== null && yRange[1] !== null) {
        scales.y.range = function(u, dmin, dmax) {
            var lo = yRange[0] !== null ? yRange[0] : dmin;
            var hi = yRange[1] !== null ? yRange[1] : dmax;
            if (dmin < lo) lo = dmin;
            if (dmax > hi) hi = dmax;
            return [lo, hi];
        };
    }
    if (hasTemp) {
        scales.temp = {};
    }
    if (opts && opts.scales) {
        Object.keys(opts.scales).forEach(function(key) {
            scales[key] = opts.scales[key];
        });
    }

    /* Axes — pick evenly spaced label positions */
    var xSplits = [];
    var wantTicks = calculateMaxXTicks(labels, width, axesPx, opts && opts.maxXTicks ? opts.maxXTicks : 6);
    if (timeSeries) {
        // Dense time series fill the width with half an interval of padding;
        // labels are placed by pixel distance, not by count.
        if (n > wantTicks && !(opts && opts.xEdgePadding !== undefined)) xEdgePadding = timeSeries.interval * DENSE_X_EDGE_PADDING;
        var timeRange = xData.length > 1 ? [xData[0] - xEdgePadding, xData[xData.length - 1] + xEdgePadding] : [xData[0] - 1, xData[0] + 1];
        xSplits = buildTimeSplits(xData, labels, timeRange, Math.max(width - axesPx - 24, 1), estimateLongestLabelWidth(labels, 40));
    } else if (n <= wantTicks) {
        for (var li = 0; li < n; li++) xSplits.push(xData[li]);
    } else {
        /* Dense series fill the width; the outer labels move inward by half a label instead. */
        var insetIndex = 0;
        if (!(opts && opts.xEdgePadding !== undefined)) {
            xEdgePadding = DENSE_X_EDGE_PADDING;
            var plotPx = Math.max(width - axesPx - 24, 1);
            var halfLabel = estimateLongestLabelWidth(labels, 40) / 2 + 4;
            insetIndex = Math.min(Math.ceil(halfLabel / plotPx * (n - 1)), Math.floor((n - 1) / 3));
        }
        var firstTick = insetIndex, lastTick = n - 1 - insetIndex;
        // Ticks sit on data points, so they are a whole number of points apart. A
        // fractional gap rounded per tick alternates long and short steps, and on
        // short series the short ones put two labels on top of each other. Use one
        // whole step that is at least a label wide.
        var pxPerPoint = Math.max(width - axesPx - 24, 1) / (n - 1);
        var minStep = Math.ceil((estimateLongestLabelWidth(labels, 40) + 18) / pxPerPoint);
        var step = Math.max(1, minStep, Math.ceil((lastTick - firstTick) / Math.max(wantTicks - 1, 1)));
        for (var ti = firstTick; ti <= lastTick; ti += step) xSplits.push(xData[ti]);
        // The last label goes to the end when it fits; otherwise the evenly spaced one stays.
        var lastPlaced = firstTick + Math.floor((lastTick - firstTick) / step) * step;
        if (lastPlaced !== lastTick && lastTick - lastPlaced >= minStep) xSplits.push(xData[lastTick]);
    }

    var xLabelMap = {};
    for (var li2 = 0; li2 < xData.length; li2++) xLabelMap[xData[li2]] = labels[li2] || '';

    var axes = [
        {
            scale: 'x',
            splits: function(u, axisIdx, scaleMin, scaleMax) {
                // A zoomed time axis labels what is in view.
                if (timeSeries && zoomable && u._zoomRange) {
                    return buildTimeSplits(xData, labels, [scaleMin, scaleMax],
                        Math.max(u.bbox.width / (window.devicePixelRatio || 1), 1), estimateLongestLabelWidth(labels, 40));
                }
                return xSplits;
            },
            values: function(u, vals) {
                if (opts && opts.xValueCallback) return vals.map(function(v) { return opts.xValueCallback(v); });
                return vals.map(function(v) { return xLabelMap[v] || ''; });
            },
            stroke: textColor,
            grid: { show: false },
            ticks: { show: false },
            font: '12px system-ui',
            gap: 4
        },
        {
            scale: 'y',
            stroke: textColor,
            grid: { stroke: gridColor, width: 1 },
            ticks: { stroke: gridColor, width: 1 },
            font: '12px system-ui',
            size: docsightAxisSize(yAxisSize),
            gap: 4
        }
    ];

    /* Custom y-axis tick labels (e.g., QAM modulation) */
    if (opts && opts.yTickCallback) {
        var origTickCb = opts.yTickCallback;
        axes[1].values = function(u, vals) {
            return vals.map(function(v) { return origTickCb(v) || ''; });
        };
    }

    /* Auto-format Y-axis with k/M when values are large (error counts) */
    if (!zones && !(opts && opts.yTickCallback)) {
        var maxVal = 0;
        allDatasets.forEach(function(ds) {
            ds.data.forEach(function(v) { if (v != null && Math.abs(v) > maxVal) maxVal = Math.abs(v); });
        });
        if (maxVal >= 1000) {
            axes[1].values = function(u, vals) { return fmtKTicks(vals); };
        }
    }

    /* Custom tick generation (e.g., fixed QAM steps) */
    if (opts && opts.yAfterBuildTicks) {
        var fakeTicks = [];
        opts.yAfterBuildTicks({ ticks: fakeTicks });
        if (fakeTicks.length > 0) {
            axes[1].splits = function() {
                return fakeTicks.map(function(t) { return t.value; });
            };
        }
    }

    /* Temperature axis (right side) */
    if (hasTemp) {
        axes.push({
            scale: 'temp',
            side: 1,
            stroke: 'rgba(249,115,22,0.6)',
            grid: { show: false },
            ticks: { stroke: 'rgba(249,115,22,0.3)', width: 1 },
            font: '12px system-ui',
            size: TEMP_AXIS_SIZE,
            gap: 4,
            values: function(u, vals) { return vals.map(function(v) { return fmtTempAxis(v); }); }
        });
    }
    if (opts && opts.axes) {
        opts.axes.forEach(function(axis) { axes.push(axis); });
    }

    /* Sync crosshairs for trend charts */
    var isTrendChart = ['chart-ds-power', 'chart-ds-snr', 'chart-us-power', 'chart-errors'].indexOf(canvasId) >= 0;
    var cursor = {
        show: true,
        x: true,
        y: false,
        points: { show: false }
    };
    if (isTrendChart) {
        cursor.sync = { key: 'docsight-trends', setSeries: false };
    }
    if (zoomable) {
        cursor.drag = { x: true, y: false, uni: 10 };
    }
    /* Plugins */
    /* Tooltip titles default to the axis labels; opts.tooltipTitles holds one per input point. */
    var titles = labels;
    if (opts && opts.tooltipTitles) {
        titles = timeSeries ? timeSeries.original.map(function(i) { return i == null ? null : opts.tooltipTitles[i]; }) : opts.tooltipTitles;
    }
    var plugins = [tooltipPlugin(titles, tooltipLabelCallback), touchScrubPlugin()];
    if (opts && opts.onPointClick) {
        var onPointClick = opts.onPointClick;
        plugins.push(pointClickPlugin(timeSeries ? function(idx, u) {
            // Report the caller's index; a gap has no point to open.
            var original = timeSeries.original[idx];
            if (original != null) onPointClick(original, u);
        } : onPointClick));
    }
    if (timeSeries) plugins.push(gapBandsPlugin(timeSeries.gaps.concat(opts.gaps || [])));
    if (zones) plugins.push(zonesPlugin(zones));
    if (opts && opts.plugins) { opts.plugins.forEach(function(p) { plugins.push(p); }); }

    /* Build options */
    var heightRatio = opts && opts.heightRatio ? opts.heightRatio : 0.55;
    var minHeight = opts && opts.minHeight ? opts.minHeight : 180;
    var maxHeight = opts && opts.maxHeight ? opts.maxHeight : 350;
    var height = Math.round(width * heightRatio);
    if (height < minHeight) height = minHeight;
    if (height > maxHeight) height = maxHeight;

    var uOpts = {
        width: width,
        height: height,
        scales: scales,
        axes: axes,
        series: uSeries,
        cursor: cursor,
        legend: { show: !(opts && opts.legend === false) && allDatasets.length + (hasTemp ? 1 : 0) > 1, live: false },
        plugins: plugins
    };

    var chart = new uPlot(uOpts, uData, container);
    charts[canvasId] = chart;
    chart._docsightXEdgePadding = xEdgePadding;
    chart._docsightParams = params;
    chart._docsightOriginal = timeSeries ? timeSeries.original : null;

    /* Restore zoom state from previous chart instance (survives destroy/recreate),
       unless the new data no longer reaches it, e.g. after moving the window. */
    if (savedZoom && zoomable && xData.length && savedZoom.max > xData[0] && savedZoom.min < xData[xData.length - 1]) {
        chart._zoomRange = savedZoom;
        chart.setScale('x', savedZoom);
    }

    /* Release fixed container height after chart is rendered */
    if (savedHeight > 0) {
        requestAnimationFrame(function() {
            container.style.minHeight = '';
        });
    }

    /* Responsive resize (debounced to avoid rapid setSize calls) */
    var resizeTimer;
    var resizeObserver = new ResizeObserver(function(entries) {
        var entry = entries[0];
        var w = Math.round(entry.contentRect.width);
        if (w > 0 && Math.abs(w - chart.width) > 5) {
            clearTimeout(resizeTimer);
            resizeTimer = setTimeout(function() {
                var h = Math.round(w * heightRatio);
                if (h < minHeight) h = minHeight;
                if (h > maxHeight) h = maxHeight;
                chart.setSize({width: w, height: h});
            }, 100);
        }
    });
    resizeObserver.observe(container);
    chart._docsightResizeObs = resizeObserver;

    /* Patch destroy to cleanup observer */
    var origDestroy = chart.destroy.bind(chart);
    chart.destroy = function() {
        if (chart._docsightResizeObs) { chart._docsightResizeObs.disconnect(); chart._docsightResizeObs = null; }
        origDestroy();
    };
}

/* ── Chart Zoom Modal ── */
var zoomChart = null;

function openChartZoom(canvasId) {
    var src = charts[canvasId];
    if (!src || !src._docsightParams) return;
    var params = src._docsightParams;
    var srcEl = document.getElementById(canvasId);
    var card = srcEl ? srcEl.closest('.chart-card') : null;
    var label = card ? card.querySelector('.chart-label') : null;
    document.getElementById('chart-zoom-title').textContent = label ? label.textContent : '';
    var overlay = document.getElementById('chart-zoom-overlay');
    window.DOCSightModal.open(overlay);

    setTimeout(function() {
        if (zoomChart) { zoomChart.destroy(); zoomChart = null; }
        var zoomContainer = document.getElementById('chart-zoom-canvas');
        if (!zoomContainer) return;
        zoomContainer.textContent = '';
        var isDark = document.documentElement.getAttribute('data-theme') !== 'light';
        var gridColor = isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)';
        var textColor = isDark ? '#888' : '#666';
        var isBar = params.type === 'bar';
        var zoomTime = params.opts && params.opts.times && params.opts.times.length === params.labels.length
            ? docsightTimeSeries(params.labels, params.datasets, params.opts.times, params.opts.tempData || null) : null;
        if (zoomTime) {
            params = Object.assign({}, params, {
                labels: zoomTime.labels,
                datasets: params.datasets.map(function(ds, k) { return Object.assign({}, ds, {data: zoomTime.data[k]}); }),
                opts: params.opts.tempData ? Object.assign({}, params.opts, {tempData: zoomTime.temp}) : params.opts
            });
        }
        var n = params.labels.length;
        var zoomYAxisSize = params.opts && params.opts.zoomYAxisSize ? params.opts.zoomYAxisSize : DEFAULT_ZOOM_Y_AXIS_SIZE;
        var w = zoomContainer.offsetWidth || 800;
        var h = zoomContainer.offsetHeight || 500;
        if (h < 300) h = 300;

        /* Build data */
        var xData = zoomTime ? zoomTime.times.slice() : [];
        if (!zoomTime) for (var xi = 0; xi < n; xi++) xData.push(xi);
        var zoomXEdgePadding = calculateXEdgePadding(params.labels, xData, w, zoomYAxisSize, params.opts && params.opts.zoomXEdgePadding);
        var uData = [xData];
        params.datasets.forEach(function(ds) { uData.push(ds.data); });

        var zoomTempData = params.opts && params.opts.tempData && _tempOverlayVisible ? params.opts.tempData : null;
        var zoomHasTemp = zoomTempData && zoomTempData.some(function(v) { return v !== null; }) && !isBar;
        if (zoomHasTemp) uData.push(zoomTempData);

        /* Series */
        var barPaths = isBar ? uPlot.paths.bars({size: [0.7, 50], gap: 1}) : null;
        var uSeries = [{ label: 'X', value: function(u, v) { return params.labels[v] || ''; } }];
        params.datasets.forEach(function(ds) {
            var zoomShowPoints = ds.showPoints;
            if (zoomShowPoints === undefined) zoomShowPoints = n === 1;
            var s = {
                label: ds.label,
                stroke: ds.color || 'rgba(168,85,247,0.9)',
                width: ds.lineWidth !== undefined ? ds.lineWidth : (isBar ? 0 : 2),
                fill: isBar ? barFill(ds.color) : (ds.fill || undefined),
                points: { show: zoomShowPoints, size: isBar ? 0 : (ds.pointSize || (n > 30 ? 4 : 8)) },
                spanGaps: ds.spanGaps !== undefined ? ds.spanGaps : false
            };
            if (ds.hideInLegend) s.class = 'docsight-legend-hidden';
            if (ds.fillTo !== undefined && ds.fillTo !== null) s.fillTo = ds.fillTo;
            if (isBar) { s.paths = barPaths; s.points = { show: false }; }
            if (ds.stepped) { s.paths = uPlot.paths.stepped({ align: -1 }); s.width = 2; }
            if (ds.dashed) { s.dash = [5, 5]; }
            uSeries.push(s);
        });

        if (zoomHasTemp) {
            var ts = {
                label: T.temperature || 'Temperature',
                stroke: 'rgba(249,115,22,0.7)',
                width: 1.5,
                dash: [5, 3],
                scale: 'temp',
                points: { show: false, size: 4 },
                spanGaps: true
            };
            ts._docsightAxisID = 'y-temp';
            uSeries.push(ts);
        }

        /* Tooltip callback */
        var zoomTooltipCb = null;
        if (params.opts && params.opts.tooltipLabelCallback) {
            zoomTooltipCb = params.opts.tooltipLabelCallback;
        } else if (zoomHasTemp) {
            zoomTooltipCb = function(ctx) {
                var val = ctx.parsed.y;
                if (val == null) return '';
                if (ctx.dataset.yAxisID === 'y-temp') return ctx.dataset.label + ': ' + fmtTemp(val);
                return ctx.dataset.label + ': ' + val;
            };
        }

        /* Scales */
        var yRange = [null, null];
        if (params.zones) {
            var zoneMeta = params.zones.find(function(z) { return z.yMin !== undefined; });
            if (zoneMeta) { yRange = [zoneMeta.yMin, zoneMeta.yMax]; }
        }
        if (params.opts && params.opts.yMin !== undefined) yRange[0] = params.opts.yMin;
        if (params.opts && params.opts.yMax !== undefined) yRange[1] = params.opts.yMax;

        var scales = {
            x: { time: false, range: function() { return [xData[0] - zoomXEdgePadding, xData[xData.length - 1] + zoomXEdgePadding]; } },
            y: {}
        };
        if (yRange[0] !== null && yRange[1] !== null) {
            scales.y.range = function(u, dmin, dmax) {
                var lo = yRange[0] !== null ? yRange[0] : dmin;
                var hi = yRange[1] !== null ? yRange[1] : dmax;
                if (dmin < lo) lo = dmin;
                if (dmax > hi) hi = dmax;
                return [lo, hi];
            };
        }
        if (zoomHasTemp) { scales.temp = {}; }

        /* Axes */
        var zLabelWidth = estimateLongestLabelWidth(params.labels, 60);

        var zoomMaxTicks = calculateMaxXTicks(params.labels, w, zoomYAxisSize, 10);
        var zoomXSplits = zoomTime
            ? buildTimeSplits(xData, params.labels, [xData[0] - zoomXEdgePadding, xData[xData.length - 1] + zoomXEdgePadding], Math.max(w - zoomYAxisSize - 24, 1), zLabelWidth)
            : buildEvenIndexTicks(n, zoomMaxTicks);
        var axes = [
            {
                scale: 'x',
                space: zLabelWidth,
                splits: function() { return zoomXSplits; },
                values: function(u, vals) {
                    if (!zoomTime) return vals.map(function(v) { return params.labels[v] || ''; });
                    return vals.map(function(v) { var i = xData.indexOf(v); return i === -1 ? '' : (params.labels[i] || ''); });
                },
                stroke: textColor,
                grid: { stroke: gridColor, width: 1 },
                ticks: { stroke: gridColor, width: 1 },
                font: '12px system-ui',
                gap: 4
            },
            {
                scale: 'y',
                stroke: textColor,
                grid: { stroke: gridColor, width: 1 },
                ticks: { stroke: gridColor, width: 1 },
                font: '12px system-ui',
                size: docsightAxisSize(zoomYAxisSize),
                gap: 4
            }
        ];
        if (params.opts && params.opts.yTickCallback) {
            var cb = params.opts.yTickCallback;
            axes[1].values = function(u, vals) { return vals.map(function(v) { return cb(v) || ''; }); };
        }
        if (params.opts && params.opts.yAfterBuildTicks) {
            var ft = [];
            params.opts.yAfterBuildTicks({ ticks: ft });
            if (ft.length > 0) {
                axes[1].splits = function() { return ft.map(function(t) { return t.value; }); };
            }
        }
        if (zoomHasTemp) {
            axes.push({
                scale: 'temp', side: 1,
                stroke: 'rgba(249,115,22,0.6)',
                grid: { show: false },
                ticks: { stroke: 'rgba(249,115,22,0.3)', width: 1 },
                font: '12px system-ui',
                size: 45,
                gap: 4,
                values: function(u, vals) { return vals.map(function(v) { return fmtTempAxis(v); }); }
            });
        }

        /* Plugins */
        var plugins = [tooltipPlugin(params.labels, zoomTooltipCb), touchScrubPlugin()];
        if (zoomTime) plugins.push(gapBandsPlugin(zoomTime.gaps));
        if (params.zones) plugins.push(zonesPlugin(params.zones));

        var uOpts = {
            width: w,
            height: h,
            scales: scales,
            axes: axes,
            series: uSeries,
            cursor: { show: true, x: true, y: false, points: { show: false } },
            legend: { show: params.datasets.length > 1 || zoomHasTemp, live: false },
            plugins: plugins
        };

        zoomChart = new uPlot(uOpts, uData, zoomContainer);
    }, 50);
}

function closeChartZoom() {
    window.DOCSightModal.close('chart-zoom-overlay');
    if (zoomChart) { zoomChart.destroy(); zoomChart = null; }
}
