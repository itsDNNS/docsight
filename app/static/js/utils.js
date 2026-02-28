/* ═══ DOCSight Utility Functions ═══ */

function escapeHtml(str) {
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
}

/* ── Export for LLM ── */
function exportForLLM() {
    var modal = document.getElementById('export-modal');
    var textarea = document.getElementById('export-text');
    var modeEl = document.querySelector('input[name="export-mode"]:checked');
    var mode = modeEl ? modeEl.value : 'full';
    textarea.value = T.export_no_data;
    modal.classList.add('open');
    fetch('/api/export?mode=' + mode)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.text) {
                textarea.value = data.text;
            } else if (data.error) {
                textarea.value = data.error;
            }
        })
        .catch(function() {
            textarea.value = 'Error loading export data.';
        });
}
function closeExportModal() {
    document.getElementById('export-modal').classList.remove('open');
}
function openBqmSetupModal() {
    document.getElementById('bqm-setup-modal').classList.add('open');
}
function closeBqmSetupModal() {
    document.getElementById('bqm-setup-modal').classList.remove('open');
}
function openReportModal() {
    document.getElementById('report-modal').classList.add('open');
    // Close sidebar on mobile
    var sb = document.getElementById('sidebar');
    if (sb) {
        sb.classList.remove('mobile-open');
        var bd = document.getElementById('sidebar-backdrop');
        if (bd) bd.classList.remove('active');
    }
}
function closeReportModal() {
    document.getElementById('report-modal').classList.remove('open');
    // Reset to step 1
    document.getElementById('report-step1').style.display = '';
    document.getElementById('report-step2').style.display = 'none';
    document.getElementById('report-generate-btn').style.display = '';
    document.getElementById('report-copy-btn').style.display = 'none';
    document.getElementById('report-pdf-btn').style.display = 'none';
    // Reset BNetzA complaint source
    var bnetzIdField = document.getElementById('report-bnetz-id');
    if (bnetzIdField) bnetzIdField.value = '';
}
function generateComplaint() {
    var days = document.getElementById('report-days').value;
    var lang = document.getElementById('report-lang').value;
    var name = encodeURIComponent(document.getElementById('report-name').value);
    var number = encodeURIComponent(document.getElementById('report-number').value);
    var address = encodeURIComponent(document.getElementById('report-address').value);
    var includeBnetz = document.getElementById('report-include-bnetz');
    var bnetzParam = (includeBnetz && includeBnetz.checked) ? '&include_bnetz=true' : '';
    var bnetzIdField = document.getElementById('report-bnetz-id');
    if (bnetzIdField && bnetzIdField.value) {
        bnetzParam = '&bnetz_id=' + bnetzIdField.value;
    }
    var btn = document.getElementById('report-generate-btn');
    btn.disabled = true;
    btn.textContent = '...';
    fetch('/api/complaint?days=' + days + '&lang=' + lang + '&name=' + name + '&number=' + number + '&address=' + address + bnetzParam)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            document.getElementById('report-complaint-text').value = data.text;
            document.getElementById('report-step1').style.display = 'none';
            document.getElementById('report-step2').style.display = 'block';
            document.getElementById('report-generate-btn').style.display = 'none';
            document.getElementById('report-copy-btn').style.display = '';
            document.getElementById('report-pdf-btn').style.display = '';
        })
        .catch(function(e) { alert('Error: ' + e); })
        .finally(function() { btn.disabled = false; btn.textContent = '\u270E Generate Letter'; });
}
function generateBnetzComplaint(bnetzId) {
    var bnetzIdField = document.getElementById('report-bnetz-id');
    if (bnetzIdField) bnetzIdField.value = bnetzId;
    var checkbox = document.getElementById('report-include-bnetz');
    if (checkbox) checkbox.checked = true;
    openReportModal();
}
function copyComplaint() {
    var textarea = document.getElementById('report-complaint-text');
    var btn = document.getElementById('report-copy-btn');
    textarea.select();
    textarea.setSelectionRange(0, textarea.value.length);
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(textarea.value).then(function() {
            var orig = btn.innerHTML;
            btn.innerHTML = '&#10003; Copied!';
            setTimeout(function() { btn.innerHTML = orig; }, 2000);
        });
    } else {
        document.execCommand('copy');
    }
}
function downloadReport() {
    var days = document.getElementById('report-days').value;
    var lang = document.getElementById('report-lang').value;
    window.location.href = '/api/report?days=' + days + '&lang=' + lang;
}
function copyExport() {
    var textarea = document.getElementById('export-text');
    var btn = document.getElementById('export-copy-btn');
    textarea.select();
    textarea.setSelectionRange(0, textarea.value.length);
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(textarea.value).then(function() {
            btn.textContent = T.copied;
            setTimeout(function() { btn.textContent = T.copy_clipboard; }, 2000);
        }).catch(function() {
            fallbackCopy(textarea, btn, T);
        });
    } else {
        fallbackCopy(textarea, btn, T);
    }
}
function fallbackCopy(textarea, btn, T) {
    try {
        document.execCommand('copy');
        btn.textContent = T.copied;
        setTimeout(function() { btn.textContent = T.copy_clipboard; }, 2000);
    } catch(e) {
        btn.textContent = 'Select All + Ctrl+C';
        setTimeout(function() { btn.textContent = T.copy_clipboard; }, 3000);
    }
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
