'use strict';
DOCSightSettings.backups = function({showToast}) {
/* ── Backup ── */
function downloadBackup() {
    var btn = document.getElementById('backup-download-btn');
    var el = document.getElementById('backup-download-result');
    btn.disabled = true;
    el.className = 'test-result test-loading';
    el.style.display = 'flex';
    el.textContent = '';
    var span = document.createElement('span');
    span.textContent = '\u23F3';
    el.appendChild(span);
    el.appendChild(document.createTextNode(' ' + (T.backup_creating || 'Creating backup...')));
    fetch(docsightUrl('/api/backup'), { method: 'POST' })
    .then(function(r) {
        if (!r.ok) return r.json().then(function(j) { throw new Error(j.error || 'Backup failed'); });
        var cd = r.headers.get('Content-Disposition') || '';
        var match = cd.match(/filename="?([^"]+)"?/);
        var fname = match ? match[1] : 'docsight_backup.tar.gz';
        return r.blob().then(function(blob) { return { blob: blob, fname: fname }; });
    })
    .then(function(res) {
        var a = document.createElement('a');
        a.href = URL.createObjectURL(res.blob);
        a.download = res.fname;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(a.href);
        el.textContent = '';
        el.className = 'test-result test-ok';
        var check = document.createElement('span');
        check.className = 'check-icon';
        check.textContent = '\u2713';
        el.appendChild(check);
        el.appendChild(document.createTextNode(' ' + (T.backup_success || 'Backup downloaded')));
        btn.disabled = false;
    })
    .catch(function(err) {
        el.textContent = '';
        el.className = 'test-result test-fail';
        var x = document.createElement('span');
        x.textContent = '\u2717';
        el.appendChild(x);
        el.appendChild(document.createTextNode(' ' + (err.message || T.network_error)));
        btn.disabled = false;
    });
}

function backupNow() {
    var el = document.getElementById('backup-now-result');
    el.className = 'test-result test-loading';
    el.style.display = 'flex';
    el.textContent = '';
    var span = document.createElement('span');
    span.textContent = '\u23F3';
    el.appendChild(span);
    el.appendChild(document.createTextNode(' ' + (T.backup_creating || 'Creating backup...')));
    fetch(docsightUrl('/api/backup/scheduled'), { method: 'POST' })
    .then(function(r) { return r.json(); })
    .then(function(res) {
        el.textContent = '';
        if (res.success) {
            el.className = 'test-result test-ok';
            var check = document.createElement('span');
            check.className = 'check-icon';
            check.textContent = '\u2713';
            el.appendChild(check);
            el.appendChild(document.createTextNode(' ' + (T.backup_saved || 'Backup saved') + ': ' + res.filename));
            loadBackupList();
        } else {
            el.className = 'test-result test-fail';
            var x = document.createElement('span');
            x.textContent = '\u2717';
            el.appendChild(x);
            el.appendChild(document.createTextNode(' ' + (res.error || T.save_failed || 'Failed')));
        }
    })
    .catch(function() {
        el.textContent = '';
        el.className = 'test-result test-fail';
        var x = document.createElement('span');
        x.textContent = '\u2717';
        el.appendChild(x);
        el.appendChild(document.createTextNode(' ' + (T.network_error || 'Network error')));
    });
}

function loadBackupList() {
    var el = document.getElementById('backup-list');
    if (!el) return;
    fetch(docsightUrl('/api/backup/list'))
    .then(function(r) { return r.json(); })
    .then(function(res) {
        var backups = Array.isArray(res) ? res : (res && Array.isArray(res.backups) ? res.backups : []);
        el.textContent = '';
        if (backups.length === 0) {
            var emptySpan = document.createElement('span');
            emptySpan.style.cssText = 'color:var(--muted);font-style:italic;';
            emptySpan.textContent = T.backup_none || 'No backups found';
            el.appendChild(emptySpan);
            return;
        }
        var table = document.createElement('table');
        table.style.cssText = 'width:100%;border-collapse:collapse;';
        var tbody = document.createElement('tbody');
        backups.forEach(function(b) {
            var sizeMB = (b.size / 1048576).toFixed(1);
            var date = b.modified ? new Date(b.modified).toLocaleString() : '';
            var tr = document.createElement('tr');
            tr.style.cssText = 'border-bottom:1px solid var(--card-border);';

            var td1 = document.createElement('td');
            td1.style.cssText = 'padding:6px 0;';
            var codeEl = document.createElement('code');
            codeEl.style.cssText = 'font-size:0.8em;';
            codeEl.textContent = b.filename;
            td1.appendChild(codeEl);
            tr.appendChild(td1);

            var td2 = document.createElement('td');
            td2.style.cssText = 'padding:6px 8px;color:var(--muted);font-size:0.8em;white-space:nowrap;';
            td2.textContent = date;
            tr.appendChild(td2);

            var td3 = document.createElement('td');
            td3.style.cssText = 'padding:6px 8px;color:var(--muted);font-size:0.8em;white-space:nowrap;';
            td3.textContent = sizeMB + ' MB';
            tr.appendChild(td3);

            var td4 = document.createElement('td');
            td4.style.cssText = 'padding:6px 0;text-align:right;';
            var delBtn = document.createElement('button');
            delBtn.type = 'button';
            delBtn.className = 'btn btn-secondary';
            delBtn.style.cssText = 'padding:2px 8px;font-size:0.75em;';
            var deleteLabel = ((T.backup_delete || T.bqm_delete || 'Delete backup') + ' ' + b.filename).trim();
            delBtn.setAttribute('data-filename', b.filename);
            delBtn.setAttribute('aria-label', deleteLabel);
            delBtn.setAttribute('title', deleteLabel);
            delBtn.addEventListener('click', function() { deleteBackup(this.getAttribute('data-filename')); });
            var icon = document.createElement('i');
            icon.setAttribute('data-lucide', 'trash-2');
            icon.setAttribute('aria-hidden', 'true');
            icon.style.cssText = 'width:12px;height:12px;';
            delBtn.appendChild(icon);
            td4.appendChild(delBtn);
            tr.appendChild(td4);

            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        el.appendChild(table);
        if (typeof lucide !== 'undefined') lucide.createIcons();
    })
    .catch(function() {
        el.textContent = '';
        var errSpan = document.createElement('span');
        errSpan.style.cssText = 'color:var(--error);';
        errSpan.textContent = T.network_error;
        el.appendChild(errSpan);
    });
}

function deleteBackup(filename) {
    docsightConfirm({
        title: T.delete || 'Delete',
        message: T.backup_delete_confirm || 'Delete this backup?',
        confirmText: T.delete || 'Delete',
        cancelText: T.cancel || 'Cancel',
        danger: true
    }).then(function(confirmed) {
        if (!confirmed) return null;
        return fetch(docsightUrl('/api/backup/' + encodeURIComponent(filename)), { method: 'DELETE' });
    })
    .then(function(r) { return r ? r.json() : null; })
    .then(function(res) {
        if (!res) return;
        if (res.success) {
            loadBackupList();
        } else {
            showToast(res.error || T.save_failed || 'Failed', false);
        }
    })
    .catch(function() { showToast(T.network_error || 'Network error', false); });
}

/* ── Directory Browser ── */
var _browsePath = '/backup';

function openBrowseModal(opener) {
    var modal = document.getElementById('browse-modal');
    _browsePath = document.getElementById('backup_path').value || '/backup';
    var selected = document.getElementById('browse-selected-path');
    var status = document.getElementById('browse-status');
    if (selected) selected.textContent = _browsePath;
    if (status) status.textContent = T.loading || 'Loading...';
    DOCSightModal.open(modal, {opener: opener || document.activeElement, labelledBy: 'browse-modal-title'});
    browseTo(_browsePath);
}

function closeBrowseModal() {
    DOCSightModal.close('browse-modal');
}

function selectBrowsePath() {
    document.getElementById('backup_path').value = _browsePath;
    document.getElementById('backup_path').dispatchEvent(new Event('input', {bubbles: true}));
    closeBrowseModal();
}

function browseTo(path) {
    _browsePath = path;
    var bc = document.getElementById('browse-breadcrumb');
    var dirs = document.getElementById('browse-dirs');
    var selected = document.getElementById('browse-selected-path');
    var status = document.getElementById('browse-status');
    bc.textContent = path;
    if (selected) selected.textContent = path;
    dirs.textContent = '';
    var loadingDiv = document.createElement('div');
    loadingDiv.style.cssText = 'padding:16px;color:var(--muted);text-align:center;';
    loadingDiv.textContent = '\u23F3 ' + (T.loading || 'Loading...');
    dirs.appendChild(loadingDiv);
    if (status) status.textContent = T.loading || 'Loading...';
    fetch(docsightUrl('/api/browse?path=' + encodeURIComponent(path)))
    .then(function(r) { return r.json(); })
    .then(function(res) {
        dirs.textContent = '';
        if (res.error) {
            var errDiv = document.createElement('div');
            errDiv.style.cssText = 'padding:16px;color:var(--error);';
            errDiv.textContent = res.error;
            dirs.appendChild(errDiv);
            if (status) status.textContent = res.error;
            return;
        }
        _browsePath = res.path;
        bc.textContent = res.path;
        if (selected) selected.textContent = res.path;

        if (res.parent) {
            var parentItem = _createBrowseItem('..', res.parent, 'corner-left-up', true);
            dirs.appendChild(parentItem);
        }
        if (res.directories.length === 0 && !res.parent) {
            var emptyDiv = document.createElement('div');
            emptyDiv.style.cssText = 'padding:16px;color:var(--muted);text-align:center;font-style:italic;';
            emptyDiv.textContent = T.backup_empty_dir || 'Empty directory';
            dirs.appendChild(emptyDiv);
        }
        res.directories.forEach(function(d) {
            var item = _createBrowseItem(d.name, d.path, 'folder', false);
            dirs.appendChild(item);
        });
        if (status) {
            status.textContent = res.directories.length
                ? res.directories.length + ' ' + (T.directories || 'directories')
                : (T.backup_empty_dir || 'Empty directory');
        }
        if (typeof lucide !== 'undefined') lucide.createIcons();
    })
    .catch(function() {
        dirs.textContent = '';
        var errDiv = document.createElement('div');
        errDiv.style.cssText = 'padding:16px;color:var(--error);';
        errDiv.textContent = T.network_error;
        dirs.appendChild(errDiv);
        if (status) status.textContent = T.network_error;
    });
}

function _createBrowseItem(label, targetPath, iconName, isMuted) {
    var div = document.createElement('div');
    div.className = 'browse-item';
    div.setAttribute('role', 'button');
    div.setAttribute('tabindex', '0');
    div.setAttribute('aria-label', label);
    div.style.cssText = 'padding:8px 12px;cursor:pointer;display:flex;align-items:center;gap:8px;border-radius:var(--radius-sm);';
    div.addEventListener('click', function() { browseTo(targetPath); });
    div.addEventListener('keydown', function(event) {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        event.preventDefault();
        browseTo(targetPath);
    });
    div.addEventListener('mouseenter', function() { this.style.background = 'var(--hover-bg)'; });
    div.addEventListener('mouseleave', function() { this.style.background = ''; });

    var icon = document.createElement('i');
    icon.setAttribute('data-lucide', iconName);
    icon.style.cssText = 'width:16px;height:16px;color:' + (isMuted ? 'var(--muted)' : 'var(--accent)') + ';';
    div.appendChild(icon);

    var span = document.createElement('span');
    span.textContent = label;
    if (isMuted) span.style.color = 'var(--muted)';
    div.appendChild(span);

    return div;
}

function init() {
    var checkbox = document.getElementById('backup_enabled');
    var settings = document.getElementById('backup-auto-settings');
    if (checkbox && settings) checkbox.addEventListener('change', function() {
        settings.style.opacity = checkbox.checked ? '1' : '0.5';
        settings.style.pointerEvents = checkbox.checked ? 'auto' : 'none';
    });
}
return {init, downloadBackup, backupNow, loadBackupList, openBrowseModal, closeBrowseModal, selectBrowsePath};
};
