/* ═══ DOCSight Utility Functions ═══ */

function escapeHtml(str) {
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
}

/* ── Export for AI Analysis ── */
var exportRawText = '';
var exportLoadId = 0;
var exportObserverAttached = false;
function isExportModalOpen() {
    var modal = document.getElementById('export-modal');
    return !!(modal && (modal.classList.contains('open') || modal.getAttribute('data-modal-open') === 'true'));
}
function resetExportState() {
    exportLoadId += 1;
    exportRawText = '';
    var textarea = document.getElementById('export-text');
    if (textarea) textarea.value = '';
    updateExportSize();
    setExportStatus('');
}
function ensureExportModalObserver() {
    if (exportObserverAttached || typeof MutationObserver === 'undefined') return;
    var modal = document.getElementById('export-modal');
    if (!modal) return;
    exportObserverAttached = true;
    new MutationObserver(function() {
        if (!isExportModalOpen()) resetExportState();
    }).observe(modal, { attributes: true, attributeFilter: ['class', 'data-modal-open', 'style'] });
}
function exportForLLM() {
    ensureExportModalObserver();
    var textarea = document.getElementById('export-text');
    var modeEl = document.querySelector('input[name="export-mode"]:checked');
    var mode = modeEl ? modeEl.value : 'full';
    var loadId = ++exportLoadId;
    exportRawText = '';
    textarea.value = T.export_no_data;
    setExportStatus(T.export_loading || 'Loading export preview...', 'progress');
    updateExportSize();
    if (window.DOCSightModal) {
        window.DOCSightModal.open('export-modal');
    } else {
        document.getElementById('export-modal').classList.add('open');
    }
    fetch('/api/export?mode=' + encodeURIComponent(mode))
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
    if (window.DOCSightModal) {
        window.DOCSightModal.close('export-modal');
    } else {
        document.getElementById('export-modal').classList.remove('open');
    }
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
    document.getElementById('bqm-setup-modal').classList.add('open');
}
function closeBqmSetupModal() {
    document.getElementById('bqm-setup-modal').classList.remove('open');
}
var reportGenerationId = 0;
function openReportModal() {
    resetReportModalState();
    if (window.DOCSightModal) {
        window.DOCSightModal.open('report-modal');
    } else {
        document.getElementById('report-modal').classList.add('open');
    }
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
    if (window.DOCSightModal) {
        window.DOCSightModal.close('report-modal');
    } else {
        document.getElementById('report-modal').classList.remove('open');
    }
    resetReportModalState();
}
function resetReportModalState() {
    reportGenerationId += 1;
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
function generateComplaint() {
    var days = document.getElementById('report-days').value;
    var lang = document.getElementById('report-lang').value;
    var name = encodeURIComponent(document.getElementById('report-name').value);
    var number = encodeURIComponent(document.getElementById('report-number').value);
    var address = encodeURIComponent(document.getElementById('report-address').value);
    var includeBnetz = document.getElementById('report-include-bnetz');
    var bnetzParam = (includeBnetz && includeBnetz.checked) ? '&include_bnetz=true' : '';
    var comparisonParam = '';
    var bnetzIdField = document.getElementById('report-bnetz-id');
    if (bnetzIdField && bnetzIdField.value) {
        bnetzParam = '&bnetz_id=' + encodeURIComponent(bnetzIdField.value);
    }
    var includeComparison = document.getElementById('report-include-comparison');
    if (includeComparison && includeComparison.checked && window.__docsightComparisonResult) {
        var cmp = window.__docsightComparisonResult;
        comparisonParam =
            '&comparison_from_a=' + encodeURIComponent(cmp.period_a.from) +
            '&comparison_to_a=' + encodeURIComponent(cmp.period_a.to) +
            '&comparison_from_b=' + encodeURIComponent(cmp.period_b.from) +
            '&comparison_to_b=' + encodeURIComponent(cmp.period_b.to);
    }
    var btn = document.getElementById('report-generate-btn');
    btn.disabled = true;
    btn.textContent = '...';
    setReportBuilderStatus(T.report_builder_building || 'Building evidence package...', 'progress');
    var generationId = reportGenerationId;
    fetch('/api/complaint?days=' + days + '&lang=' + lang + '&name=' + name + '&number=' + number + '&address=' + address + bnetzParam + comparisonParam)
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
    var days = document.getElementById('report-days').value;
    var lang = document.getElementById('report-lang').value;
    var comparisonParam = '';
    var includeComparison = document.getElementById('report-include-comparison');
    if (includeComparison && includeComparison.checked && window.__docsightComparisonResult) {
        var cmp = window.__docsightComparisonResult;
        comparisonParam =
            '&comparison_from_a=' + encodeURIComponent(cmp.period_a.from) +
            '&comparison_to_a=' + encodeURIComponent(cmp.period_a.to) +
            '&comparison_from_b=' + encodeURIComponent(cmp.period_b.from) +
            '&comparison_to_b=' + encodeURIComponent(cmp.period_b.to);
    }
    window.location.href = '/api/report?days=' + days + '&lang=' + lang + comparisonParam;
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
function toggleCard(el) {
    el.classList.toggle('open');
}
function openSpeedtestSetupModal() {
    document.getElementById('speedtest-setup-modal').classList.add('open');
}
function closeSpeedtestSetupModal() {
    document.getElementById('speedtest-setup-modal').classList.remove('open');
}
