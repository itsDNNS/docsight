/* ── Channel Timeline + Compare ── */
/* Extracted from IIFE – depends on: T, charts, renderChart, getPillValue,
   DS_POWER_THRESHOLDS, DS_SNR_THRESHOLDS, US_POWER_THRESHOLDS */

/* ── Channel Mode Switch (Timeline / Compare) ── */
function switchChannelMode() {
    var mode = getPillValue('channel-mode-tabs') || 'timeline';
    var timelinePanel = document.getElementById('channel-panel-timeline');
    var comparePanel = document.getElementById('channel-panel-compare');
    if (mode === 'compare') {
        timelinePanel.style.display = 'none';
        comparePanel.style.display = '';
        loadCompareChannelList();
    } else {
        timelinePanel.style.display = '';
        comparePanel.style.display = 'none';
    }
}
window.switchChannelMode = switchChannelMode;

/* ── Channel Timeline ── */
var _channelsLoaded = false;

function loadChannelList() {
    if (_channelsLoaded) return;
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
            _channelsLoaded = true;
        })
        .catch(function() {});
}

function loadChannelTimeline() {
    var sel = document.getElementById('channel-select');
    var val = sel.value;
    var chartsEl = document.getElementById('channel-charts');
    var emptyEl = document.getElementById('channel-empty');
    var loadingEl = document.getElementById('channel-loading');
    if (!val) {
        chartsEl.style.display = 'none';
        emptyEl.style.display = 'none';
        return;
    }
    var parts = val.split('-');
    var direction = parts[0];
    var channelId = parts[1];
    var selectedOpt = sel.options[sel.selectedIndex];
    var docsisVersion = selectedOpt ? selectedOpt.dataset.docsis || '3.0' : '3.0';
    var days = getPillValue('channel-time-tabs');

    loadingEl.style.display = '';
    chartsEl.style.display = 'none';
    emptyEl.style.display = 'none';

    fetch('/api/channel-history?channel_id=' + channelId + '&direction=' + direction + '&days=' + days)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            loadingEl.style.display = 'none';
            if (!data || data.length === 0) {
                emptyEl.textContent = T.no_channel_data || 'No data available for this channel.';
                emptyEl.style.display = '';
                return;
            }
            chartsEl.style.display = '';
            var xLabels = data.map(function(d) {
                if (!d.timestamp) return '';
                if (parseInt(days) <= 1) return d.timestamp.substring(11, 16);
                return d.timestamp.substring(5, 16).replace('T', ' ');
            });
            var powerDatasets = [{label: T.power_dbmv || 'Power (dBmV)', data: data.map(function(d){ return d.power; }), color: '#00e5f0'}];
            var powerThresholds = direction === 'ds' ? DS_POWER_THRESHOLDS : US_POWER_THRESHOLDS;
            var powerCard = document.querySelector('#channel-charts .chart-card:first-child');
            var powerLabel = powerCard ? powerCard.querySelector('.chart-label') : null;
            var errorsCard = document.getElementById('channel-errors-card');
            if (direction === 'ds') {
                powerDatasets.push({label: T.snr_db || 'SNR (dB)', data: data.map(function(d){ return d.snr; }), color: '#66ff77'});
                powerThresholds = null; /* DS combines Power + SNR, thresholds don't apply */
                if (powerLabel) powerLabel.textContent = (T.power_dbmv || 'Power') + ' & ' + (T.snr_db || 'SNR');
                errorsCard.style.display = '';
                renderChart('chart-ch-errors', xLabels, [
                    {label: T.correctable || 'Correctable', data: data.map(function(d){ return d.correctable_errors; }), color: '#2196f3'},
                    {label: T.uncorrectable || 'Uncorrectable', data: data.map(function(d){ return d.uncorrectable_errors; }), color: '#f44336'}
                ], 'bar');
            } else {
                if (powerLabel) powerLabel.textContent = T.power_dbmv || 'Power (dBmV)';
                errorsCard.style.display = 'none';
            }
            renderChart('chart-ch-power', xLabels, powerDatasets, null, powerThresholds);

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
                var modLabels = mods.map(function(d) { return d.timestamp.substring(5, 16).replace('T', ' '); });
                var modValues = mods.map(function(d) { return qamMap[d.modulation] !== undefined ? qamMap[d.modulation] : -1; });
                var tickValues = [];
                for (var qi = 0; qi < qamSteps.length; qi++) tickValues.push(qi);
                renderChart('chart-ch-modulation', modLabels, [
                    {label: T.modulation || 'Modulation', data: modValues, color: '#ffab40', stepped: true}
                ], null, null, {
                    yTickCallback: function(value) { return qamLabel[qamSteps[value]] || ''; },
                    tooltipLabelCallback: function(ctx) { return (T.modulation || 'Modulation') + ': ' + (qamLabel[qamSteps[ctx.raw]] || ctx.raw); },
                    yMin: -0.5,
                    yMax: qamSteps.length - 0.5,
                    yAfterBuildTicks: function(axis) {
                        axis.ticks = tickValues.map(function(v) { return {value: v}; });
                    }
                });
            }
        })
        .catch(function() {
            loadingEl.style.display = 'none';
            emptyEl.textContent = T.trend_error || 'Error loading data.';
            emptyEl.style.display = '';
        });
}
window.loadChannelTimeline = loadChannelTimeline;

/* ── Channel Compare ── */
var _compareChannels = [];
var _compareColors = ['#a855f7', '#3b82f6', '#10b981', '#f59e0b', '#ec4899', '#06b6d4'];
var _compareChannelData = null;

function loadCompareChannelList() {
    var dir = getPillValue('compare-dir-tabs') || 'ds';
    var sel = document.getElementById('compare-channel-select');
    fetch('/api/channels')
        .then(function(r) { return r.json(); })
        .then(function(data) {
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
        })
        .catch(function() {});
}

function onCompareDirectionChange() {
    _compareChannels = [];
    renderCompareChips();
    var chartsEl = document.getElementById('compare-charts');
    var emptyEl = document.getElementById('compare-empty');
    chartsEl.style.display = 'none';
    emptyEl.style.display = 'none';
    // Destroy existing compare charts
    ['chart-cmp-power', 'chart-cmp-snr', 'chart-cmp-errors', 'chart-cmp-modulation'].forEach(function(id) {
        if (charts[id]) { charts[id].destroy(); delete charts[id]; }
    });
    loadCompareChannelList();
}
window.onCompareDirectionChange = onCompareDirectionChange;

function addCompareChannel() {
    var sel = document.getElementById('compare-channel-select');
    var opt = sel.options[sel.selectedIndex];
    if (!opt || !opt.value) return;
    if (_compareChannels.length >= 6) {
        alert(T.max_channels_reached || 'Maximum 6 channels');
        return;
    }
    var id = parseInt(opt.value);
    if (_compareChannels.some(function(c) { return c.id === id; })) return;
    var dir = getPillValue('compare-dir-tabs') || 'ds';
    var prefix = dir === 'ds' ? 'DS' : 'US';
    _compareChannels.push({
        id: id,
        label: prefix + ' ' + id + ' (' + (opt.dataset.freq || '') + ')',
        color: _compareColors[_compareChannels.length],
        docsis: opt.dataset.docsis || '3.0'
    });
    renderCompareChips();
    loadCompareChannelList();
    loadCompareCharts();
}
window.addCompareChannel = addCompareChannel;

function removeCompareChannel(id) {
    _compareChannels = _compareChannels.filter(function(c) { return c.id !== id; });
    // Re-assign colors sequentially
    _compareChannels.forEach(function(c, i) { c.color = _compareColors[i]; });
    renderCompareChips();
    loadCompareChannelList();
    if (_compareChannels.length > 0) {
        loadCompareCharts();
    } else {
        document.getElementById('compare-charts').style.display = 'none';
        ['chart-cmp-power', 'chart-cmp-snr', 'chart-cmp-errors', 'chart-cmp-modulation'].forEach(function(id) {
            if (charts[id]) { charts[id].destroy(); delete charts[id]; }
        });
    }
}
window.removeCompareChannel = removeCompareChannel;

function renderCompareChips() {
    var container = document.getElementById('compare-chips');
    container.innerHTML = '';
    _compareChannels.forEach(function(ch) {
        var chip = document.createElement('span');
        chip.className = 'compare-chip';
        chip.style.backgroundColor = ch.color;
        chip.innerHTML = ch.label + ' <button class="compare-chip-remove" onclick="removeCompareChannel(' + ch.id + ')">&times;</button>';
        container.appendChild(chip);
    });
}

function loadCompareCharts() {
    var chartsEl = document.getElementById('compare-charts');
    var emptyEl = document.getElementById('compare-empty');
    var loadingEl = document.getElementById('compare-loading');
    if (_compareChannels.length === 0) {
        chartsEl.style.display = 'none';
        emptyEl.textContent = T.no_channels_selected || 'Select channels to compare';
        emptyEl.style.display = '';
        return;
    }
    var dir = getPillValue('compare-dir-tabs') || 'ds';
    var days = getPillValue('compare-time-tabs') || '7';
    var ids = _compareChannels.map(function(c) { return c.id; }).join(',');

    loadingEl.style.display = '';
    chartsEl.style.display = 'none';
    emptyEl.style.display = 'none';

    fetch('/api/channel-compare?channels=' + ids + '&direction=' + dir + '&days=' + days)
        .then(function(r) { return r.json(); })
        .then(function(data) {
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
                emptyEl.textContent = T.no_channel_data || 'No data available.';
                emptyEl.style.display = '';
                return;
            }
            chartsEl.style.display = '';

            var xLabels = timestamps.map(function(ts) {
                if (parseInt(days) <= 1) return ts.substring(11, 16);
                return ts.substring(5, 16).replace('T', ' ');
            });

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
                    color: ch.color
                };
            });
            var powerThresholds = dir === 'ds' ? DS_POWER_THRESHOLDS : US_POWER_THRESHOLDS;
            renderChart('chart-cmp-power', xLabels, powerDatasets, null, powerThresholds);

            // SNR Chart (DS only)
            var snrCard = document.getElementById('compare-snr-card');
            if (dir === 'ds') {
                snrCard.style.display = '';
                var snrDatasets = _compareChannels.map(function(ch) {
                    return {
                        label: 'CH ' + ch.id,
                        data: timestamps.map(function(ts) { var d = lookups[ch.id][ts]; return d ? d.snr : null; }),
                        color: ch.color
                    };
                });
                renderChart('chart-cmp-snr', xLabels, snrDatasets, null, DS_SNR_THRESHOLDS);
            } else {
                snrCard.style.display = 'none';
            }

            // Errors Chart (DS only, lines not bars)
            var errorsCard = document.getElementById('compare-errors-card');
            if (dir === 'ds') {
                errorsCard.style.display = '';
                var errorDatasets = [];
                _compareChannels.forEach(function(ch) {
                    errorDatasets.push({
                        label: 'CH ' + ch.id + ' ' + (T.uncorrectable || 'Uncorr.'),
                        data: timestamps.map(function(ts) { var d = lookups[ch.id][ts]; return d ? d.uncorrectable_errors : null; }),
                        color: ch.color
                    });
                    errorDatasets.push({
                        label: 'CH ' + ch.id + ' ' + (T.correctable || 'Corr.'),
                        data: timestamps.map(function(ts) { var d = lookups[ch.id][ts]; return d ? d.correctable_errors : null; }),
                        color: ch.color,
                        dashed: true
                    });
                });
                renderChart('chart-cmp-errors', xLabels, errorDatasets);
            } else {
                errorsCard.style.display = 'none';
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
                        stepped: true
                    };
                });
                var tickValues = [];
                for (var qi = 0; qi < qamNames.length; qi++) tickValues.push(qi);
                renderChart('chart-cmp-modulation', xLabels, modDatasets, null, null, {
                    yTickCallback: function(value) { return qamLabel[value] || ''; },
                    tooltipLabelCallback: function(ctx) { return ctx.dataset.label + ': ' + (qamLabel[ctx.raw] || ctx.raw); },
                    yMin: -0.5,
                    yMax: qamNames.length - 0.5,
                    yAfterBuildTicks: function(axis) {
                        axis.ticks = tickValues.map(function(v) { return {value: v}; });
                    }
                });
            }
        })
        .catch(function() {
            loadingEl.style.display = 'none';
            emptyEl.textContent = T.trend_error || 'Error loading data.';
            emptyEl.style.display = '';
        });
}
window.loadCompareCharts = loadCompareCharts;
