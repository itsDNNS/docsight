/* ── Correlation data rules ──
   Pure functions behind the correlation view: range parsing, event severity,
   Connection Monitor reachability buckets, sparse speedtest marks and CSV rows.
   No DOM or canvas access, so they run unchanged in the browser and in Node tests. */
(function (root, factory) {
    'use strict';
    var api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) Object.defineProperty(root, 'DOCSightCorrelationData', {
        configurable: false,
        writable: false,
        value: api
    });
})(typeof window !== 'undefined' ? window : null, function () {
    'use strict';

    var SEVERITIES = ['info', 'warning', 'critical'];
    var MAX_REACHABILITY_BUCKETS = 300;

    /* '6h' / '7d' / legacy plain day counts → hours; anything else falls back to one day. */
    function rangeHours(range) {
        var raw = String(range || '1d');
        if (/^\d+$/.test(raw)) return parseInt(raw, 10);
        var match = raw.match(/^(\d+)(h|d)$/);
        if (!match) return 24;
        var value = parseInt(match[1], 10);
        return match[2] === 'h' ? value : value * 24;
    }

    function normalizeSeverity(event) {
        var severity = String((event && event.severity) || 'info').toLowerCase();
        return SEVERITIES.indexOf(severity) !== -1 ? severity : 'info';
    }

    /* A throughput measurement is a finite, non-negative number; anything else is missing. */
    function measurement(value) {
        return typeof value === 'number' && isFinite(value) && value >= 0 ? value : null;
    }

    function target(entry) {
        return entry && entry.target ? entry.target : (entry || {});
    }

    /* The time a Connection Monitor sample covers, in epoch milliseconds. */
    function sampleInterval(sample, sampleTarget) {
        if (!sample || typeof sample.timestamp !== 'number' || !isFinite(sample.timestamp)) return null;
        var coverageSeconds = typeof sample.bucket_seconds === 'number' && isFinite(sample.bucket_seconds) && sample.bucket_seconds > 0
            ? sample.bucket_seconds
            : Number(sampleTarget && sampleTarget.poll_interval_ms) / 1000;
        if (!isFinite(coverageSeconds) || coverageSeconds <= 0) return null;
        var startMs = sample.timestamp * 1000;
        return { startMs: startMs, endMs: startMs + coverageSeconds * 1000 };
    }

    /**
     * Re-bucket loaded Connection Monitor samples into time-proportional display buckets.
     * CM timestamps are epoch seconds; buckets are in milliseconds. A bucket without any
     * observed sample stays 'unknown' instead of being treated as reachable.
     */
    function bucketReachability(targetData, tMinMs, tMaxMs, bucketCount) {
        var requestedCount = Math.floor(Number(bucketCount));
        var count = Math.min(MAX_REACHABILITY_BUCKETS, Math.max(1, isFinite(requestedCount) ? requestedCount : 1));
        if (!isFinite(tMinMs) || !isFinite(tMaxMs) || tMaxMs <= tMinMs) return [];
        var widthMs = (tMaxMs - tMinMs) / count;
        var buckets = [];
        for (var bi = 0; bi < count; bi++) {
            var bucketStart = tMinMs + bi * widthMs;
            var bucketEnd = bi === count - 1 ? tMaxMs : tMinMs + (bi + 1) * widthMs;
            var sampleCount = 0;
            var weightedLoss = 0;
            var allDown = true;
            var targetKeys = {};
            var targetLabels = [];

            (targetData || []).forEach(function(entry, targetIndex) {
                var entryTarget = target(entry);
                var key = entryTarget.id != null ? 'id:' + entryTarget.id : 'index:' + targetIndex;
                var label = entryTarget.label || entryTarget.host || String(entryTarget.id != null ? entryTarget.id : targetIndex + 1);
                var targetObserved = false;
                (entry.samples || []).forEach(function(sample) {
                    var interval = sampleInterval(sample, entryTarget);
                    if (!interval || interval.startMs >= bucketEnd || interval.endMs <= bucketStart) return;
                    var loss = Number(sample.packet_loss_pct);
                    if (!isFinite(loss) || loss < 0 || loss > 100) return;
                    var weight = Number(sample.sample_count);
                    if (!isFinite(weight) || weight <= 0) weight = 1;
                    sampleCount += weight;
                    weightedLoss += loss * weight;
                    if (loss !== 100) allDown = false;
                    targetObserved = true;
                });
                if (targetObserved && !targetKeys[key]) {
                    targetKeys[key] = true;
                    targetLabels.push(label);
                }
            });

            var lossPct = sampleCount > 0 ? weightedLoss / sampleCount : null;
            var state = 'unknown';
            if (sampleCount > 0) {
                if (allDown && lossPct === 100) state = 'down';
                else if (lossPct === 0) state = 'ok';
                else state = 'degraded';
            }
            buckets.push({
                startMs: bucketStart,
                endMs: bucketEnd,
                state: state,
                lossPct: lossPct,
                sampleCount: sampleCount,
                targetsObserved: targetLabels.length,
                targetScope: targetLabels.join(' | ')
            });
        }
        return buckets;
    }

    /**
     * Speedtests are discrete measurements: one stem per test, never a connecting line.
     * Close neighbours get thinner stems; download/upload separate only when there is room.
     * parseTime maps a timestamp to a Date in the configured time zone.
     */
    function buildSpeedMarks(speedtests, xScale, yScale, tMin, tMax, visibleMetrics, parseTime) {
        var timesMs = speedtests.map(function(sample) { return parseTime(sample.timestamp).getTime(); });
        var visiblePoints = [];
        for (var i = 0; i < speedtests.length; i++) {
            if (isFinite(timesMs[i]) && timesMs[i] >= tMin && timesMs[i] <= tMax) {
                visiblePoints.push({ index: i, x: xScale(timesMs[i]) });
            }
        }

        var nearestVisibleDistances = [];
        for (var vi = 0; vi < visiblePoints.length; vi++) {
            var previousDistance = vi > 0 ? Math.abs(visiblePoints[vi].x - visiblePoints[vi - 1].x) : Infinity;
            var nextDistance = vi < visiblePoints.length - 1 ? Math.abs(visiblePoints[vi + 1].x - visiblePoints[vi].x) : Infinity;
            nearestVisibleDistances[visiblePoints[vi].index] = Math.min(previousDistance, nextDistance);
        }

        var singleVisibleSample = visiblePoints.length === 1;
        return speedtests.map(function(sample, index) {
            var timestampMs = timesMs[index];
            var timestampX = xScale(timestampMs);
            var visible = isFinite(timestampMs) && timestampMs >= tMin && timestampMs <= tMax;
            var nearestVisibleDistance = visible ? nearestVisibleDistances[index] : Infinity;

            var download = measurement(sample.download_mbps);
            var upload = measurement(sample.upload_mbps);
            var canSeparatePair = visibleMetrics.download && visibleMetrics.upload && download !== null && upload !== null && nearestVisibleDistance >= 8;
            var offset = canSeparatePair ? Math.min(2, nearestVisibleDistance / 4) : 0;
            return {
                timestamp: sample.timestamp,
                timestampMs: timestampMs,
                timestampX: timestampX,
                visible: visible,
                nearestVisibleDistance: nearestVisibleDistance,
                offset: offset,
                stemWidth: nearestVisibleDistance < 8 ? 1 : 1.5,
                headRadius: singleVisibleSample ? 4.5 : 3.5,
                hasDownload: download !== null,
                hasUpload: upload !== null,
                downloadX: timestampX - offset,
                uploadX: timestampX + offset,
                downloadY: download !== null ? yScale(download) : null,
                uploadY: upload !== null ? yScale(upload) : null
            };
        });
    }

    /* CSV cell with spreadsheet formula injection neutralized. */
    function encodeCSVCell(value) {
        if (value == null || value === '') return '';
        if (typeof value !== 'string') return value;

        var firstMeaningful = value.search(/\S/);
        var hasLeadingControlPrefix = /^[\s]*[\t\r]/.test(value);
        if (hasLeadingControlPrefix
                || (firstMeaningful !== -1 && '=+-@'.indexOf(value.charAt(firstMeaningful)) !== -1)) {
            value = "'" + value;
        }
        if (/[",\r\n]/.test(value)) return '"' + value.replace(/"/g, '""') + '"';
        return value;
    }

    var CSV_BASE_HEADERS = ['timestamp', 'source', 'health', 'ds_snr_min', 'ds_power_avg', 'us_power_avg', 'ds_uncorrectable_errors', 'download_mbps', 'upload_mbps', 'ping_ms', 'severity', 'message'];
    var CSV_REACHABILITY_HEADERS = ['state', 'packet_loss_pct', 'sample_count', 'bucket_start', 'bucket_end', 'target_scope'];

    /* CSV lines (header first) for timeline entries plus the displayed reachability buckets. */
    function csvRows(entries, reachabilityBuckets) {
        var headers = CSV_BASE_HEADERS.concat(CSV_REACHABILITY_HEADERS);
        var rows = [headers.map(encodeCSVCell).join(',')];
        (entries || []).forEach(function(entry) {
            rows.push(headers.map(function(header) {
                return CSV_REACHABILITY_HEADERS.indexOf(header) !== -1 ? '' : encodeCSVCell(entry[header]);
            }).join(','));
        });
        (reachabilityBuckets || []).forEach(function(bucket) {
            var row = {
                timestamp: new Date(bucket.startMs).toISOString(),
                source: 'connection_monitor',
                state: bucket.state,
                packet_loss_pct: bucket.lossPct == null ? '' : Number(bucket.lossPct.toFixed(4)),
                sample_count: bucket.sampleCount,
                bucket_start: new Date(bucket.startMs).toISOString(),
                bucket_end: new Date(bucket.endMs).toISOString(),
                target_scope: bucket.targetScope || ''
            };
            rows.push(headers.map(function(header) { return encodeCSVCell(row[header]); }).join(','));
        });
        return rows;
    }

    /**
     * Uncorrectable errors per interval. The modem reports cumulative counters, so each
     * snapshot's delta is the growth since the previous one; a smaller reading means the
     * counter restarted (reboot), and then the new reading itself is the growth.
     */
    function errorDeltas(modem) {
        var previous = null;
        return (modem || []).map(function(entry) {
            var value = entry.ds_uncorrectable_errors;
            if (typeof value !== 'number' || !isFinite(value) || value < 0) {
                return { timestamp: entry.timestamp, delta: null };
            }
            var delta = previous === null ? 0 : (value >= previous ? value - previous : value);
            previous = value;
            return { timestamp: entry.timestamp, delta: delta };
        });
    }

    /* Smallest 1/2/5 × 10^n that is at least value (axis maxima). */
    function niceCeil(value) {
        if (!(value > 0) || !isFinite(value)) return 1;
        var magnitude = Math.pow(10, Math.floor(Math.log10(value)));
        var steps = [1, 2, 5, 10];
        for (var i = 0; i < steps.length; i++) {
            if (steps[i] * magnitude >= value) return steps[i] * magnitude;
        }
        return 10 * magnitude;
    }

    /**
     * Vertical layout of the correlation chart: one main band for the signal values and
     * one lane per further source, each with a label row, then the shared time axis.
     * lanes: [{ key, height }] in display order. Returns pixel positions.
     */
    function laneLayout(options) {
        var top = options.top;
        var labelHeight = options.labelHeight;
        var gap = options.gap;
        var main = { y: top, height: options.mainHeight };
        var y = top + options.mainHeight + gap;
        var lanes = {};
        var order = [];
        (options.lanes || []).forEach(function(lane) {
            lanes[lane.key] = { labelY: y, y: y + labelHeight, height: lane.height };
            order.push(lane.key);
            y += labelHeight + lane.height + gap;
        });
        var bottom = order.length ? lanes[order[order.length - 1]].y + lanes[order[order.length - 1]].height : main.y + main.height;
        return {
            main: main,
            lanes: lanes,
            order: order,
            bottom: bottom,
            axisY: bottom + options.axisGap,
            height: bottom + options.axisGap + options.axisHeight
        };
    }

    /**
     * Wall-clock "YYYY-MM-DDTHH:MM" of an instant in the given time zone, as used by
     * datetime-local inputs. roundUp moves a partial minute to the next one, so a range
     * built from (start, roundDown) and (end, roundUp) always covers the instants.
     */
    function localInputValue(ms, timeZone, roundUp) {
        var minuteMs = 60000;
        var rounded = roundUp ? Math.ceil(ms / minuteMs) * minuteMs : Math.floor(ms / minuteMs) * minuteMs;
        var parts = {};
        new Intl.DateTimeFormat('en-CA', {
            timeZone: timeZone || undefined,
            year: 'numeric', month: '2-digit', day: '2-digit',
            hour: '2-digit', minute: '2-digit', hourCycle: 'h23'
        }).formatToParts(new Date(rounded)).forEach(function(part) { parts[part.type] = part.value; });
        return parts.year + '-' + parts.month + '-' + parts.day + 'T' + parts.hour + ':' + parts.minute;
    }

    return {
        SEVERITIES: SEVERITIES.slice(),
        rangeHours: rangeHours,
        normalizeSeverity: normalizeSeverity,
        measurement: measurement,
        target: target,
        sampleInterval: sampleInterval,
        bucketReachability: bucketReachability,
        buildSpeedMarks: buildSpeedMarks,
        encodeCSVCell: encodeCSVCell,
        csvRows: csvRows,
        errorDeltas: errorDeltas,
        niceCeil: niceCeil,
        laneLayout: laneLayout,
        localInputValue: localInputValue
    };
});
