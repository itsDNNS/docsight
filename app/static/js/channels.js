/* ── Channel Timeline + Compare ── */
/* Extracted from IIFE – depends on: T, charts, renderChart, getPillValue,
   docsightFormatXAxisLabels, DS_POWER_THRESHOLDS, DS_SNR_THRESHOLDS,
   US_POWER_THRESHOLDS */

/* ── Channel State URL Persistence ── */
/* Hash format: #channels?mode=timeline&dir=ds&channel=42&range=1d
   Compare:     #channels?mode=compare&dir=us&range=30d&channels=1,2,3
   Preset:      #channels?mode=compare&dir=ds&range=7d&preset=all */

function _channelRangeHours(range) {
    var raw = String(range || '1d');
    if (/^\d+$/.test(raw)) return parseInt(raw, 10) * 24;
    var match = raw.match(/^(\d+)(h|d)$/);
    if (!match) return 24;
    var value = parseInt(match[1], 10);
    return match[2] === 'h' ? value : value * 24;
}

function _channelRangeDays(range) {
    return _channelRangeHours(range) / 24;
}

function _normalizeChannelRangeValue(value) {
    var raw = String(value || '1d');
    if (/^\d+$/.test(raw)) raw = raw + 'd';
    var allowed = ['1h', '6h', '1d', '2d', '3d', '7d', '30d', '90d'];
    return allowed.indexOf(raw) !== -1 ? raw : '1d';
}

function parseChannelHash() {
    var hash = location.hash.replace('#', '');
    var qIdx = hash.indexOf('?');
    if (qIdx === -1) return {};
    var params = {};
    hash.substring(qIdx + 1).split('&').forEach(function(pair) {
        var kv = pair.split('=');
        if (kv.length === 2) params[decodeURIComponent(kv[0])] = decodeURIComponent(kv[1]);
    });
    return params;
}

function writeChannelHash() {
    if (typeof currentView === 'undefined' || currentView !== 'channels') return;
    var mode = getPillValue('channel-mode-tabs') || 'timeline';
    var params = ['mode=' + mode];
    if (mode === 'timeline') {
        var sel = document.getElementById('channel-select');
        var val = sel ? sel.value : '';
        if (val) {
            var parts = val.split('-');
            params.push('dir=' + parts[0]);
            params.push('channel=' + parts[1]);
        }
        params.push('range=' + encodeURIComponent(getPillValue('channel-time-tabs') || '1d'));
    } else {
        params.push('dir=' + getCompareDirection());
        params.push('range=' + encodeURIComponent(getPillValue('compare-time-tabs') || '1d'));
        if (_comparePreset === 'all') {
            params.push('preset=all');
        } else if (_compareChannels.length > 0) {
            var ids = _compareChannels.map(function(c) { return c.id; });
            ids.sort(function(a, b) { return a - b; });
            ids = ids.filter(function(v, i, a) { return i === 0 || a[i - 1] !== v; });
            params.push('channels=' + ids.join(','));
        }
    }
    history.replaceState(null, '', '#channels?' + params.join('&'));
}

function setPillByValue(containerId, value) {
    var container = document.getElementById(containerId);
    if (!container) return;
    container.querySelectorAll('.trend-tab').forEach(function(t) {
        t.classList.toggle('active', t.dataset.value === value);
    });
}

function initChannelView() {
    var params = parseChannelHash();
    loadChannelList(function() {
        if (!params.mode) {
            // No hash params → reset to defaults (timeline, no selection, 1d)
            setPillByValue('channel-mode-tabs', 'timeline');
            setPillByValue('channel-time-tabs', '1d');
            var sel = document.getElementById('channel-select');
            if (sel) sel.value = '';
            _compareChannels = [];
            _comparePreset = null;
            _compareState.ds = { channels: [], preset: null };
            _compareState.us = { channels: [], preset: null };
            _lastCompareDir = 'ds';
            setPillByValue('compare-dir-tabs', 'ds');
            switchChannelMode();
            writeChannelHash();
            return;
        }
        setPillByValue('channel-mode-tabs', params.mode);
        switchChannelMode();

        if (params.mode === 'timeline') {
            setPillByValue('channel-time-tabs', _normalizeChannelRangeValue(params.range || params.days || '1d'));
            var sel = document.getElementById('channel-select');
            if (params.dir && params.channel) {
                sel.value = params.dir + '-' + params.channel;
                if (sel.value === params.dir + '-' + params.channel) {
                    loadChannelTimeline();
                    return;
                }
            }
            // Missing or invalid channel → clear selection, show prompt
            sel.value = '';
            loadChannelTimeline();
            writeChannelHash();
        } else if (params.mode === 'compare') {
            setPillByValue('compare-dir-tabs', params.dir || 'ds');
            _lastCompareDir = params.dir || 'ds';
            setPillByValue('compare-time-tabs', _normalizeChannelRangeValue(params.range || params.days || '1d'));
            _compareChannels = [];
            _comparePreset = null;
            _compareState.ds = { channels: [], preset: null };
            _compareState.us = { channels: [], preset: null };
            updateCompareActionLabels();
            if (params.preset === 'all') {
                addAllCompareChannels();
            } else if (params.channels) {
                var channelIds = params.channels.split(',').map(function(s) { return parseInt(s); });
                var dir = params.dir || 'ds';
                fetch('/api/channels')
                    .then(function(r) { return r.json(); })
                    .then(function(data) {
                        var available = dir === 'ds' ? (data.ds_channels || []) : (data.us_channels || []);
                        _compareChannels = [];
                        channelIds.forEach(function(id) {
                            for (var i = 0; i < available.length; i++) {
                                if (available[i].channel_id === id) {
                                    _compareChannels.push(buildCompareChannelEntry(available[i], _compareChannels.length, dir));
                                    break;
                                }
                            }
                        });
                        renderCompareChips();
                        populateCompareChannelList(data);
                        if (_compareChannels.length > 0) loadCompareCharts();
                        else {
                            var emptyEl = document.getElementById('compare-empty');
                            emptyEl.textContent = T.no_channels_selected || 'Select channels to compare';
                            emptyEl.style.display = '';
                            writeChannelHash();
                        }
                    })
                    .catch(function() { writeChannelHash(); });
            } else {
                loadCompareChannelList();
                var emptyEl = document.getElementById('compare-empty');
                emptyEl.textContent = T.no_channels_selected || 'Select channels to compare';
                emptyEl.style.display = '';
                writeChannelHash();
            }
        } else {
            writeChannelHash();
        }
    });
}
window.initChannelView = initChannelView;

/* ── Channel Mode Switch (Timeline / Compare) ── */
function switchChannelMode() {
    var mode = getPillValue('channel-mode-tabs') || 'timeline';
    var timelinePanel = document.getElementById('channel-panel-timeline');
    var comparePanel = document.getElementById('channel-panel-compare');
    var timelineControls = document.getElementById('channel-timeline-controls');
    var compareControls = document.getElementById('channel-compare-controls');
    var infoBar = document.getElementById('channel-info-bar');
    if (mode === 'compare') {
        timelinePanel.style.display = 'none';
        comparePanel.style.display = '';
        if (timelineControls) timelineControls.style.display = 'none';
        if (compareControls) compareControls.style.display = 'contents';
        if (infoBar) infoBar.style.display = 'none';
        loadCompareChannelList();
        if (_compareChannels.length === 0) {
            var emptyEl = document.getElementById('compare-empty');
            emptyEl.textContent = T.no_channels_selected || 'Select channels to compare';
            emptyEl.style.display = '';
        }
    } else {
        timelinePanel.style.display = '';
        comparePanel.style.display = 'none';
        if (timelineControls) timelineControls.style.display = 'contents';
        if (compareControls) compareControls.style.display = 'none';
        var sel = document.getElementById('channel-select');
        if (!sel || !sel.value) {
            document.getElementById('channel-empty').style.display = '';
            document.getElementById('channel-no-data').style.display = 'none';
        } else {
            // Restore info bar for already-selected channel
            var cparts = sel.value.split('-');
            _updateChannelInfoBar(cparts[0], cparts[1]);
        }
    }
    _updateChannelSelectionControls();
    writeChannelHash();
}
window.switchChannelMode = switchChannelMode;

/* ── Channel Timeline ── */
var _channelsLoaded = false;

function loadChannelList(callback) {
    if (_channelsLoaded) { if (callback) callback(); return; }
    var sel = document.getElementById('channel-select');
    fetch('/api/channels')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            sel.innerHTML = '<option value="">' + (T.select_channel || 'Select Channel') + '</option>';
            var ds = data.ds_channels || [];
            var us = data.us_channels || [];
            if (ds.length) {
                var grp = document.createElement('optgroup');
                grp.label = T.downstream_channels || 'Downstream Channels';
                ds.forEach(function(ch) {
                    var opt = document.createElement('option');
                    opt.value = 'ds-' + ch.channel_id;
                    opt.dataset.docsis = ch.docsis_version || '3.0';
                    opt.textContent = 'DS ' + ch.channel_id + ' (' + (ch.frequency || '') + ')';
                    grp.appendChild(opt);
                });
                sel.appendChild(grp);
            }
            if (us.length) {
                var grp2 = document.createElement('optgroup');
                grp2.label = T.upstream_channels || 'Upstream Channels';
                us.forEach(function(ch) {
                    var opt = document.createElement('option');
                    opt.value = 'us-' + ch.channel_id;
                    opt.dataset.docsis = ch.docsis_version || '3.0';
                    opt.textContent = 'US ' + ch.channel_id + ' (' + (ch.frequency || '') + ')';
                    grp2.appendChild(opt);
                });
                sel.appendChild(grp2);
            }
            _cachedChannelData = data;
            _channelsLoaded = true;
            if (callback) callback();
        })
        .catch(function() { if (callback) callback(); });
}

function _makeInfoItem(text, bold) {
    var el = document.createElement('span');
    el.className = 'ch-info-item';
    if (bold) {
        var b = document.createElement('strong');
        b.textContent = text;
        el.appendChild(b);
    } else {
        el.textContent = text;
    }
    return el;
}
function _makeInfoItemWithLabel(label, value, unit) {
    var el = document.createElement('span');
    el.className = 'ch-info-item';
    el.textContent = label + ' ';
    var b = document.createElement('strong');
    b.textContent = value;
    el.appendChild(b);
    if (unit) el.appendChild(document.createTextNode(' ' + unit));
    return el;
}
function _makeInfoSep() {
    var el = document.createElement('span');
    el.className = 'ch-info-sep';
    return el;
}

function _hasChannelDocsisErrorSeries(data) {
    return !!(data && data.some(function(d) {
        return d && (d.correctable_errors != null || d.uncorrectable_errors != null);
    }));
}

function _setChartCardVisible(cardId, chartId, visible) {
    var card = document.getElementById(cardId);
    if (card) card.style.display = visible ? '' : 'none';
    if (!visible && charts[chartId]) {
        charts[chartId].destroy();
        delete charts[chartId];
    }
}


function _channelWeatherHasData(tempData) {
    return !!(tempData && tempData.some(function(v) { return v !== null; }));
}

function _formatChannelWeatherTime(ms) {
    return new Date(ms).toISOString().replace('T', ' ').replace(/\.\d{3}Z$/, 'Z');
}

function _getChannelWeatherRange(timestamps) {
    var times = (timestamps || []).map(function(ts) {
        var ms = new Date(ts).getTime();
        return isFinite(ms) ? ms : null;
    }).filter(function(ms) { return ms !== null; }).sort(function(a, b) { return a - b; });
    if (!times.length) return null;
    var margin = 90 * 60 * 1000;
    return {
        start: _formatChannelWeatherTime(times[0] - margin),
        end: _formatChannelWeatherTime(times[times.length - 1] + margin)
    };
}

function _fetchChannelWeatherForTimestamps(timestamps) {
    var wr = _getChannelWeatherRange(timestamps);
    if (!wr) return Promise.resolve([]);
    var url = '/api/weather/range?start=' + encodeURIComponent(wr.start) + '&end=' + encodeURIComponent(wr.end);
    return fetch(url).then(function(r) { return r.json(); }).catch(function() { return []; });
}

function _alignWeatherToChannelTimestamps(timestamps, weatherData, days) {
    if (!weatherData || !weatherData.length) return null;
    var weather = weatherData.map(function(row) {
        var ms = row && row.timestamp ? new Date(row.timestamp).getTime() : NaN;
        var temp = row ? row.temperature : null;
        if (!isFinite(ms) || temp == null || !isFinite(Number(temp))) return null;
        return { ts: ms, temp: Number(temp), day: row.timestamp.substring(0, 10) };
    }).filter(function(row) { return row !== null; });
    if (!weather.length) return null;

    if (_channelRangeDays(days) >= 30) {
        var dailyTemps = {};
        weather.forEach(function(row) {
            if (!dailyTemps[row.day]) dailyTemps[row.day] = [];
            dailyTemps[row.day].push(row.temp);
        });
        var dailyAvg = {};
        Object.keys(dailyTemps).forEach(function(day) {
            var vals = dailyTemps[day];
            var sum = 0;
            vals.forEach(function(v) { sum += v; });
            dailyAvg[day] = Math.round(sum / vals.length * 10) / 10;
        });
        return (timestamps || []).map(function(ts) {
            var day = ts ? String(ts).substring(0, 10) : '';
            return dailyAvg[day] !== undefined ? dailyAvg[day] : null;
        });
    }

    return (timestamps || []).map(function(ts) {
        if (!ts) return null;
        var target = new Date(ts).getTime();
        if (!isFinite(target)) return null;
        var best = null;
        var bestDist = Infinity;
        weather.forEach(function(row) {
            var dist = Math.abs(row.ts - target);
            if (dist < bestDist) {
                bestDist = dist;
                best = row.temp;
            }
        });
        return bestDist <= 90 * 60 * 1000 ? best : null;
    });
}

function _updateTempToggleButton(btnId, tempData) {
    var btn = document.getElementById(btnId);
    if (!btn) return;
    var hasWeather = _channelWeatherHasData(tempData);
    btn.style.display = hasWeather ? '' : 'none';
    btn.classList.toggle('active', _tempOverlayVisible && hasWeather);
    btn.setAttribute('aria-pressed', (_tempOverlayVisible && hasWeather) ? 'true' : 'false');
    btn.title = _tempOverlayVisible ? (T.temp_overlay_hide || 'Hide temperature overlay') : (T.temp_overlay_show || 'Show temperature overlay');
}

function _updateChannelTempToggle() {
    _updateTempToggleButton('channel-temp-toggle-btn', _lastChannelWeather);
}

function _updateCompareTempToggle() {
    _updateTempToggleButton('compare-temp-toggle-btn', _lastCompareWeather);
}

function _updateChannelSelectionControls() {
    var channelTimeTabs = document.getElementById('channel-time-tabs');
    var channelSelect = document.getElementById('channel-select');
    var hasTimelineSelection = !!(channelSelect && channelSelect.value);
    if (channelTimeTabs) channelTimeTabs.style.display = hasTimelineSelection ? '' : 'none';

    var hasCompareSelection = _compareChannels.length > 0;
    var compareTimeTabs = document.getElementById('compare-time-tabs');
    var compareClearBtn = document.getElementById('compare-clear-btn');
    if (compareTimeTabs) compareTimeTabs.style.display = hasCompareSelection ? '' : 'none';
    if (compareClearBtn) compareClearBtn.style.display = hasCompareSelection ? '' : 'none';
}

function toggleChannelTempOverlay() {
    _tempOverlayVisible = !_tempOverlayVisible;
    _updateChannelTempToggle();
    _updateCompareTempToggle();
    _renderChannelTimelineCharts();
    _renderCompareCharts();
}
window.toggleChannelTempOverlay = toggleChannelTempOverlay;

function toggleCompareTempOverlay() {
    _tempOverlayVisible = !_tempOverlayVisible;
    _updateChannelTempToggle();
    _updateCompareTempToggle();
    _renderChannelTimelineCharts();
    _renderCompareCharts();
}
window.toggleCompareTempOverlay = toggleCompareTempOverlay;

function _updateChannelInfoBar(direction, channelId) {
    var bar = document.getElementById('channel-info-bar');
    if (!bar) return;
    if (!_cachedChannelData) { bar.style.display = 'none'; return; }
    var channels = direction === 'ds'
        ? (_cachedChannelData.ds_channels || [])
        : (_cachedChannelData.us_channels || []);
    var ch = null;
    for (var i = 0; i < channels.length; i++) {
        if (String(channels[i].channel_id) === String(channelId)) { ch = channels[i]; break; }
    }
    if (!ch) { bar.style.display = 'none'; return; }
    while (bar.firstChild) bar.removeChild(bar.firstChild);
    var dir = direction.toUpperCase();
    var health = ch.health || 'unknown';
    var healthLabel = T['health_' + health] || health;

    bar.appendChild(_makeInfoItem(dir + ' ' + channelId, true));
    bar.appendChild(_makeInfoSep());
    if (ch.frequency) {
        var freqStr = String(ch.frequency);
        bar.appendChild(_makeInfoItem(freqStr.indexOf('MHz') === -1 ? freqStr + ' MHz' : freqStr));
    }
    bar.appendChild(_makeInfoItem('DOCSIS ' + (ch.docsis_version || '3.0')));
    bar.appendChild(_makeInfoSep());
    if (ch.power != null) bar.appendChild(_makeInfoItemWithLabel('Power', ch.power, 'dBmV'));
    if (ch.snr != null) bar.appendChild(_makeInfoItemWithLabel('SNR', ch.snr, 'dB'));
    bar.appendChild(_makeInfoSep());
    var healthEl = document.createElement('span');
    healthEl.className = 'ch-info-health ' + health;
    healthEl.textContent = healthLabel;
    bar.appendChild(healthEl);
    bar.style.display = '';
}

var _cachedChannelData = null;
var _lastChannelTimelineData = null;
var _lastChannelTimelineContext = null;
var _lastChannelWeather = null;
var _channelTimelineRequestSeq = 0;

function _renderChannelTimelineCharts() {
    var data = _lastChannelTimelineData;
    var ctx = _lastChannelTimelineContext || {};
    if (!data || data.length === 0) return;
    var direction = ctx.direction || 'ds';
    var docsisVersion = ctx.docsisVersion || '3.0';
    var days = ctx.days || '1d';

    var xLabels = docsightFormatXAxisLabels(data.map(function(d) { return d.timestamp || ''; }), days);
    var tempOpts = _channelWeatherHasData(_lastChannelWeather) ? { tempData: _lastChannelWeather } : null;
    var tempByTimestamp = null;
    if (tempOpts) {
        tempByTimestamp = {};
        data.forEach(function(d, idx) { tempByTimestamp[d.timestamp] = _lastChannelWeather[idx]; });
    }
    var powerDatasets = [{label: T.power_dbmv || 'Power (dBmV)', data: data.map(function(d){ return d.power; }), color: '#00e5f0', showPoints: false}];
    var powerThresholds = direction === 'ds' ? DS_POWER_THRESHOLDS : US_POWER_THRESHOLDS;
    var powerCard = document.querySelector('#channel-charts .chart-card:first-child');
    var powerLabel = powerCard ? powerCard.querySelector('.chart-label') : null;
    if (direction === 'ds') {
        powerDatasets.push({label: T.snr_db || 'SNR (dB)', data: data.map(function(d){ return d.snr; }), color: '#66ff77', showPoints: false});
        powerThresholds = null; /* DS combines Power + SNR, thresholds don't apply */
        if (powerLabel) powerLabel.textContent = (T.power_dbmv || 'Power') + ' & ' + (T.snr_db || 'SNR');
        var showErrors = _hasChannelDocsisErrorSeries(data);
        _setChartCardVisible('channel-errors-card', 'chart-ch-errors', showErrors);
        if (showErrors) {
            renderChart('chart-ch-errors', xLabels, [
                {label: T.correctable || 'Correctable', data: data.map(function(d){ return d.correctable_errors; }), color: '#2196f3'},
                {label: T.uncorrectable || 'Uncorrectable', data: data.map(function(d){ return d.uncorrectable_errors; }), color: '#f44336'}
            ], 'bar');
        }
    } else {
        if (powerLabel) powerLabel.textContent = T.power_dbmv || 'Power (dBmV)';
        _setChartCardVisible('channel-errors-card', 'chart-ch-errors', false);
    }
    renderChart('chart-ch-power', xLabels, powerDatasets, null, powerThresholds, tempOpts);

    // Modulation timeline (stepped line chart)
    var modCard = document.getElementById('channel-modulation-card');
    var mods = data.filter(function(d) { return d.modulation; });
    if (mods.length === 0) {
        modCard.style.display = 'none';
    } else {
        modCard.style.display = '';
        // Fixed QAM scales per channel direction and DOCSIS version
        var is31 = docsisVersion === '3.1' || docsisVersion === '4.0';
        var usQam30 = [4, 8, 16, 32, 64, 128];
        var usQam31 = [4, 8, 16, 32, 64, 128, 256, 512, 1024];
        var dsQam30 = [64, 256];
        var dsQam31 = [16, 64, 256, 1024, 2048, 4096];
        var qamSteps;
        if (direction === 'us') { qamSteps = is31 ? usQam31 : usQam30; }
        else { qamSteps = is31 ? dsQam31 : dsQam30; }
        var qamLabel = {}; qamSteps.forEach(function(v) { qamLabel[v] = v + 'QAM'; });
        var qamMap = {}; qamSteps.forEach(function(v, i) { qamMap[v + 'QAM'] = i; });
        var modLabels = docsightFormatXAxisLabels(mods.map(function(d) { return d.timestamp; }), days);
        var modValues = mods.map(function(d) { return qamMap[d.modulation] !== undefined ? qamMap[d.modulation] : -1; });
        var tickValues = [];
        for (var qi = 0; qi < qamSteps.length; qi++) tickValues.push(qi);
        renderChart('chart-ch-modulation', modLabels, [
            {label: T.modulation || 'Modulation', data: modValues, color: '#ffab40', stepped: true, showPoints: false}
        ], null, null, {
            tempData: tempOpts ? mods.map(function(d) { return tempByTimestamp[d.timestamp]; }) : null,
            yTickCallback: function(value) { return qamLabel[qamSteps[value]] || ''; },
            tooltipLabelCallback: function(ctx) {
                if (ctx.dataset.yAxisID === 'y-temp') return ctx.dataset.label + ': ' + fmtTemp(ctx.raw);
                return (T.modulation || 'Modulation') + ': ' + (qamLabel[qamSteps[ctx.raw]] || ctx.raw);
            },
            yMin: -0.5,
            yMax: qamSteps.length - 0.5,
            yAxisSize: 72,
            zoomYAxisSize: 80,
            maxXTicks: 4,
            yAfterBuildTicks: function(axis) {
                axis.ticks = tickValues.map(function(v) { return {value: v}; });
            }
        });
    }
}

function loadChannelTimeline() {
    var sel = document.getElementById('channel-select');
    var val = sel.value;
    var chartsEl = document.getElementById('channel-charts');
    var emptyEl = document.getElementById('channel-empty');
    var noDataEl = document.getElementById('channel-no-data');
    var loadingEl = document.getElementById('channel-loading');
    var infoBar = document.getElementById('channel-info-bar');
    if (!val) {
        chartsEl.style.display = 'none';
        noDataEl.style.display = 'none';
        loadingEl.style.display = 'none';
        if (infoBar) infoBar.style.display = 'none';
        _updateChannelSelectionControls();
        _channelTimelineRequestSeq++;
        _lastChannelTimelineData = null;
        _lastChannelWeather = null;
        _lastChannelTimelineContext = null;
        _updateChannelTempToggle();
        emptyEl.style.display = '';
        writeChannelHash();
        return;
    }
    var parts = val.split('-');
    _updateChannelSelectionControls();
    var direction = parts[0];
    var channelId = parts[1];
    var selectedOpt = sel.options[sel.selectedIndex];
    var docsisVersion = selectedOpt ? selectedOpt.dataset.docsis || '3.0' : '3.0';
    var days = getPillValue('channel-time-tabs') || '1d';
    writeChannelHash();
    var requestId = ++_channelTimelineRequestSeq;

    loadingEl.style.display = '';
    chartsEl.style.display = 'none';
    emptyEl.style.display = 'none';
    noDataEl.style.display = 'none';
    _updateChannelInfoBar(direction, channelId);

    fetch('/api/channel-history?channel_id=' + channelId + '&direction=' + direction + '&range=' + encodeURIComponent(days))
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (requestId !== _channelTimelineRequestSeq) return;
            loadingEl.style.display = 'none';
            if (!data || data.length === 0) {
                _lastChannelTimelineData = null;
                _lastChannelWeather = null;
                _lastChannelTimelineContext = null;
                _updateChannelTempToggle();
                noDataEl.textContent = T.no_channel_data || 'No data available for this channel.';
                noDataEl.style.display = '';
                return;
            }
            chartsEl.style.display = '';
            _lastChannelTimelineData = data;
            _lastChannelTimelineContext = {
                direction: direction,
                docsisVersion: docsisVersion,
                days: days
            };
            _lastChannelWeather = null;
            _updateChannelTempToggle();
            var timestamps = data.map(function(d) { return d.timestamp; }).filter(function(ts) { return !!ts; });
            return _fetchChannelWeatherForTimestamps(timestamps).then(function(weatherData) {
                if (requestId !== _channelTimelineRequestSeq) return;
                _lastChannelWeather = _alignWeatherToChannelTimestamps(timestamps, weatherData, days);
                _updateChannelTempToggle();
                _renderChannelTimelineCharts();
            });
        })
        .catch(function() {
            if (requestId !== _channelTimelineRequestSeq) return;
            loadingEl.style.display = 'none';
            noDataEl.textContent = T.trend_error || 'Error loading data.';
            noDataEl.style.display = '';
        });
}
window.loadChannelTimeline = loadChannelTimeline;

/* ── Channel Compare ── */
var _compareChannels = [];
var _compareColors = ['#a855f7', '#3b82f6', '#10b981', '#f59e0b', '#ec4899', '#06b6d4'];
var _compareChannelData = null;
var _comparePreset = null;
var _compareState = { ds: { channels: [], preset: null }, us: { channels: [], preset: null } };
var _lastCompareDir = 'ds';
var _lastCompareWeather = null;
var _lastCompareRenderContext = null;
var _compareRequestSeq = 0;

function compareColor(index) {
    if (index < _compareColors.length) return _compareColors[index];
    return 'hsl(' + Math.round((index * 137.508) % 360) + ', 72%, 58%)';
}

function getCompareDirection() {
    return getPillValue('compare-dir-tabs') || 'ds';
}

function getComparePresetLabel(dir) {
    return dir === 'ds'
        ? (T.all_downstream || 'All Downstream')
        : (T.all_upstream || 'All Upstream');
}

function buildCompareChannelEntry(ch, index, dir) {
    var prefix = dir === 'ds' ? 'DS' : 'US';
    return {
        id: ch.channel_id,
        label: prefix + ' ' + ch.channel_id + ' (' + (ch.frequency || '') + ')',
        color: compareColor(index),
        docsis: ch.docsis_version || '3.0'
    };
}

function updateCompareActionLabels() {
    var addAllBtn = document.getElementById('compare-add-all-btn');
    if (addAllBtn) addAllBtn.textContent = getComparePresetLabel(getCompareDirection());
}

function showCompareError(message, error) {
    var loadingEl = document.getElementById('compare-loading');
    var emptyEl = document.getElementById('compare-empty');
    if (loadingEl) loadingEl.style.display = 'none';
    if (emptyEl) {
        emptyEl.textContent = message;
        emptyEl.style.display = '';
    }
    if (error) console.error('Channel compare error:', error);
}

function clearCompareCharts() {
    _compareRequestSeq++;
    _lastCompareWeather = null;
    _lastCompareRenderContext = null;
    _updateCompareTempToggle();
    document.getElementById('compare-charts').style.display = 'none';
    document.getElementById('compare-loading').style.display = 'none';
    ['chart-cmp-power', 'chart-cmp-snr', 'chart-cmp-errors', 'chart-cmp-modulation'].forEach(function(id) {
        if (charts[id]) { charts[id].destroy(); delete charts[id]; }
    });
}

function populateCompareChannelList(data) {
    var dir = getCompareDirection();
    var sel = document.getElementById('compare-channel-select');
    updateCompareActionLabels();
    sel.innerHTML = '<option value="">' + (T.select_channel || 'Select Channel') + '</option>';
    var channels = dir === 'ds' ? (data.ds_channels || []) : (data.us_channels || []);
    channels.forEach(function(ch) {
        var already = _compareChannels.some(function(c) { return c.id === ch.channel_id; });
        if (already) return;
        var opt = document.createElement('option');
        opt.value = ch.channel_id;
        opt.dataset.docsis = ch.docsis_version || '3.0';
        opt.dataset.freq = ch.frequency || '';
        var prefix = dir === 'ds' ? 'DS' : 'US';
        opt.textContent = prefix + ' ' + ch.channel_id + ' (' + (ch.frequency || '') + ')';
        sel.appendChild(opt);
    });
}

function loadCompareChannelList(data) {
    if (data) {
        populateCompareChannelList(data);
        return;
    }
    fetch('/api/channels')
        .then(function(r) { return r.json(); })
        .then(function(payload) {
            populateCompareChannelList(payload);
        })
        .catch(function(error) {
            showCompareError(T.trend_error || 'Error loading data.', error);
        });
}

function onCompareDirectionChange() {
    var oldDir = _lastCompareDir;
    var newDir = getCompareDirection();
    // Save current state to old direction slot
    _compareState[oldDir] = { channels: _compareChannels.slice(), preset: _comparePreset };
    // Restore from new direction slot
    _compareChannels = _compareState[newDir].channels.slice();
    _comparePreset = _compareState[newDir].preset;
    _lastCompareDir = newDir;
    renderCompareChips();
    clearCompareCharts();
    loadCompareChannelList();
    updateCompareActionLabels();
    if (_compareChannels.length > 0) {
        loadCompareCharts();
    } else {
        var emptyEl = document.getElementById('compare-empty');
        emptyEl.textContent = T.no_channels_selected || 'Select channels to compare';
        emptyEl.style.display = '';
        writeChannelHash();
    }
}
window.onCompareDirectionChange = onCompareDirectionChange;

function addCompareChannel() {
    var sel = document.getElementById('compare-channel-select');
    var opt = sel.options[sel.selectedIndex];
    if (!opt || !opt.value) return;
    if (_compareChannels.length >= 6) {
        showToast(T.max_channels_reached || 'Maximum 6 channels in manual selection', 'error');
        return;
    }
    _comparePreset = null;
    var id = parseInt(opt.value);
    if (_compareChannels.some(function(c) { return c.id === id; })) return;
    var dir = getCompareDirection();
    var prefix = dir === 'ds' ? 'DS' : 'US';
    _compareChannels.push({
        id: id,
        label: prefix + ' ' + id + ' (' + (opt.dataset.freq || '') + ')',
        color: compareColor(_compareChannels.length),
        docsis: opt.dataset.docsis || '3.0'
    });
    renderCompareChips();
    loadCompareChannelList();
    loadCompareCharts();
    writeChannelHash();
}
window.addCompareChannel = addCompareChannel;

function addAllCompareChannels() {
    var dir = getCompareDirection();
    fetch('/api/channels')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var channels = dir === 'ds' ? (data.ds_channels || []) : (data.us_channels || []);
            if (channels.length === 0) {
                clearCompareChannels();
                var emptyEl = document.getElementById('compare-empty');
                emptyEl.textContent = T.no_channel_data || 'No data available.';
                emptyEl.style.display = '';
                return;
            }
            _comparePreset = 'all';
            _compareChannels = channels.map(function(ch, index) {
                return buildCompareChannelEntry(ch, index, dir);
            });
            renderCompareChips();
            loadCompareChannelList(data);
            loadCompareCharts();
            writeChannelHash();
        })
        .catch(function(error) {
            showCompareError(T.trend_error || 'Error loading data.', error);
        });
}
window.addAllCompareChannels = addAllCompareChannels;

function clearCompareChannels() {
    _comparePreset = null;
    _compareChannels = [];
    _compareState[_lastCompareDir] = { channels: [], preset: null };
    renderCompareChips();
    var emptyEl = document.getElementById('compare-empty');
    emptyEl.textContent = T.no_channels_selected || 'Select channels to compare';
    emptyEl.style.display = '';
    clearCompareCharts();
    loadCompareChannelList();
    writeChannelHash();
}
window.clearCompareChannels = clearCompareChannels;

function removeCompareChannel(id) {
    _comparePreset = null;
    _compareChannels = _compareChannels.filter(function(c) { return c.id !== id; });
    // Re-assign colors sequentially
    _compareChannels.forEach(function(c, i) { c.color = compareColor(i); });
    renderCompareChips();
    loadCompareChannelList();
    if (_compareChannels.length > 0) {
        loadCompareCharts();
    } else {
        clearCompareCharts();
    }
    writeChannelHash();
}
window.removeCompareChannel = removeCompareChannel;

function renderCompareChips() {
    var container = document.getElementById('compare-chips');
    container.innerHTML = '';
    _updateChannelSelectionControls();
    if (_comparePreset === 'all' && _compareChannels.length > 0) {
        var presetChip = document.createElement('span');
        presetChip.className = 'compare-chip';
        presetChip.style.backgroundColor = getCompareDirection() === 'ds' ? '#3b82f6' : '#10b981';
        presetChip.innerHTML = escapeHtml(getComparePresetLabel(getCompareDirection()) + ' (' + _compareChannels.length + ')')
            + ' <button class="compare-chip-remove" onclick="clearCompareChannels()">&times;</button>';
        container.appendChild(presetChip);
        return;
    }
    _compareChannels.forEach(function(ch) {
        var chip = document.createElement('span');
        chip.className = 'compare-chip';
        chip.style.backgroundColor = ch.color;
        chip.innerHTML = escapeHtml(ch.label) + ' <button class="compare-chip-remove" onclick="removeCompareChannel(' + ch.id + ')">&times;</button>';
        container.appendChild(chip);
    });
}

function _renderCompareCharts() {
    var ctx = _lastCompareRenderContext;
    if (!ctx || !ctx.data || !ctx.timestamps || ctx.timestamps.length === 0) return;
    var data = ctx.data;
    var timestamps = ctx.timestamps;
    var days = ctx.days || '1d';
    var dir = ctx.dir || getCompareDirection();
    var xLabels = docsightFormatXAxisLabels(timestamps, days);
    var tempOpts = _channelWeatherHasData(_lastCompareWeather) ? { tempData: _lastCompareWeather } : null;

    // Build lookup maps per channel: timestamp -> data point
    var lookups = {};
    _compareChannels.forEach(function(ch) {
        var map = {};
        (data[String(ch.id)] || []).forEach(function(d) { map[d.timestamp] = d; });
        lookups[ch.id] = map;
    });

    // Power Chart
    var powerDatasets = _compareChannels.map(function(ch) {
        return {
            label: 'CH ' + ch.id,
            data: timestamps.map(function(ts) { var d = lookups[ch.id][ts]; return d ? d.power : null; }),
            color: ch.color,
            showPoints: false
        };
    });
    var powerThresholds = dir === 'ds' ? DS_POWER_THRESHOLDS : US_POWER_THRESHOLDS;
    renderChart('chart-cmp-power', xLabels, powerDatasets, null, powerThresholds, tempOpts);

    // SNR Chart (DS only)
    var snrCard = document.getElementById('compare-snr-card');
    if (dir === 'ds') {
        snrCard.style.display = '';
        var snrDatasets = _compareChannels.map(function(ch) {
            return {
                label: 'CH ' + ch.id,
                data: timestamps.map(function(ts) { var d = lookups[ch.id][ts]; return d ? d.snr : null; }),
                color: ch.color,
                showPoints: false
            };
        });
        renderChart('chart-cmp-snr', xLabels, snrDatasets, null, DS_SNR_THRESHOLDS, tempOpts);
    } else {
        snrCard.style.display = 'none';
    }

    // Errors Chart (DS only, lines not bars)
    if (dir === 'ds') {
        var compareHasErrors = _compareChannels.some(function(ch) {
            return _hasChannelDocsisErrorSeries(data[String(ch.id)] || []);
        });
        _setChartCardVisible('compare-errors-card', 'chart-cmp-errors', compareHasErrors);
        if (compareHasErrors) {
            var errorDatasets = [];
            _compareChannels.forEach(function(ch) {
                errorDatasets.push({
                    label: 'CH ' + ch.id + ' ' + (T.uncorrectable || 'Uncorr.'),
                    data: timestamps.map(function(ts) { var d = lookups[ch.id][ts]; return d && d.uncorrectable_errors != null ? d.uncorrectable_errors : null; }),
                    color: ch.color,
                    showPoints: false
                });
                errorDatasets.push({
                    label: 'CH ' + ch.id + ' ' + (T.correctable || 'Corr.'),
                    data: timestamps.map(function(ts) { var d = lookups[ch.id][ts]; return d && d.correctable_errors != null ? d.correctable_errors : null; }),
                    color: ch.color,
                    dashed: true,
                    showPoints: false
                });
            });
            renderChart('chart-cmp-errors', xLabels, errorDatasets, null, null, tempOpts);
        }
    } else {
        _setChartCardVisible('compare-errors-card', 'chart-cmp-errors', false);
    }

    // Modulation Chart
    var modCard = document.getElementById('compare-modulation-card');
    var hasMod = false;
    _compareChannels.forEach(function(ch) {
        var chData = data[String(ch.id)] || [];
        if (chData.some(function(d) { return d.modulation; })) hasMod = true;
    });
    if (!hasMod) {
        modCard.style.display = 'none';
    } else {
        modCard.style.display = '';
        // Collect all unique QAM values
        var allQam = {};
        _compareChannels.forEach(function(ch) {
            (data[String(ch.id)] || []).forEach(function(d) {
                if (d.modulation) allQam[d.modulation] = true;
            });
        });
        var qamNames = Object.keys(allQam).sort(function(a, b) {
            var na = parseInt(a) || 0, nb = parseInt(b) || 0;
            return na - nb;
        });
        var qamMap = {};
        qamNames.forEach(function(name, idx) { qamMap[name] = idx; });
        var qamLabel = {};
        qamNames.forEach(function(name, idx) { qamLabel[idx] = name; });

        var modDatasets = _compareChannels.map(function(ch) {
            return {
                label: 'CH ' + ch.id,
                data: timestamps.map(function(ts) {
                    var d = lookups[ch.id][ts];
                    if (!d || !d.modulation) return null;
                    return qamMap[d.modulation] !== undefined ? qamMap[d.modulation] : null;
                }),
                color: ch.color,
                stepped: true,
                showPoints: false
            };
        });
        var tickValues = [];
        for (var qi = 0; qi < qamNames.length; qi++) tickValues.push(qi);
        renderChart('chart-cmp-modulation', xLabels, modDatasets, null, null, {
            tempData: _channelWeatherHasData(_lastCompareWeather) ? _lastCompareWeather : null,
            yTickCallback: function(value) { return qamLabel[value] || ''; },
            tooltipLabelCallback: function(ctx) {
                if (ctx.dataset.yAxisID === 'y-temp') return ctx.dataset.label + ': ' + fmtTemp(ctx.raw);
                return ctx.dataset.label + ': ' + (qamLabel[ctx.raw] || ctx.raw);
            },
            yMin: -0.5,
            yMax: qamNames.length - 0.5,
            yAxisSize: 72,
            zoomYAxisSize: 80,
            yAfterBuildTicks: function(axis) {
                axis.ticks = tickValues.map(function(v) { return {value: v}; });
            }
        });
    }
}

function loadCompareCharts() {
    var chartsEl = document.getElementById('compare-charts');
    var emptyEl = document.getElementById('compare-empty');
    var loadingEl = document.getElementById('compare-loading');
    if (_compareChannels.length === 0) {
        _compareRequestSeq++;
        _lastCompareWeather = null;
        _lastCompareRenderContext = null;
        _updateCompareTempToggle();
        chartsEl.style.display = 'none';
        emptyEl.textContent = T.no_channels_selected || 'Select channels to compare';
        emptyEl.style.display = '';
        return;
    }
    var dir = getCompareDirection();
    var days = getPillValue('compare-time-tabs') || '1d';
    var ids = _compareChannels.map(function(c) { return c.id; }).join(',');
    writeChannelHash();
    var requestId = ++_compareRequestSeq;

    loadingEl.style.display = '';
    chartsEl.style.display = 'none';
    emptyEl.style.display = 'none';

    fetch('/api/channel-compare?channels=' + ids + '&direction=' + dir + '&range=' + encodeURIComponent(days))
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (requestId !== _compareRequestSeq) return;
            loadingEl.style.display = 'none';
            _compareChannelData = data;

            // Build unified timestamp list from all channels
            var tsSet = {};
            _compareChannels.forEach(function(ch) {
                var chData = data[String(ch.id)] || [];
                chData.forEach(function(d) { tsSet[d.timestamp] = true; });
            });
            var timestamps = Object.keys(tsSet).sort();
            if (timestamps.length === 0) {
                _compareRequestSeq++;
                _lastCompareWeather = null;
                _lastCompareRenderContext = null;
                _updateCompareTempToggle();
                emptyEl.textContent = T.compare_no_data_range || 'No data for the selected channels in this time range.';
                emptyEl.style.display = '';
                return;
            }
            chartsEl.style.display = '';
            _lastCompareRenderContext = {
                data: data,
                timestamps: timestamps,
                days: days,
                dir: dir
            };
            _lastCompareWeather = null;
            _updateCompareTempToggle();
            return _fetchChannelWeatherForTimestamps(timestamps).then(function(weatherData) {
                if (requestId !== _compareRequestSeq) return;
                _lastCompareWeather = _alignWeatherToChannelTimestamps(timestamps, weatherData, days);
                _updateCompareTempToggle();
                _renderCompareCharts();
            });
        })
        .catch(function() {
            if (requestId !== _compareRequestSeq) return;
            loadingEl.style.display = 'none';
            emptyEl.textContent = T.trend_error || 'Error loading data.';
            emptyEl.style.display = '';
        });
}
window.loadCompareCharts = loadCompareCharts;
