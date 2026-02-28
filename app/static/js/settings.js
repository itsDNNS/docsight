/* ═══════════════════════════════════════════════
   DOCSight – Settings JavaScript
   Extracted from inline + Mobile List→Detail
   ═══════════════════════════════════════════════ */

/* Globals set by template: T, SECTION_TITLES, serverOffsetMin, serverTz, currentLang, currentTz, savedCooldowns */

/* ── Section Controller ── */
function switchSection(id) {
    /* Desktop sidebar: update active link */
    document.querySelectorAll('.settings-nav-link').forEach(function(link) {
        link.classList.toggle('active', link.getAttribute('data-section') === id);
    });

    /* Panels: show selected */
    document.querySelectorAll('.settings-panel').forEach(function(panel) {
        panel.classList.remove('active');
    });
    var target = document.getElementById('panel-' + id);
    if (target) target.classList.add('active');

    /* Topbar title */
    document.getElementById('topbar-title').textContent = SECTION_TITLES[id] || id;

    /* Hide save footer on support panel */
    var saveFooter = document.getElementById('settings-save-footer');
    if (saveFooter) {
        saveFooter.style.display = (id === 'support' || id === 'modules') ? 'none' : '';
    }

    /* Auto-load data for certain panels */
    if (id === 'general') loadApiTokens();
    if (id === 'backup') loadBackupList();

    /* URL hash */
    history.replaceState(null, '', '#' + id);

    /* Mobile: switch to detail view */
    if (window.innerWidth < 768) {
        document.body.classList.add('mobile-detail-active');
    }
}

/* ── Mobile List → Detail ── */
function backToList() {
    document.body.classList.remove('mobile-detail-active');
    history.replaceState(null, '', location.pathname);
}

/* ── API Token Management ── */
function _tokenCell(text, style) {
    var td = document.createElement('td');
    td.style.cssText = style || 'padding:4px 8px;';
    td.textContent = text;
    return td;
}

function loadApiTokens() {
    var table = document.getElementById('api-tokens-table');
    var body = document.getElementById('api-tokens-body');
    var empty = document.getElementById('api-tokens-empty');
    if (!table || !body) return;
    fetch('/api/tokens').then(function(r) { return r.json(); }).then(function(data) {
        var tokens = (data.tokens || []).filter(function(t) { return !t.revoked; });
        while (body.firstChild) body.removeChild(body.firstChild);
        if (tokens.length === 0) {
            table.style.display = 'none';
            if (empty) empty.style.display = 'block';
            return;
        }
        table.style.display = 'table';
        if (empty) empty.style.display = 'none';
        tokens.forEach(function(tk) {
            var tr = document.createElement('tr');
            tr.appendChild(_tokenCell(tk.name, 'padding:4px 8px;'));
            var prefixTd = document.createElement('td');
            prefixTd.style.cssText = 'padding:4px 8px;';
            var code = document.createElement('code');
            code.textContent = tk.token_prefix + '...';
            prefixTd.appendChild(code);
            tr.appendChild(prefixTd);
            tr.appendChild(_tokenCell(tk.last_used_at || '\u2014', 'padding:4px 8px;'));
            var actionTd = document.createElement('td');
            actionTd.style.cssText = 'padding:4px 8px;';
            var btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'btn btn-sm';
            btn.style.cssText = 'font-size:0.8em;padding:2px 8px;';
            btn.textContent = T.api_token_revoke || 'Revoke';
            btn.setAttribute('data-token-id', tk.id);
            btn.setAttribute('data-token-name', tk.name);
            btn.addEventListener('click', function() {
                revokeToken(parseInt(this.getAttribute('data-token-id')), this.getAttribute('data-token-name'));
            });
            actionTd.appendChild(btn);
            tr.appendChild(actionTd);
            body.appendChild(tr);
        });
    }).catch(function() {});
}

function createApiToken() {
    var inp = document.getElementById('api-token-name');
    var name = (inp.value || '').trim();
    if (!name) { inp.focus(); return; }
    fetch('/api/tokens', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: name})
    }).then(function(r) { return r.json().then(function(d) { return {ok: r.ok, data: d}; }); })
    .then(function(res) {
        if (!res.ok) { showToast(res.data.error || 'Error', false); return; }
        inp.value = '';
        var banner = document.getElementById('api-token-created-banner');
        document.getElementById('api-token-plaintext').textContent = res.data.token;
        banner.style.display = 'block';
        loadApiTokens();
        if (typeof lucide !== 'undefined') lucide.createIcons();
    }).catch(function() { showToast('Error', false); });
}

function copyToken() {
    var text = document.getElementById('api-token-plaintext').textContent;
    navigator.clipboard.writeText(text).then(function() {
        showToast(T.api_token_copied || 'Token copied!', true);
    });
}

function revokeToken(id, name) {
    var msg = (T.api_token_revoke_confirm || 'Revoke token "{name}"?').replace('{name}', name);
    if (!confirm(msg)) return;
    fetch('/api/tokens/' + id, {method: 'DELETE'})
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.success) {
            showToast(T.api_token_revoked || 'Token revoked', true);
            document.getElementById('api-token-created-banner').style.display = 'none';
            loadApiTokens();
        } else {
            showToast(data.error || 'Error', false);
        }
    }).catch(function() { showToast('Error', false); });
}

/* ── Status Dots ── */
function updateStatusDots() {
    var dots = {
        notifications: 'notify_webhook_url',
        speedtest: 'speedtest_tracker_url',
        bqm: 'bqm_url',
        smokeping: 'smokeping_url',
        mqtt: 'mqtt_host'
    };
    for (var section in dots) {
        var el = document.getElementById(dots[section]);
        /* Desktop sidebar dot */
        var dot = document.getElementById('dot-' + section);
        if (el && dot) {
            dot.classList.toggle('visible', el.value.trim() !== '');
        }
        /* Mobile list dot */
        var mDot = document.getElementById('mdot-' + section);
        if (el && mDot) {
            mDot.classList.toggle('visible', el.value.trim() !== '');
        }
    }
    /* BNetzA dot: based on checkbox */
    var bnetzCheck = document.getElementById('bnetz_watch_enabled');
    var bnetzDot = document.getElementById('dot-bnetz');
    var mBnetzDot = document.getElementById('mdot-bnetz');
    if (bnetzCheck) {
        if (bnetzDot) bnetzDot.classList.toggle('visible', bnetzCheck.checked);
        if (mBnetzDot) mBnetzDot.classList.toggle('visible', bnetzCheck.checked);
    }
    /* Weather dot: based on checkbox */
    var weatherCheck = document.getElementById('weather_enabled');
    var weatherDot = document.getElementById('dot-weather');
    var mWeatherDot = document.getElementById('mdot-weather');
    if (weatherCheck) {
        if (weatherDot) weatherDot.classList.toggle('visible', weatherCheck.checked);
        if (mWeatherDot) mWeatherDot.classList.toggle('visible', weatherCheck.checked);
    }
}

/* ── Theme Toggle ── */
function initThemeToggle() {
    var themeCheck = document.getElementById('theme-check');
    var themeCheckMobile = document.getElementById('theme-check-mobile');

    function applyTheme(isDark) {
        var theme = isDark ? 'dark' : 'light';
        document.documentElement.setAttribute('data-theme', theme);
        localStorage.setItem('docsis-theme', theme);
        if (themeCheck) themeCheck.checked = isDark;
        if (themeCheckMobile) themeCheckMobile.checked = isDark;
    }

    if (themeCheck) {
        themeCheck.addEventListener('change', function() { applyTheme(themeCheck.checked); });
    }
    if (themeCheckMobile) {
        themeCheckMobile.addEventListener('change', function() { applyTheme(themeCheckMobile.checked); });
    }

    /* Restore saved theme */
    var saved = localStorage.getItem('docsis-theme');
    if (saved) applyTheme(saved === 'dark');
}

/* ── ISP Change ── */
function onIspChange() {
    var sel = document.getElementById('isp_select');
    var row = document.getElementById('isp-other-row');
    var icon = document.getElementById('isp-icon-preview');
    if (!sel) return;
    row.style.display = sel.value === '__other__' ? 'flex' : 'none';
    var isp = sel.value.toLowerCase();
    var iconMap = {
        'vodafone': '/static/img/providers/vodafone.svg',
        'telekom': '/static/img/providers/telekom.svg',
        'o2': '/static/img/providers/o2.svg'
    };
    if (sel.value && sel.value !== '__other__') {
        icon.src = iconMap[isp] || '/static/img/providers/generic.svg';
        icon.alt = sel.value;
        icon.style.display = 'block';
        icon.style.opacity = iconMap[isp] ? '1' : '0.7';
    } else {
        icon.style.display = 'none';
    }
}

/* ── Toast ── */
function showToast(msg, ok) {
    var el = document.getElementById('toast');
    el.textContent = msg;
    el.className = 'toast ' + (ok ? 'toast-ok' : 'toast-fail');
    el.style.display = 'block';
    setTimeout(function() { el.style.display = 'none'; }, 3000);
}

/* ── Form Data ── */
var MASK = '\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022';
var SECRET_FIELDS = ['modem_password', 'mqtt_password', 'admin_password', 'speedtest_tracker_token', 'notify_webhook_token'];

function escHtml(s) {
    var d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
}

function getFormData() {
    var form = document.getElementById('settings-form');
    var data = {};
    form.querySelectorAll('input:not(#theme-check):not(#theme-check-mobile):not(#isp_other_input):not(.notify-toggle):not(.notify-cooldown-input), select:not(#isp_select)').forEach(function(inp) {
        if (inp.type === 'checkbox') {
            data[inp.name] = inp.checked ? inp.value : 'false';
            return;
        }
        if (inp.type === 'hidden' && data[inp.name] !== undefined) return;
        if (SECRET_FIELDS.indexOf(inp.name) !== -1) {
            data[inp.name] = inp.value || MASK;
        } else {
            data[inp.name] = inp.value;
        }
    });
    var ispSel = document.getElementById('isp_select');
    if (ispSel.value === '__other__') {
        data.isp_name = document.getElementById('isp_other_input').value;
    } else {
        data.isp_name = ispSel.value;
    }
    var themeCheck = document.getElementById('theme-check');
    data.theme = themeCheck.checked ? 'dark' : 'light';
    var cooldowns = {};
    document.querySelectorAll('.notify-event-row').forEach(function(row) {
        var key = row.getAttribute('data-event');
        var toggle = row.querySelector('.notify-toggle');
        var inp = row.querySelector('.notify-cooldown-input');
        if (!toggle.checked) {
            cooldowns[key] = 0;
        } else if (inp.value.trim() !== '') {
            cooldowns[key] = parseInt(inp.value, 10) || 1;
        }
    });
    data.notify_cooldowns = JSON.stringify(cooldowns);
    return data;
}

/* ── Modem Test ── */
function testModem() {
    var el = document.getElementById('modem-test');
    el.className = 'test-result test-loading';
    el.style.display = 'flex';
    el.textContent = '';
    var span = document.createElement('span');
    span.textContent = '\u23F3';
    el.appendChild(span);
    el.appendChild(document.createTextNode(' ' + T.testing));
    var data = getFormData();
    fetch('/api/test-modem', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({modem_type: data.modem_type, modem_url: data.modem_url, modem_user: data.modem_user, modem_password: data.modem_password})
    })
    .then(function(r) { return r.json(); })
    .then(function(res) {
        el.textContent = '';
        if (res.success) {
            el.className = 'test-result test-ok';
            var check = document.createElement('span');
            check.className = 'check-icon';
            check.textContent = '\u2713';
            el.appendChild(check);
            el.appendChild(document.createTextNode(' ' + T.connected + ': ' + (res.model || 'OK')));
        } else {
            el.className = 'test-result test-fail';
            var x = document.createElement('span');
            x.textContent = '\u2717';
            el.appendChild(x);
            el.appendChild(document.createTextNode(' ' + T.error_prefix + ': ' + (res.error || T.unknown_error)));
        }
    })
    .catch(function() {
        el.textContent = '';
        el.className = 'test-result test-fail';
        var x = document.createElement('span');
        x.textContent = '\u2717';
        el.appendChild(x);
        el.appendChild(document.createTextNode(' ' + T.network_error));
    });
}

/* ── MQTT Test ── */
function testMqtt() {
    var el = document.getElementById('mqtt-test');
    el.className = 'test-result test-loading';
    el.style.display = 'flex';
    el.textContent = '';
    var span = document.createElement('span');
    span.textContent = '\u23F3';
    el.appendChild(span);
    el.appendChild(document.createTextNode(' ' + T.testing));
    var data = getFormData();
    fetch('/api/test-mqtt', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({mqtt_host: data.mqtt_host, mqtt_port: data.mqtt_port, mqtt_user: data.mqtt_user, mqtt_password: data.mqtt_password})
    })
    .then(function(r) { return r.json(); })
    .then(function(res) {
        el.textContent = '';
        if (res.success) {
            el.className = 'test-result test-ok';
            var check = document.createElement('span');
            check.className = 'check-icon';
            check.textContent = '\u2713';
            el.appendChild(check);
            el.appendChild(document.createTextNode(' ' + T.connected));
        } else {
            el.className = 'test-result test-fail';
            var x = document.createElement('span');
            x.textContent = '\u2717';
            el.appendChild(x);
            el.appendChild(document.createTextNode(' ' + T.error_prefix + ': ' + (res.error || T.unknown_error)));
        }
    })
    .catch(function() {
        el.textContent = '';
        el.className = 'test-result test-fail';
        var x = document.createElement('span');
        x.textContent = '\u2717';
        el.appendChild(x);
        el.appendChild(document.createTextNode(' ' + T.network_error));
    });
}

/* ── Notification Test ── */
function testNotifications() {
    var el = document.getElementById('notify-test');
    el.className = 'test-result test-loading';
    el.style.display = 'flex';
    el.textContent = '';
    var span = document.createElement('span');
    span.textContent = '\u23F3';
    el.appendChild(span);
    el.appendChild(document.createTextNode(' Sending test notification...'));
    fetch('/api/notifications/test', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: '{}'
    })
    .then(function(r) { return r.json(); })
    .then(function(res) {
        el.textContent = '';
        if (res.success) {
            el.className = 'test-result test-ok';
            var check = document.createElement('span');
            check.className = 'check-icon';
            check.textContent = '\u2713';
            el.appendChild(check);
            el.appendChild(document.createTextNode(' Test notification sent'));
        } else {
            el.className = 'test-result test-fail';
            var x = document.createElement('span');
            x.textContent = '\u2717';
            el.appendChild(x);
            el.appendChild(document.createTextNode(' ' + (res.error || 'Unknown error')));
        }
    })
    .catch(function() {
        el.textContent = '';
        el.className = 'test-result test-fail';
        var x = document.createElement('span');
        x.textContent = '\u2717';
        el.appendChild(x);
        el.appendChild(document.createTextNode(' ' + T.network_error));
    });
}

/* ── Demo Migration ── */
function migrateToLive() {
    var msg = T.demo_migrate_confirm || 'This will delete all demo data and switch to live mode. Your own entries will be kept. Continue?';
    if (!confirm(msg)) return;
    var el = document.getElementById('migrate-result');
    el.className = 'test-result test-loading';
    el.style.display = 'flex';
    el.textContent = '';
    var span = document.createElement('span');
    span.textContent = '\u23F3';
    el.appendChild(span);
    el.appendChild(document.createTextNode(' Migrating...'));
    fetch('/api/demo/migrate', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: '{}'
    })
    .then(function(r) { return r.json(); })
    .then(function(res) {
        el.textContent = '';
        if (res.success) {
            el.className = 'test-result test-ok';
            var check = document.createElement('span');
            check.className = 'check-icon';
            check.textContent = '\u2713';
            el.appendChild(check);
            el.appendChild(document.createTextNode(' ' + (T.demo_migrate_success || 'Migration complete')));
            setTimeout(function() { location.reload(); }, 1500);
        } else {
            el.className = 'test-result test-fail';
            var x = document.createElement('span');
            x.textContent = '\u2717';
            el.appendChild(x);
            el.appendChild(document.createTextNode(' ' + (res.error || 'Unknown error')));
        }
    })
    .catch(function() {
        el.textContent = '';
        el.className = 'test-result test-fail';
        var x = document.createElement('span');
        x.textContent = '\u2717';
        el.appendChild(x);
        el.appendChild(document.createTextNode(' ' + T.network_error));
    });
}

/* ── Submit ── */
function initFormSubmit() {
    document.getElementById('settings-form').addEventListener('submit', function(e) {
        e.preventDefault();
        var errEl = document.getElementById('global-error');
        errEl.style.display = 'none';
        var saveBtn = e.target.querySelector('button[type="submit"]');
        var data = getFormData();
        fetch('/api/config', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(data)
        })
        .then(function(r) { return r.json(); })
        .then(function(res) {
            if (res.success) {
                if (saveBtn) {
                    var orig = saveBtn.textContent;
                    saveBtn.textContent = '\u2713 ' + T.settings_saved;
                    saveBtn.style.background = 'var(--success, #10b981)';
                }
                var newLang = document.getElementById('language').value;
                var newTz = document.getElementById('timezone').value;
                if (newLang !== currentLang || newTz !== currentTz) {
                    setTimeout(function() { location.reload(); }, 800);
                } else if (saveBtn) {
                    setTimeout(function() { saveBtn.textContent = orig; saveBtn.style.background = ''; }, 2500);
                }
            } else {
                errEl.textContent = res.error || T.save_failed;
                errEl.style.display = 'block';
            }
        })
        .catch(function() {
            errEl.textContent = T.network_error;
            errEl.style.display = 'block';
        });
    });
}

/* ── Timezone Hint ── */
function initTimezoneHint() {
    if (typeof serverOffsetMin === 'undefined') return;
    var browserOffsetMin = -new Date().getTimezoneOffset();
    var diffMin = browserOffsetMin - serverOffsetMin;
    if (diffMin === 0) return;

    var inp = document.getElementById('snapshot_time');
    var hint = document.getElementById('snapshot-tz-hint');
    if (!inp || !hint) return;

    function updateTzHint() {
        var parts = inp.value.split(':');
        if (parts.length < 2) return;
        var h = parseInt(parts[0]), m = parseInt(parts[1]);
        var totalMin = h * 60 + m + diffMin;
        totalMin = ((totalMin % 1440) + 1440) % 1440;
        var lh = String(Math.floor(totalMin / 60)).padStart(2, '0');
        var lm = String(totalMin % 60).padStart(2, '0');
        hint.textContent = T.snapshot_hint + ' \u2014 ' + inp.value + ' ' + serverTz + ' = ' + lh + ':' + lm + ' ' + T.snapshot_your_time;
    }
    updateTzHint();
    inp.addEventListener('change', updateTzHint);
}

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
    fetch('/api/backup', { method: 'POST' })
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
    fetch('/api/backup/scheduled', { method: 'POST' })
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
            el.appendChild(document.createTextNode(' ' + (res.error || 'Failed')));
        }
    })
    .catch(function() {
        el.textContent = '';
        el.className = 'test-result test-fail';
        var x = document.createElement('span');
        x.textContent = '\u2717';
        el.appendChild(x);
        el.appendChild(document.createTextNode(' ' + T.network_error));
    });
}

function loadBackupList() {
    var el = document.getElementById('backup-list');
    if (!el) return;
    fetch('/api/backup/list')
    .then(function(r) { return r.json(); })
    .then(function(res) {
        el.textContent = '';
        if (!res.backups || res.backups.length === 0) {
            var emptySpan = document.createElement('span');
            emptySpan.style.cssText = 'color:var(--muted);font-style:italic;';
            emptySpan.textContent = T.backup_none || 'No backups found';
            el.appendChild(emptySpan);
            return;
        }
        var table = document.createElement('table');
        table.style.cssText = 'width:100%;border-collapse:collapse;';
        var tbody = document.createElement('tbody');
        res.backups.forEach(function(b) {
            var sizeMB = (b.size / 1048576).toFixed(1);
            var date = new Date(b.modified * 1000).toLocaleString();
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
            delBtn.setAttribute('data-filename', b.filename);
            delBtn.addEventListener('click', function() { deleteBackup(this.getAttribute('data-filename')); });
            var icon = document.createElement('i');
            icon.setAttribute('data-lucide', 'trash-2');
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
    if (!confirm(T.backup_delete_confirm || 'Delete this backup?')) return;
    fetch('/api/backup/' + encodeURIComponent(filename), { method: 'DELETE' })
    .then(function(r) { return r.json(); })
    .then(function(res) {
        if (res.success) {
            loadBackupList();
        } else {
            alert(res.error || 'Failed');
        }
    })
    .catch(function() { alert(T.network_error); });
}

/* ── Directory Browser ── */
var _browsePath = '/backup';

function openBrowseModal() {
    var modal = document.getElementById('browse-modal');
    modal.style.display = 'flex';
    _browsePath = document.getElementById('backup_path').value || '/backup';
    browseTo(_browsePath);
}

function closeBrowseModal() {
    document.getElementById('browse-modal').style.display = 'none';
}

function selectBrowsePath() {
    document.getElementById('backup_path').value = _browsePath;
    closeBrowseModal();
}

function browseTo(path) {
    _browsePath = path;
    var bc = document.getElementById('browse-breadcrumb');
    var dirs = document.getElementById('browse-dirs');
    bc.textContent = path;
    dirs.textContent = '';
    var loadingDiv = document.createElement('div');
    loadingDiv.style.cssText = 'padding:16px;color:var(--muted);text-align:center;';
    loadingDiv.textContent = '\u23F3 Loading...';
    dirs.appendChild(loadingDiv);
    fetch('/api/browse?path=' + encodeURIComponent(path))
    .then(function(r) { return r.json(); })
    .then(function(res) {
        dirs.textContent = '';
        if (res.error) {
            var errDiv = document.createElement('div');
            errDiv.style.cssText = 'padding:16px;color:var(--error);';
            errDiv.textContent = res.error;
            dirs.appendChild(errDiv);
            return;
        }
        _browsePath = res.path;
        bc.textContent = res.path;

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
        if (typeof lucide !== 'undefined') lucide.createIcons();
    })
    .catch(function() {
        dirs.textContent = '';
        var errDiv = document.createElement('div');
        errDiv.style.cssText = 'padding:16px;color:var(--error);';
        errDiv.textContent = T.network_error;
        dirs.appendChild(errDiv);
    });
}

function _createBrowseItem(label, targetPath, iconName, isMuted) {
    var div = document.createElement('div');
    div.className = 'browse-item';
    div.style.cssText = 'padding:8px 12px;cursor:pointer;display:flex;align-items:center;gap:8px;border-radius:var(--radius-sm);';
    div.addEventListener('click', function() { browseTo(targetPath); });
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

/* ── Username Field Toggle + Modem Defaults ── */
function toggleUsernameField() {
    var modemType = document.getElementById('modem_type');
    if (!modemType) return;

    var usernameField = document.getElementById('modem_user');
    var urlField = document.getElementById('modem_url');

    if (modemType.value === 'ultrahub7') {
        usernameField.disabled = true;
        usernameField.value = '';
        usernameField.placeholder = T.not_required || 'Not required for this modem';
        usernameField.style.opacity = '0.5';
        usernameField.style.cursor = 'not-allowed';
    } else {
        usernameField.disabled = false;
        usernameField.style.opacity = '1';
        usernameField.style.cursor = 'text';
        if (modemType.value === 'vodafone_station') {
            if (urlField && (!urlField.value || urlField.value === 'http://192.168.178.1')) {
                urlField.value = 'http://192.168.0.1';
            }
            if (!usernameField.value) usernameField.value = 'admin';
            usernameField.placeholder = 'admin';
        } else if (modemType.value === 'tc4400') {
            if (urlField && (!urlField.value || urlField.value === 'http://192.168.178.1')) {
                urlField.value = 'http://192.168.100.1';
            }
            if (!usernameField.value) usernameField.value = 'admin';
            usernameField.placeholder = 'admin';
        } else if (modemType.value === 'cm3500') {
            if (urlField && (!urlField.value || urlField.value === 'http://192.168.178.1')) {
                urlField.value = 'https://192.168.100.1';
            }
            if (!usernameField.value) usernameField.value = 'admin';
            usernameField.placeholder = 'admin';
        } else {
            usernameField.placeholder = 'admin';
        }
    }
}

/* ── Init ── */
document.addEventListener('DOMContentLoaded', function() {
    if (typeof lucide !== 'undefined') lucide.createIcons();

    initThemeToggle();
    initFormSubmit();
    initTimezoneHint();
    onIspChange();
    toggleUsernameField();
    updateStatusDots();

    /* Listen for input changes on integration fields to update dots */
    ['notify_webhook_url', 'speedtest_tracker_url', 'bqm_url', 'smokeping_url', 'mqtt_host'].forEach(function(id) {
        var el = document.getElementById(id);
        if (el) el.addEventListener('input', updateStatusDots);
    });
    var bnetzWatchCheck = document.getElementById('bnetz_watch_enabled');
    if (bnetzWatchCheck) bnetzWatchCheck.addEventListener('change', updateStatusDots);
    var weatherCheck = document.getElementById('weather_enabled');
    if (weatherCheck) weatherCheck.addEventListener('change', updateStatusDots);

    /* Modem type change */
    var modemType = document.getElementById('modem_type');
    if (modemType) modemType.addEventListener('change', toggleUsernameField);

    /* Backup toggle */
    var backupCb = document.getElementById('backup_enabled');
    var backupSettings = document.getElementById('backup-auto-settings');
    if (backupCb && backupSettings) {
        backupCb.addEventListener('change', function() {
            backupSettings.style.opacity = backupCb.checked ? '1' : '0.5';
            backupSettings.style.pointerEvents = backupCb.checked ? 'auto' : 'none';
        });
    }

    /* Populate per-event notification toggles + cooldown inputs */
    try {
        var saved = typeof savedCooldowns !== 'undefined' ? savedCooldowns : {};
        document.querySelectorAll('.notify-event-row').forEach(function(row) {
            var key = row.getAttribute('data-event');
            var toggle = row.querySelector('.notify-toggle');
            var inp = row.querySelector('.notify-cooldown-input');
            if (saved[key] !== undefined) {
                if (saved[key] === 0) {
                    toggle.checked = false;
                    inp.disabled = true;
                    inp.style.opacity = '0.4';
                } else {
                    inp.value = saved[key];
                }
            }
            toggle.addEventListener('change', function() {
                inp.disabled = !toggle.checked;
                inp.style.opacity = toggle.checked ? '1' : '0.4';
            });
        });
    } catch(e) {}

    /* Restore section from URL hash */
    var hash = location.hash.replace('#', '');
    if (hash && document.getElementById('panel-' + hash)) {
        switchSection(hash);
    }
});

/* ── Module Management ── */
function initModuleToggles() {
    document.querySelectorAll('.module-toggle-input').forEach(function(toggle) {
        toggle.addEventListener('change', function() {
            var moduleId = this.getAttribute('data-module-id');
            var action = this.checked ? 'enable' : 'disable';
            var toggleEl = this;

            fetch('/api/modules/' + moduleId + '/' + action, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
            })
            .then(function(r) { return r.json(); })
            .then(function(res) {
                if (res.success) {
                    showToast(T.settings_saved || 'Saved');
                    var banner = document.getElementById('module-restart-banner');
                    if (banner) {
                        banner.style.display = 'flex';
                        lucide.createIcons({nodes: [banner]});
                    }
                } else {
                    toggleEl.checked = !toggleEl.checked;
                    showToast(res.error || 'Error', true);
                }
            })
            .catch(function() {
                toggleEl.checked = !toggleEl.checked;
                showToast(T.network_error || 'Network error', true);
            });
        });
    });
}

document.addEventListener('DOMContentLoaded', initModuleToggles);
