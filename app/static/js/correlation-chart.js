/* ── Correlation chart drawing ──
   Lays out and draws the correlation canvas: the signal band with its axes, one
   lane per source below it, and the shared time axis. prepare() and scales() are
   pure geometry; draw() and the overlay helpers only touch the canvas context
   they are given, so all of it runs in Node tests with a stub context. */
(function (root, factory) {
    'use strict';
    var api = factory(root && root.DOCSightCorrelationData
        ? root.DOCSightCorrelationData
        : require('./correlation-data.js'));
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) Object.defineProperty(root, 'DOCSightCorrelationChart', {
        configurable: false,
        writable: false,
        value: api
    });
})(typeof window !== 'undefined' ? window : null, function (CorrelationData) {
    'use strict';

    /* Lane heights below the main signal band, in display order. */
    var LANES = [
        { key: 'state', height: 10 },
        { key: 'errors', height: 30 },
        { key: 'speed', height: 48 },
        { key: 'segment', height: 34 },
        { key: 'events', height: 14 },
        { key: 'reachability', height: 18 }
    ];

    /* Chart colors from the theme; read(prop, fallback) resolves one custom property. */
    function colors(read) {
        var warn = read('--warn', '#ff9800');
        var crit = read('--crit', '#f44336');
        var good = read('--good', '#4caf50');
        var text = read('--muted', '#888');
        return {
            snr: read('--corr-color-snr', '#3b82f6'),
            txPower: read('--corr-color-tx-power', '#f59e0b'),
            dsPower: read('--corr-color-ds-power', '#a855f7'),
            download: read('--corr-color-download', '#0ea5e9'),
            upload: read('--corr-color-upload', '#06b6d4'),
            event: warn,
            errors: read('--corr-color-errors', 'rgba(239,68,68,0.6)'),
            temperature: read('--corr-color-temperature', '#f97316'),
            segmentDs: read('--corr-color-seg-ds', '#0ea5e9'),
            segmentUs: read('--corr-color-seg-us', '#6366f1'),
            reachability: { ok: good, degraded: warn, down: crit, unknown: text },
            health: { good: good, tolerated: read('--tolerated', '#84cc16'), marginal: warn, critical: crit },
            warn: warn,
            crit: crit,
            accent: read('--accent', '#2196f3'),
            laneTint: read('--tint-emphasis', 'rgba(127,127,127,0.08)'),
            text: text,
            grid: read('--input-border', '#333')
        };
    }

    /* Splits the sources and lays out the lanes that have something to show.
       input: {data, weather, segment, targets, visible}. */
    function prepare(input) {
        var data = input.data || [];
        var visible = input.visible;
        var targets = input.targets || [];
        var modem = data.filter(function (d) { return d.source === 'modem'; });
        var speedtest = data.filter(function (d) { return d.source === 'speedtest'; });
        var events = data.filter(function (d) { return d.source === 'event'; });
        var segment = input.segment || [];
        var errorDeltas = CorrelationData.errorDeltas(modem);
        var hasErrorData = errorDeltas.some(function (d) { return d.delta !== null; });
        var hasReachability = targets.some(function (entry) {
            var target = CorrelationData.target(entry);
            return (entry.samples || []).some(function (sample) { return !!CorrelationData.sampleInterval(sample, target); });
        });
        // Every source gets its own lane and scale; hidden sources take no space.
        var laneVisible = {
            state: modem.length > 0 && visible.signalState,
            errors: hasErrorData && visible.errors,
            speed: speedtest.length > 0 && (visible.download || visible.upload),
            segment: segment.length > 0 && (visible.segmentDs || visible.segmentUs),
            events: events.length > 0 && visible.events,
            reachability: hasReachability && visible.reachability
        };
        return {
            data: data, modem: modem, speedtest: speedtest, events: events,
            weather: input.weather || [], segment: segment, targets: targets,
            errorDeltas: errorDeltas, hasErrorData: hasErrorData, hasReachability: hasReachability,
            laneVisible: laneVisible,
            empty: modem.length === 0 && speedtest.length === 0 && !hasReachability,
            layout: CorrelationData.laneLayout({
                top: 26, mainHeight: 200, labelHeight: 16, gap: 8, axisGap: 4, axisHeight: 22,
                lanes: LANES.filter(function (lane) { return laneVisible[lane.key]; })
            })
        };
    }

    function finite(v) { return typeof v === 'number' && isFinite(v); }
    function bounds(values, fallbackMin, fallbackMax) {
        return values.length
            ? [Math.floor(Math.min.apply(null, values) - 2), Math.ceil(Math.max.apply(null, values) + 2)]
            : [fallbackMin, fallbackMax];
    }

    /* Time range, value scales and plot box. Returns null without a usable time range.
       options: {width, visible, zoom, selectedRange, fahrenheit, measure, parseTime, colors, dpr}. */
    function scales(prep, options) {
        var parseTime = options.parseTime;
        var visible = options.visible;
        var modem = prep.modem, layout = prep.layout;
        var W = options.width, H = layout.height;

        var allTs = prep.data.map(function (d) { return parseTime(d.timestamp).getTime(); }).filter(isFinite);
        prep.targets.forEach(function (entry) {
            var target = CorrelationData.target(entry);
            (entry.samples || []).forEach(function (sample) {
                var interval = CorrelationData.sampleInterval(sample, target);
                if (interval) allTs.push(interval.startMs, interval.endMs);
            });
        });
        var range = options.selectedRange;
        var hasRange = range && finite(range.startMs) && finite(range.endMs) && range.endMs > range.startMs;
        if (!hasRange && allTs.length === 0) return null;
        var tMinFull = hasRange ? range.startMs : Math.min.apply(null, allTs);
        var tMaxFull = hasRange ? range.endMs : Math.max.apply(null, allTs);
        if (tMinFull === tMaxFull) tMaxFull = tMinFull + 3600000;
        var tMin = options.zoom ? options.zoom.tMin : tMinFull;
        var tMax = options.zoom ? options.zoom.tMax : tMaxFull;

        // Main band: power (dBmV, left), SNR (dB, right), temperature (°C/°F, outer right).
        var mainTop = layout.main.y, mainH = layout.main.height;
        function bandY(v, min, max) { return mainTop + mainH - (v - min) / (max - min) * mainH; }

        var dsPowerValues = modem.map(function (d) { return d.ds_power_avg; }).filter(finite);
        var txValues = modem.map(function (d) { return d.us_power_avg; }).filter(function (v) { return finite(v) && v > 0; });
        var showDsPower = visible.dsPower && dsPowerValues.length > 0;
        var showTxPower = visible.txPower && txValues.length > 0;
        // DS and US power share one dBmV axis so their levels stay directly comparable.
        var powerValues = (showDsPower ? dsPowerValues : []).concat(showTxPower ? txValues : []);
        if (!powerValues.length) powerValues = dsPowerValues.concat(txValues);
        var power = bounds(powerValues, -10, 55);
        function yPower(v) { return bandY(v, power[0], power[1]); }

        var snrValues = modem.map(function (d) { return d.ds_snr_min || 0; }).filter(function (v) { return v > 0; });
        var showSnr = visible.snr && snrValues.length > 0;
        var snr = bounds(snrValues, 20, 45);
        function ySnr(v) { return bandY(v, snr[0], snr[1]); }

        var fahrenheit = !!options.fahrenheit;
        function toDisplayTemp(c) { return fahrenheit ? c * 9 / 5 + 32 : c; }
        var tempValues = prep.weather.map(function (d) { return toDisplayTemp(d.temperature); })
            .filter(function (v) { return v != null && !isNaN(v); });
        var showTemp = visible.temperature && tempValues.length > 1;
        var temp = bounds(tempValues, fahrenheit ? 14 : -10, fahrenheit ? 104 : 40);
        function yTemp(v) { return bandY(toDisplayTemp(v), temp[0], temp[1]); }

        // Axis widths: dBmV on the left; dB and temperature each get their own right axis.
        var axisWidth = function (values) {
            return Math.ceil(Math.max.apply(null, values.map(function (v) { return options.measure(String(v)); }))) + 10;
        };
        var snrAxisWidth = showSnr ? Math.max(30, axisWidth(snr)) : 0;
        var tempAxisWidth = showTemp ? Math.max(30, axisWidth(temp)) : 0;
        var laneAxisWidth = prep.laneVisible.speed ? axisWidth([CorrelationData.niceCeil(1000) + ' Mbps']) : 0;
        var pad = {
            top: mainTop,
            left: Math.max(44, axisWidth(power) + 4),
            right: Math.max(16, snrAxisWidth + tempAxisWidth, laneAxisWidth) + 8,
            bottom: H - mainTop - mainH
        };
        var plotW = W - pad.left - pad.right;
        function xScale(ts) { return pad.left + (ts - tMin) / (tMax - tMin) * plotW; }

        // Lanes.
        var lanes = layout.lanes;
        var speedtest = prep.speedtest.slice().sort(function (a, b) {
            return parseTime(a.timestamp).getTime() - parseTime(b.timestamp).getTime();
        });
        var speedValues = speedtest.map(function (d) { return CorrelationData.measurement(d.download_mbps); })
            .concat(speedtest.map(function (d) { return CorrelationData.measurement(d.upload_mbps); }))
            .filter(function (v) { return v !== null; });
        var dlMin = 0;
        var dlMax = CorrelationData.niceCeil(speedValues.length ? Math.max.apply(null, speedValues) : 500);
        var speedLane = lanes.speed || { y: mainTop, height: mainH };
        function yDl(v) { return speedLane.y + speedLane.height - (v - dlMin) / (dlMax - dlMin) * speedLane.height; }
        var segmentLane = lanes.segment || { y: mainTop, height: mainH };
        function ySegment(v) { return segmentLane.y + segmentLane.height - (v / 100) * segmentLane.height; }
        var errorMax = prep.errorDeltas.reduce(function (max, d) { return d.delta !== null && d.delta > max ? d.delta : max; }, 0);

        var reachabilityBuckets = prep.hasReachability
            ? CorrelationData.bucketReachability(prep.targets, tMin, tMax, Math.min(300, Math.max(1, Math.floor(plotW / 3))))
            : [];
        var reachabilityLane = lanes.reachability && reachabilityBuckets.length > 0
            ? { y: lanes.reachability.y, height: lanes.reachability.height }
            : null;

        return {
            pad: pad, plotW: plotW, plotH: mainH, W: W, H: H, layout: layout, bandY: bandY,
            tMin: tMin, tMax: tMax, tMinFull: tMinFull, tMaxFull: tMaxFull,
            snrMin: snr[0], snrMax: snr[1], txMin: power[0], txMax: power[1],
            dsPowerMin: power[0], dsPowerMax: power[1], errorMax: errorMax, errorDeltas: prep.errorDeltas,
            errorScaleMax: CorrelationData.niceCeil(errorMax),
            tempMin: temp[0], tempMax: temp[1], tempUnit: fahrenheit ? '°F' : '°C',
            dlMin: dlMin, dlMax: dlMax,
            show: { dsPower: showDsPower, txPower: showTxPower, snr: showSnr, temperature: showTemp },
            snrAxisWidth: snrAxisWidth,
            hasPowerData: dsPowerValues.length > 0, hasTxData: txValues.length > 0, hasErrorData: prep.hasErrorData,
            modem: modem, speedtest: speedtest, events: prep.events, data: prep.data,
            speedMarks: CorrelationData.buildSpeedMarks(speedtest, xScale, yDl, tMin, tMax,
                { download: visible.download, upload: visible.upload }, parseTime),
            weather: prep.weather, segment: prep.segment,
            reachabilityBuckets: reachabilityBuckets, reachabilityLane: reachabilityLane,
            xScale: xScale, ySnr: ySnr, yTx: yPower, yDsPower: yPower, yDl: yDl, yTemp: yTemp, ySegment: ySegment,
            colors: options.colors,
            dpr: options.dpr || 1
        };
    }

    function drawSpeedMarks(ctx, marks, baselineY, colors, visibleMetrics) {
        ['download', 'upload'].forEach(function (kind) {
            if (!visibleMetrics[kind]) return;
            var has = kind === 'download' ? 'hasDownload' : 'hasUpload';
            marks.forEach(function (mark) {
                if (!mark.visible || !mark[has]) return;
                ctx.beginPath();
                ctx.moveTo(mark[kind + 'X'], baselineY);
                ctx.lineTo(mark[kind + 'X'], mark[kind + 'Y']);
                ctx.strokeStyle = colors[kind];
                ctx.lineWidth = mark.stemWidth;
                ctx.stroke();
                ctx.beginPath();
                ctx.arc(mark[kind + 'X'], mark[kind + 'Y'], mark.headRadius, 0, Math.PI * 2);
                ctx.fillStyle = colors[kind];
                ctx.fill();
            });
        });
    }

    /* Draws the chart. options: {visible, events (filtered), labels (lane captions), axisLabel(t), parseTime}. */
    function draw(ctx, st, options) {
        var visible = options.visible;
        var parseTime = options.parseTime;
        var c = st.colors;
        var pad = st.pad, plotW = st.plotW, lanes = st.layout.lanes;
        var mainTop = st.layout.main.y;
        var right = pad.left + plotW;

        function text(value, x, y, align, font, color) {
            ctx.fillStyle = color || c.text;
            ctx.font = font || '12px system-ui, sans-serif';
            ctx.textAlign = align;
            ctx.fillText(value, x, y);
        }
        function axisCaption(value, x, align) { text(value, x, mainTop - 10, align, '11px system-ui, sans-serif'); }
        function niceStep(min, max) { return CorrelationData.niceCeil((max - min) / 5); }
        function ticks(min, max, visit) {
            var step = niceStep(min, max);
            for (var v = Math.ceil(min / step) * step; v <= max; v += step) visit(v);
        }

        // Power grid and left axis (falls back to the SNR scale when no power is shown).
        var powerShown = st.show.dsPower || st.show.txPower;
        var gridMin = powerShown ? st.txMin : st.snrMin;
        var gridMax = powerShown ? st.txMax : st.snrMax;
        ticks(gridMin, gridMax, function (v) {
            var y = st.bandY(v, gridMin, gridMax);
            ctx.strokeStyle = c.grid;
            ctx.lineWidth = 0.5;
            ctx.setLineDash([2, 4]);
            ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(right, y); ctx.stroke();
            ctx.setLineDash([]);
            if (powerShown) text(String(v), pad.left - 6, y + 4, 'right');
        });
        if (powerShown) axisCaption('dBmV', pad.left - 6, 'right');

        // SNR axis on the right, temperature to the right of it.
        if (st.show.snr) {
            var snrX = right + 6;
            ticks(st.snrMin, st.snrMax, function (v) { text(String(v), snrX, st.ySnr(v) + 4, 'left', null, c.snr); });
            axisCaption('dB', snrX, 'left');
        }
        if (st.show.temperature) {
            var tempX = right + 6 + st.snrAxisWidth;
            ticks(st.tempMin, st.tempMax, function (v) {
                text(String(v), tempX, st.bandY(v, st.tempMin, st.tempMax) + 4, 'left', null, c.temperature);
            });
            axisCaption(st.tempUnit, tempX, 'left');
        }

        // Connect observations directly; smoothed curves imply unmeasured trends.
        function drawSeries(points, color, width, dash) {
            ctx.beginPath();
            var started = false;
            points.forEach(function (point) {
                if (point === null) return;
                if (started) ctx.lineTo(point[0], point[1]);
                else { ctx.moveTo(point[0], point[1]); started = true; }
            });
            ctx.strokeStyle = color;
            ctx.lineWidth = width;
            ctx.setLineDash(dash);
            ctx.stroke();
            ctx.setLineDash([]);
        }
        function x(entry) { return st.xScale(parseTime(entry.timestamp).getTime()); }
        var modem = st.modem;
        if (st.show.snr && modem.length > 1) {
            drawSeries(modem.map(function (d) { return [x(d), st.ySnr(d.ds_snr_min || st.snrMin)]; }), c.snr, 2, []);
        }
        if (st.show.txPower && modem.length > 1) {
            drawSeries(modem.map(function (d) { return d.us_power_avg ? [x(d), st.yTx(d.us_power_avg)] : null; }), c.txPower, 2, [6, 3]);
        }
        if (st.show.dsPower && modem.length > 1) {
            drawSeries(modem.map(function (d) { return d.ds_power_avg != null ? [x(d), st.yDsPower(d.ds_power_avg)] : null; }), c.dsPower, 1.5, [2, 3]);
        }
        if (st.show.temperature) {
            drawSeries(st.weather.map(function (d) { return d.temperature == null ? null : [x(d), st.yTemp(d.temperature)]; }), c.temperature, 1.5, [5, 3]);
        }

        // Lane labels and backgrounds share one style; each lane draws its own values.
        st.layout.order.forEach(function (key) {
            var lane = lanes[key];
            text(options.labels[key], pad.left, lane.labelY + 11, 'left', '11px system-ui, sans-serif');
            ctx.fillStyle = c.laneTint;
            ctx.fillRect(pad.left, lane.y, plotW, lane.height);
        });
        function laneTick(value, y) { text(value, right + 6, y, 'left', '11px system-ui, sans-serif'); }

        if (lanes.state) {
            for (var si = 0; si < modem.length; si++) {
                var sx1 = x(modem[si]);
                var sx2 = si < modem.length - 1 ? x(modem[si + 1]) : Math.min(right, sx1 + 3);
                if (sx2 < pad.left || sx1 > right) continue;
                ctx.fillStyle = c.health[modem[si].health] || c.laneTint;
                ctx.fillRect(Math.max(pad.left, sx1), lanes.state.y, Math.max(1, Math.min(right, sx2) - Math.max(pad.left, sx1)), lanes.state.height);
            }
        }

        if (lanes.errors) {
            var errorLane = lanes.errors;
            for (var ei = 0; ei < st.errorDeltas.length; ei++) {
                var delta = st.errorDeltas[ei].delta;
                if (!delta) continue;
                var ex = x(modem[ei]);
                if (ex < pad.left || ex > right) continue;
                var eh = Math.max(2, delta / st.errorScaleMax * errorLane.height);
                ctx.fillStyle = c.errors;
                ctx.fillRect(ex - 1.5, errorLane.y + errorLane.height - eh, 3, eh);
            }
            laneTick(String(st.errorScaleMax), errorLane.y + 9);
            laneTick('0', errorLane.y + errorLane.height);
        }

        // Speedtests are point-in-time measurements: stems and heads, never a line.
        if (lanes.speed) {
            drawSpeedMarks(ctx, st.speedMarks, st.yDl(0), c, visible);
            laneTick(st.dlMax + ' Mbps', lanes.speed.y + 9);
            laneTick('0', lanes.speed.y + lanes.speed.height);
        }

        if (lanes.segment) {
            ['Ds', 'Us'].forEach(function (dir) {
                if (!visible['segment' + dir]) return;
                var key = dir.toLowerCase() + '_total';
                drawSeries(st.segment.map(function (d) { return d[key] == null ? null : [x(d), st.ySegment(d[key])]; }), c['segment' + dir], 1.5, []);
            });
            laneTick('100 %', lanes.segment.y + 9);
            laneTick('0', lanes.segment.y + lanes.segment.height);
        }

        // Events: shape carries the severity (circle info, triangle warning, diamond critical).
        if (lanes.events) {
            var mid = lanes.events.y + lanes.events.height / 2;
            options.events.forEach(function (event) {
                var vx = x(event);
                if (vx < pad.left || vx > right) return;
                var sev = CorrelationData.normalizeSeverity(event);
                ctx.strokeStyle = sev === 'critical' ? c.crit : sev === 'warning' ? c.warn : c.text;
                ctx.fillStyle = ctx.strokeStyle;
                ctx.lineWidth = 1.5;
                ctx.beginPath();
                if (sev === 'critical') {
                    ctx.moveTo(vx, mid - 6); ctx.lineTo(vx + 6, mid); ctx.lineTo(vx, mid + 6); ctx.lineTo(vx - 6, mid); ctx.closePath();
                    ctx.fill();
                } else if (sev === 'warning') {
                    ctx.moveTo(vx, mid - 6); ctx.lineTo(vx + 6, mid + 5); ctx.lineTo(vx - 6, mid + 5); ctx.closePath();
                    ctx.stroke();
                } else {
                    ctx.arc(vx, mid, 4, 0, Math.PI * 2);
                    ctx.stroke();
                }
            });
        }

        var reach = st.reachabilityLane;
        if (reach) {
            ctx.save();
            st.reachabilityBuckets.forEach(function (bucket) {
                var x1 = Math.max(pad.left, st.xScale(bucket.startMs));
                var x2 = Math.min(right, st.xScale(bucket.endMs));
                if (x2 <= x1) return;
                ctx.globalAlpha = bucket.state === 'unknown' ? 0.35 : 0.82;
                ctx.fillStyle = c.reachability[bucket.state];
                ctx.fillRect(x1, reach.y, Math.max(1, x2 - x1), reach.height);
                ctx.globalAlpha = 0.7;
                ctx.strokeStyle = c.grid;
                ctx.lineWidth = 0.5;
                ctx.strokeRect(x1, reach.y, Math.max(1, x2 - x1), reach.height);
                if (x2 - x1 >= 18) {
                    ctx.globalAlpha = 0.95;
                    var mark = bucket.state === 'ok' ? '✓' : bucket.state === 'degraded' ? '!' : bucket.state === 'down' ? '×' : '?';
                    text(mark, (x1 + x2) / 2, reach.y + 13, 'center', 'bold 12px system-ui, sans-serif', bucket.state === 'unknown' ? c.text : '#fff');
                }
            });
            ctx.restore();
        }

        // Shared time axis below the last lane.
        var labelCount = Math.min(8, Math.floor(plotW / 80));
        for (var li = 0; li <= labelCount; li++) {
            var t = st.tMin + (st.tMax - st.tMin) * li / labelCount;
            text(options.axisLabel(t), st.xScale(t), st.layout.axisY + 14, 'center');
        }
    }

    /* A highlighted point on the overlay: filled, with a white ring. */
    function drawDot(ctx, x, y, radius, color) {
        ctx.beginPath();
        ctx.arc(x, y, radius, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.fill();
        ctx.strokeStyle = '#fff';
        ctx.lineWidth = 2;
        ctx.stroke();
    }

    /* Index of the item closest to t (ms), or -1; skip(i) leaves an item out. */
    function nearestIndex(items, t, parseTime, skip) {
        var best = -1, bestDist = Infinity;
        for (var i = 0; i < items.length; i++) {
            if (skip && skip(i)) continue;
            var dist = Math.abs(parseTime(items[i].timestamp).getTime() - t);
            if (dist < bestDist) { bestDist = dist; best = i; }
        }
        return best;
    }

    return {
        LANES: LANES,
        colors: colors,
        prepare: prepare,
        scales: scales,
        draw: draw,
        drawSpeedMarks: drawSpeedMarks,
        drawDot: drawDot,
        nearestIndex: nearestIndex
    };
});
