'use strict';
DOCSightSettings.smart_capture = function({showToast}) {
/* ── Smart Capture History ── */
// Note: uses innerHTML with escapeHtml() for all dynamic content, consistent with
// the existing pattern used throughout events.js, speedtest.js, and correlation.js.
function loadSmartCaptureHistory() {
    var loading = document.getElementById('sc-history-loading');
    var empty = document.getElementById('sc-history-empty');
    var tableWrap = document.getElementById('sc-history-table-wrap');
    var tbody = document.getElementById('sc-history-tbody');
    if (!tbody) return;

    if (loading) loading.style.display = '';
    if (empty) empty.style.display = 'none';
    if (tableWrap) tableWrap.style.display = 'none';

    fetch(docsightUrl('/api/smart-capture/executions?limit=50'))
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (loading) loading.style.display = 'none';
            var execs = data.executions || [];
            while (tbody.firstChild) tbody.removeChild(tbody.firstChild);
            if (execs.length === 0) {
                if (empty) empty.style.display = '';
                return;
            }
            if (tableWrap) tableWrap.style.display = '';
            var statusLabels = {
                completed: T.sc_status_completed || 'Completed',
                fired: T.sc_status_fired || 'Fired',
                pending: T.sc_status_pending || 'Pending',
                suppressed: T.sc_status_suppressed || 'Suppressed',
                expired: T.sc_status_expired || 'Expired'
            };
            execs.forEach(function(ex) {
                var tr = document.createElement('tr');
                var ts = ex.created_at ? ex.created_at.replace('T', ' ').replace('Z', '') : '';
                var trigger = escapeHtml(ex.trigger_type || '');
                var label = statusLabels[ex.status] || ex.status;
                var detail = '';
                if (ex.suppression_reason) {
                    detail = escapeHtml(ex.suppression_reason);
                } else if (ex.linked_result_id) {
                    detail = 'Result #' + ex.linked_result_id;
                } else if (ex.last_error) {
                    detail = escapeHtml(ex.last_error);
                }
                // Dynamic content sanitized via escapeHtml before insertion
                tr.innerHTML = '<td style="white-space:nowrap;font-size:0.85em;">' + escapeHtml(ts) + '</td>'
                    + '<td>' + trigger + '</td>'
                    + '<td><span class="sc-status-' + escapeHtml(ex.status) + '">' + escapeHtml(label) + '</span></td>'
                    + '<td style="font-size:0.85em;color:var(--muted);">' + detail + '</td>';
                tbody.appendChild(tr);
            });
            if (typeof lucide !== 'undefined') lucide.createIcons();
        })
        .catch(function() {
            if (loading) loading.style.display = 'none';
            if (empty) empty.style.display = '';
            showToast(T.sc_history_error || 'Failed to load execution history', false);
        });
}

/* ── Smart Capture Guardrails Summary ── */
function updateGuardrailsSummary() {
    var el = document.getElementById('sc-guardrails-summary');
    var cooldownEl = document.getElementById('sc_global_cooldown');
    var maxEl = document.getElementById('sc_max_actions_per_hour');
    var speedtestIntervalEl = document.getElementById('sc_speedtest_min_interval');
    var speedtestDailyEl = document.getElementById('sc_speedtest_max_actions_per_day');
    if (!el || !cooldownEl || !maxEl) return;
    var cooldown = parseInt(cooldownEl.value) || 0;
    var maxPerHour = parseInt(maxEl.value) || 1;
    var speedtestInterval = speedtestIntervalEl ? (parseInt(speedtestIntervalEl.value) || 0) : 0;
    var speedtestDaily = speedtestDailyEl ? (parseInt(speedtestDailyEl.value) || 0) : 0;
    var cooldownStr;
    if (cooldown >= 3600) cooldownStr = Math.round(cooldown / 3600) + 'h';
    else if (cooldown >= 60) cooldownStr = Math.round(cooldown / 60) + ' min';
    else cooldownStr = cooldown + 's';
    var speedtestIntervalStr;
    if (speedtestInterval >= 3600) speedtestIntervalStr = Math.round(speedtestInterval / 3600) + 'h';
    else if (speedtestInterval >= 60) speedtestIntervalStr = Math.round(speedtestInterval / 60) + ' min';
    else speedtestIntervalStr = speedtestInterval + 's';
    var tpl = T.sc_guardrails_summary || 'At most %max%/hour, minimum %cooldown% apart; Smart Capture speedtests: %speedtestMax%/day, %speedtestInterval% apart';
    el.textContent = tpl
        .replace('%max%', maxPerHour)
        .replace('%cooldown%', cooldownStr)
        .replace('%speedtestMax%', speedtestDaily)
        .replace('%speedtestInterval%', speedtestIntervalStr);
}

// Initialize guardrails summary on load and input
function init() {
    updateGuardrailsSummary();
    ['sc_global_cooldown', 'sc_max_actions_per_hour', 'sc_speedtest_min_interval', 'sc_speedtest_max_actions_per_day'].forEach(function(id) {
        var el = document.getElementById(id);
        if (el) el.addEventListener('input', updateGuardrailsSummary);
    });
}
return {init, loadSmartCaptureHistory};
};
