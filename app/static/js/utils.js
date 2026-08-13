/* ═══ DOCSight Utility Functions ═══ */

function escapeHtml(str) {
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
}

/* ── Export for AI Analysis ── */
var exportRawText = '';
var exportLoadId = 0;
var exportCloseHandlerAttached = false;
function isExportModalOpen() {
    var modal = document.getElementById('export-modal');
    return !!(modal && modal.open);
}
function resetExportState() {
    exportLoadId += 1;
    exportRawText = '';
    var textarea = document.getElementById('export-text');
    if (textarea) textarea.value = '';
    updateExportSize();
    setExportStatus('');
}
function ensureExportModalCloseHandler() {
    if (exportCloseHandlerAttached) return;
    var modal = document.getElementById('export-modal');
    if (!modal) return;
    exportCloseHandlerAttached = true;
    modal.addEventListener('close', resetExportState);
}
function exportForLLM() {
    ensureExportModalCloseHandler();
    var textarea = document.getElementById('export-text');
    var modeEl = document.querySelector('input[name="export-mode"]:checked');
    var mode = modeEl ? modeEl.value : 'full';
    var loadId = ++exportLoadId;
    exportRawText = '';
    textarea.value = T.export_no_data;
    setExportStatus(T.export_loading || 'Loading export preview...', 'progress');
    updateExportSize();
    window.DOCSightModal.open('export-modal');
    fetch(docsightUrl('/api/export?mode=' + encodeURIComponent(mode)))
        .then(function(r) {
            return r.json().then(function(data) {
                if (!r.ok || data.error) {
                    throw new Error(data.error || (T.export_error || 'Error loading export data.'));
                }
                return data;
            });
        })
        .then(function(data) {
            if (loadId !== exportLoadId || !isExportModalOpen()) return;
            exportRawText = data.text || '';
            refreshExportPreview();
            setExportStatus(T.export_ready || 'Review the export before copying or downloading.', 'success');
        })
        .catch(function(e) {
            if (loadId !== exportLoadId || !isExportModalOpen()) return;
            var message = e && e.message ? e.message : (T.export_error || 'Error loading export data.');
            textarea.value = message;
            updateExportSize();
            setExportStatus(message, 'error');
        });
}
function closeExportModal() {
    exportLoadId += 1;
    window.DOCSightModal.close('export-modal');
}
function setExportStatus(message, type) {
    var status = document.getElementById('export-status');
    if (!status) return;
    status.textContent = message || '';
    status.classList.remove('is-progress', 'is-success', 'is-error');
    if (type) status.classList.add('is-' + type);
}
function getExportPreviewText() {
    var text = exportRawText || '';
    var redactIps = document.getElementById('export-redact-ips');
    var redactHostnames = document.getElementById('export-redact-hostnames');
    var redactCustomers = document.getElementById('export-redact-customers');
    if (redactIps && redactIps.checked) {
        text = text.replace(/\b(?:\d{1,3}\.){3}\d{1,3}\b/g, '[redacted-ip]');
        text = text.replace(/\b[0-9a-fA-F]{1,4}:[0-9a-fA-F:]*:[0-9a-fA-F]{0,4}\b/g, function(match) {
            var colonCount = (match.match(/:/g) || []).length;
            if (match.indexOf('::') === -1 && colonCount < 3) return match;
            return '[redacted-ip]';
        });
    }
    if (redactHostnames && redactHostnames.checked) {
        text = text.replace(/\b[a-zA-Z0-9][a-zA-Z0-9-]*(?:\.[a-zA-Z0-9][a-zA-Z0-9-]*)+\b/g, function(match) {
            if (match === '[redacted-ip]') return match;
            if (/^\d+(?:\.\d+)+$/.test(match)) return match;
            return '[redacted-hostname]';
        });
    }
    if (redactCustomers && redactCustomers.checked) {
        text = text.replace(/\b(?:customer|account|contract|subscriber|kunden(?:nummer)?|kundennr\.?|client|ref(?:erence)?)\s*(?:id|number|no\.?|ref|nr\.?)?\s*[:#-]?\s*[A-Z0-9][A-Z0-9._/ -]{2,}\b/gi, '[redacted-customer]');
        text = text.replace(/\bK-\d{3,}\b/g, '[redacted-customer]');
        text = text.replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi, '[redacted-customer]');
    }
    return text;
}
function refreshExportPreview() {
    var textarea = document.getElementById('export-text');
    if (!textarea) return;
    textarea.value = getExportPreviewText();
    updateExportSize();
}
function updateExportSize() {
    var indicator = document.getElementById('export-size-indicator');
    var textarea = document.getElementById('export-text');
    if (!indicator || !textarea) return;
    var chars = textarea.value.length;
    var approxTokens = Math.max(1, Math.ceil(chars / 4));
    indicator.textContent = chars.toLocaleString() + ' ' + (T.export_size_characters || 'characters') + ' · ~' + approxTokens.toLocaleString() + ' ' + (T.export_size_tokens || 'tokens');
}
function openBqmSetupModal() {
    window.DOCSightModal.open('bqm-setup-modal');
}
function closeBqmSetupModal() {
    window.DOCSightModal.close('bqm-setup-modal');
}
var reportGenerationId = 0;
var reportScope = null;
function openReportModal(scope) {
    reportScope = scope === undefined ? null : scope;
    resetReportModalState();
    renderReportScope();
    window.DOCSightModal.open('report-modal');
    syncComparisonReportState();
    // Close sidebar on mobile
    var sb = document.getElementById('sidebar');
    if (sb) {
        sb.classList.remove('mobile-open');
        var bd = document.getElementById('sidebar-backdrop');
        if (bd) bd.classList.remove('active');
    }
}
function closeReportModal() {
    window.DOCSightModal.close('report-modal');
    resetReportModalState();
    reportScope = null;
}
function isValidReportScope(scope) {
    return !!(scope && scope.window && typeof scope.window.from === 'string' && scope.window.from &&
        typeof scope.window.to === 'string' && scope.window.to);
}
function formatReportScopeDate(value) {
    try {
        var locale = document.documentElement.lang || undefined;
        return new Intl.DateTimeFormat(locale, {dateStyle: 'medium', timeStyle: 'short'}).format(new Date(value));
    } catch (error) {
        return value;
    }
}
function reportReadinessStatus(status) {
    var labels = {
        present: T.report_status_present || 'Ready',
        stale: T.report_status_stale || 'Stale',
        missing: T.report_status_missing || 'Missing',
        optional: T.report_status_optional || 'Optional',
        not_applicable: T.report_status_not_applicable || 'Not applicable',
        unavailable: T.report_status_unavailable || 'Unavailable'
    };
    return labels[status] || labels.missing;
}
function renderReportReadiness() {
    var summaryRoot = document.getElementById('report-readiness-summary');
    var list = document.getElementById('report-readiness-list');
    if (!summaryRoot || !list) return;
    summaryRoot.textContent = '';
    list.textContent = '';
    var summary = reportScope && reportScope.summary || {};
    ['present', 'stale', 'missing', 'optional', 'not_applicable', 'unavailable'].forEach(function(status) {
        if (!Object.prototype.hasOwnProperty.call(summary, status)) return;
        var item = document.createElement('span');
        item.className = 'report-readiness-count report-status-' + status;
        item.textContent = reportReadinessStatus(status) + ': ' + summary[status];
        summaryRoot.appendChild(item);
    });
    var items = reportScope && reportScope.items || [];
    items.forEach(function(item) {
        var status = item.status || 'missing';
        var row = document.createElement('li');
        row.className = 'report-readiness-row report-status-' + status;
        var label = document.createElement('span');
        label.textContent = T[item.label_key] || item.label_key || item.key || '';
        var statusLabel = document.createElement('strong');
        statusLabel.textContent = reportReadinessStatus(status);
        row.appendChild(label);
        row.appendChild(statusLabel);
        list.appendChild(row);
    });
}
function renderReportScope() {
    var fixedScope = document.getElementById('report-fixed-scope');
    var daysField = document.getElementById('report-days-field');
    var days = document.getElementById('report-days');
    var isFixed = !!reportScope;
    fixedScope.hidden = !isFixed;
    daysField.hidden = isFixed;
    days.disabled = isFixed;
    if (!isFixed) return;
    if (!isValidReportScope(reportScope)) {
        setReportBuilderStatus(T.report_fixed_scope_invalid || 'The selected problem window is incomplete. Return to Evidence Journey and rebuild the checklist.', 'error');
        document.getElementById('report-generate-btn').disabled = true;
        return;
    }
    var windowData = reportScope && reportScope.window;
    document.getElementById('report-period-label').textContent = windowData.label || '';
    var from = document.getElementById('report-period-from');
    var to = document.getElementById('report-period-to');
    from.dateTime = windowData.from;
    to.dateTime = windowData.to;
    from.textContent = formatReportScopeDate(windowData.from);
    to.textContent = formatReportScopeDate(windowData.to);
    renderReportReadiness();
}
function changeReportProblemWindow() {
    var scope = reportScope;
    reportGenerationId += 1;
    window.DOCSightModal.close('report-modal');
    resetReportModalState();
    reportScope = null;
    if (scope && typeof scope.changeWindow === 'function') scope.changeWindow();
}
function resetReportModalState() {
    reportGenerationId += 1;
    ['report-name', 'report-number', 'report-address'].forEach(function(fieldId) {
        var field = document.getElementById(fieldId);
        if (field) field.value = field.defaultValue;
    });
    document.getElementById('report-step1').style.display = '';
    document.getElementById('report-step2').style.display = 'none';
    var generateBtn = document.getElementById('report-generate-btn');
    generateBtn.style.display = '';
    generateBtn.disabled = false;
    generateBtn.textContent = '\u270E ' + (T.report_build_package || 'Build evidence package');
    document.getElementById('report-copy-btn').style.display = 'none';
    document.getElementById('report-pdf-btn').style.display = 'none';
    // Reset BNetzA complaint source
    var bnetzIdField = document.getElementById('report-bnetz-id');
    if (bnetzIdField) bnetzIdField.value = '';
    var complaintText = document.getElementById('report-complaint-text');
    if (complaintText) complaintText.value = '';
    var days = document.getElementById('report-days');
    var daysField = document.getElementById('report-days-field');
    var fixedScope = document.getElementById('report-fixed-scope');
    if (days) days.disabled = false;
    if (daysField) daysField.hidden = false;
    if (fixedScope) fixedScope.hidden = true;
    setReportBuilderStatus('');
}
function setReportBuilderStatus(message, type) {
    var status = document.getElementById('report-builder-status');
    if (!status) return;
    status.textContent = message || '';
    status.classList.remove('is-success', 'is-error', 'is-progress');
    if (type) {
        status.classList.add('is-' + type);
    }
}
function syncComparisonReportState() {
    var toggle = document.getElementById('report-include-comparison');
    var note = document.getElementById('report-comparison-note');
    if (!toggle || !note) return;
    var hasComparison = !!window.__docsightComparisonResult;
    toggle.disabled = !hasComparison;
    if (!hasComparison) {
        toggle.checked = false;
    }
    note.textContent = hasComparison
        ? (T.report_include_comparison_ready || 'The current comparison results will be attached to the complaint and PDF report.')
        : (T.report_include_comparison_hint || 'Run a comparison first to attach the current before/after evidence.');
}
function reportResponseMatchesScope(data) {
    if (!reportScope) return true;
    return !!(data && data.window &&
        data.window.from === reportScope.window.from &&
        data.window.to === reportScope.window.to);
}
function buildReportRequestParams() {
    var params = new URLSearchParams();
    if (reportScope) {
        if (!isValidReportScope(reportScope)) {
            throw new Error(T.report_fixed_scope_invalid || 'The selected problem window is incomplete. Return to Evidence Journey and rebuild the checklist.');
        }
        params.set('from', reportScope.window.from);
        params.set('to', reportScope.window.to);
    } else {
        params.set('days', document.getElementById('report-days').value);
    }
    params.set('lang', document.getElementById('report-lang').value);
    params.set('name', document.getElementById('report-name').value);
    params.set('number', document.getElementById('report-number').value);
    params.set('address', document.getElementById('report-address').value);
    var includeBnetz = document.getElementById('report-include-bnetz');
    if (includeBnetz && includeBnetz.checked) params.set('include_bnetz', 'true');
    var bnetzIdField = document.getElementById('report-bnetz-id');
    if (bnetzIdField && bnetzIdField.value) {
        params.set('bnetz_id', bnetzIdField.value);
    }
    var includeComparison = document.getElementById('report-include-comparison');
    if (includeComparison && includeComparison.checked && window.__docsightComparisonResult) {
        var cmp = window.__docsightComparisonResult;
        params.set('comparison_from_a', cmp.period_a.from);
        params.set('comparison_to_a', cmp.period_a.to);
        params.set('comparison_from_b', cmp.period_b.from);
        params.set('comparison_to_b', cmp.period_b.to);
    }
    return params;
}
function generateComplaint() {
    var btn = document.getElementById('report-generate-btn');
    btn.disabled = true;
    btn.textContent = '...';
    setReportBuilderStatus(T.report_builder_building || 'Building evidence package...', 'progress');
    var generationId = reportGenerationId;
    var params;
    try {
        params = buildReportRequestParams();
    } catch (error) {
        btn.disabled = false;
        btn.textContent = '\u270E ' + (T.report_build_package || 'Build evidence package');
        setReportBuilderStatus(error.message, 'error');
        return;
    }
    fetch(docsightUrl('/api/complaint?' + params.toString()))
        .then(function(r) {
            return r.json().then(function(data) {
                if (!r.ok || data.error) {
                    throw new Error(data.error || (T.report_builder_error || 'Report generation failed.'));
                }
                return data;
            });
        })
        .then(function(data) {
            if (generationId !== reportGenerationId) return;
            if (!reportResponseMatchesScope(data)) {
                throw new Error(T.report_window_mismatch || 'The server returned a different problem window. Choose Change problem window and rebuild the checklist before trying again.');
            }
            document.getElementById('report-complaint-text').value = data.text;
            document.getElementById('report-step1').style.display = 'none';
            document.getElementById('report-step2').style.display = 'block';
            document.getElementById('report-generate-btn').style.display = 'none';
            document.getElementById('report-copy-btn').style.display = '';
            document.getElementById('report-pdf-btn').style.display = '';
            setReportBuilderStatus(T.report_builder_ready || 'Evidence package ready. Review the letter text, then copy it or download the PDF package.', 'success');
        })
        .catch(function(e) {
            if (generationId !== reportGenerationId) return;
            var message = e && e.message ? e.message : (T.report_builder_error || 'Report generation failed. Try a different report period or verify that monitoring data exists.');
            setReportBuilderStatus(message, 'error');
            showToast(message, 'error');
        })
        .finally(function() {
            if (generationId !== reportGenerationId) return;
            btn.disabled = false;
            btn.textContent = '\u270E ' + (T.report_build_package || 'Build evidence package');
        });
}
function generateBnetzComplaint(bnetzId) {
    openReportModal();
    var bnetzIdField = document.getElementById('report-bnetz-id');
    if (bnetzIdField) bnetzIdField.value = bnetzId;
    var checkbox = document.getElementById('report-include-bnetz');
    if (checkbox) checkbox.checked = true;
}
function copyComplaint() {
    var textarea = document.getElementById('report-complaint-text');
    var btn = document.getElementById('report-copy-btn');
    textarea.select();
    textarea.setSelectionRange(0, textarea.value.length);
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(textarea.value).then(function() {
            var orig = btn.innerHTML;
            btn.innerHTML = '&#10003; ' + (T.copied || 'Copied!');
            setReportBuilderStatus(T.report_builder_copied || 'Letter text copied. Attach the PDF package when you contact your ISP.', 'success');
            setTimeout(function() { btn.innerHTML = orig; }, 2000);
        });
    } else {
        document.execCommand('copy');
    }
}
function downloadReport() {
    var params = buildReportRequestParams();
    window.location.href = docsightUrl('/api/report?' + params.toString());
}
function copyExport() {
    var textarea = document.getElementById('export-text');
    var btn = document.getElementById('export-copy-btn');
    var text = textarea.value;
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function() {
            btn.textContent = T.copied || 'Copied!';
            setExportStatus(T.export_copied || 'Export copied. Review the destination before pasting sensitive diagnostics.', 'success');
            setTimeout(function() { btn.textContent = T.export_copy || 'Copy export'; }, 2000);
        }).catch(function() {
            fallbackCopy(textarea, btn, T);
        });
    } else {
        fallbackCopy(textarea, btn, T);
    }
}
function fallbackCopy(textarea, btn, T) {
    try {
        textarea.select();
        textarea.setSelectionRange(0, textarea.value.length);
        document.execCommand('copy');
        btn.textContent = T.copied || 'Copied!';
        setExportStatus(T.export_copied || 'Export copied. Review the destination before pasting sensitive diagnostics.', 'success');
        setTimeout(function() { btn.textContent = T.export_copy || 'Copy export'; }, 2000);
    } catch(e) {
        btn.textContent = T.copy_fallback || 'Select All + Ctrl+C';
        setExportStatus(T.export_copy_error || 'Could not copy automatically. Select the text and copy it manually.', 'error');
        setTimeout(function() { btn.textContent = T.export_copy || 'Copy export'; }, 3000);
    }
}
function downloadExportMarkdown() {
    var text = document.getElementById('export-text').value || '';
    var blob = new Blob([text], { type: 'text/markdown;charset=utf-8' });
    var url = URL.createObjectURL(blob);
    var link = document.createElement('a');
    link.href = url;
    link.download = 'docsight-ai-export.md';
    document.body.appendChild(link);
    link.click();
    link.remove();
    setExportStatus(T.export_download_ready || 'Download ready. Review the file before sharing it.', 'success');
    setTimeout(function() { URL.revokeObjectURL(url); }, 1000);
}
function openSpeedtestSetupModal() {
    window.DOCSightModal.open('speedtest-setup-modal');
}
function closeSpeedtestSetupModal() {
    window.DOCSightModal.close('speedtest-setup-modal');
}
function setSetupStatus(statusId, message, type) {
    var status = document.getElementById(statusId);
    if (!status) return;
    status.textContent = message || '';
    status.classList.remove('is-success', 'is-error', 'is-progress');
    if (type) status.classList.add('is-' + type);
}
function copySetupSnippet(sourceId, statusId) {
    var source = document.getElementById(sourceId);
    var text = source ? source.textContent.trim() : '';
    var copied = (T.setup_copied || 'Copied. Paste it into your setup notes or terminal when ready.');
    var copyError = (T.setup_copy_error || 'Could not copy automatically. Select the snippet and copy it manually.');
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function() {
            setSetupStatus(statusId, copied, 'success');
        }).catch(function() {
            setSetupStatus(statusId, copyError, 'error');
        });
    } else {
        setSetupStatus(statusId, copyError, 'error');
    }
}
function validateSetupGuidance(statusId, integration) {
    var messages = {
        speedtest: T.speedtest_setup_validation_path || 'Speedtest can be tested in Speedtest settings after the base URL and API token are saved. DOCSight uses the saved credentials for the live connection test.',
        bqm: T.bqm_setup_validation_path || 'BQM can be validated in BQM settings after the share URL is saved. DOCSight checks the saved share URL before importing graphs.',
        smokeping: T.smokeping_setup_validation_path || 'SmokePing validation depends on the saved base URL and target in SmokePing settings. Save those values first, then refresh this view to confirm live data.'
    };
    setSetupStatus(statusId, messages[integration] || (T.setup_guidance_ready || 'Open Settings, save the integration details, then use the settings test or refresh this view to confirm live data.'), 'progress');
}
