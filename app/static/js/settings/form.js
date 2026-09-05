'use strict';
DOCSightSettings.form = function({state, showsSaveFooter}) {
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
var SECRET_FIELDS = ['modem_password', 'mqtt_password', 'admin_password', 'speedtest_tracker_token', 'notify_webhook_token', 'notify_apprise_key', 'notify_apprise_token', 'notify_pwa_push_vapid_private_key']
    .concat(typeof MODULE_SECRET_FIELDS !== 'undefined' ? MODULE_SECRET_FIELDS : []);
var SAVED_SECRET_FIELDS = typeof SAVED_MODULE_SECRET_FIELDS !== 'undefined'
    ? SAVED_MODULE_SECRET_FIELDS
    : [];

function _isConfigSecretField(inp) {
    return !!(
        inp &&
        inp.name &&
        inp.tagName === 'INPUT' &&
        (
            SECRET_FIELDS.indexOf(inp.name) !== -1 ||
            inp.dataset.configSecret === 'true' ||
            _isSavedSecretField(inp)
        )
    );
}

function getFormData() {
    var form = document.getElementById('settings-form');
    var data = {};
    form.querySelectorAll('input:not(#theme-toggle-appearance):not(#isp_other_input):not(.notify-toggle):not(.notify-cooldown-input):not(.module-toggle-input), select:not(#isp_select), textarea').forEach(function(inp) {
        if (inp.type === 'checkbox') {
            data[inp.name] = inp.checked ? inp.value : 'false';
            return;
        }
        if (inp.type === 'hidden' && data[inp.name] !== undefined) return;
        if (_isConfigSecretField(inp)) {
            if (_isSavedSecretField(inp) && !inp.dataset.userEditedSecret) {
                data[inp.name] = MASK;
            } else {
                data[inp.name] = inp.value || MASK;
            }
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
    data.theme = document.documentElement.getAttribute('data-theme') || 'dark';
    var cooldowns = {};
    document.querySelectorAll('.notify-event-row').forEach(function(row) {
        var eventKey = row.getAttribute('data-event');
        var severity = row.getAttribute('data-severity') || '';
        var key = severity ? eventKey + ':' + severity : eventKey;
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

function _isSavedSecretField(el) {
    return !!(
        el &&
        el.name &&
        el.tagName === 'INPUT' &&
        el.type === 'password' &&
        (
            el.dataset.savedSecret === 'true' ||
            SAVED_SECRET_FIELDS.indexOf(el.name) !== -1
        )
    );
}

function _shouldTreatSavedSecretEventAsUserEdit(e) {
    var target = e && e.target;
    return !!(
        e &&
        e.isTrusted &&
        _isSavedSecretField(target) &&
        document.activeElement === target
    );
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

var baseline = [];
var failed = false;
var secretVersion = 0;
var queue = Promise.resolve();
var pending = 0;
var confirmed = {language: currentLang, timezone: currentTz};
var identities = new WeakMap();
var occurrences = new Map();

function isInstantControl(el) {
    if (el.id === 'theme-toggle-appearance') return false;
    if (el.id === 'font_family') return true;
    if (el.type === 'hidden') {
        return Array.from(el.form.elements).some(function(other) {
            return other !== el && other.name === el.name && other.type === 'checkbox' && isInstantControl(other);
        });
    }
    return el.matches('label.toggle input[type="checkbox"], label.switch input[type="checkbox"], .module-toggle-input, .notify-toggle, .notify-cooldown-input');
}

function capture() {
    var form = document.getElementById('settings-form');
    return Array.from(form.elements).filter(function(el) {
        return (el.name || el.matches('.notify-toggle, .notify-cooldown-input')) && !['submit', 'button', 'file'].includes(el.type);
    }).map(function(el) {
        var row = el.closest('.notify-event-row');
        var name = el.name || JSON.stringify([row.dataset.event, row.dataset.severity || '', el.matches('.notify-toggle') ? 'enabled' : 'cooldown']);
        var id = el.getAttribute('data-module-id') || el.id;
        if (!identities.has(el)) {
            var group = JSON.stringify([name, id, el.type]);
            var index = occurrences.get(group) || 0;
            identities.set(el, index);
            occurrences.set(group, index + 1);
        }
        var secret = _isConfigSecretField(el);
        var value;
        if (!secret) {
            if (el.type === 'checkbox' || el.type === 'radio') value = el.checked ? '1' : '0';
            else if (el.multiple) value = Array.from(el.selectedOptions, function(opt) { return opt.value; }).sort();
            else value = el.value || '';
        }
        return state.record({name: name, id: id, type: el.type, index: identities.get(el),
            owner: el.matches('.module-toggle-input') ? 'module' : 'config',
            instant: isInstantControl(el), value: value, secret: secret,
            secretEditVersion: el.dataset.secretEditVersion});
    });
}

function syncSaveFooter() {
    var current = capture();
    var footer = document.getElementById('save-footer');
    var visible = showsSaveFooter() && state.dirty(current, baseline) && (failed || state.dirty(current, baseline, true));
    footer.classList.toggle('visible', visible);
    footer.toggleAttribute('aria-hidden', !visible);
    if (!visible) footer.setAttribute('aria-hidden', 'true');
    footer.toggleAttribute('inert', !visible);
}

function acknowledgeSecrets(sent, data) {
    var fields = Array.from(document.getElementById('settings-form').elements);
    sent.filter(function(record) { return record.secretEditVersion !== undefined; }).forEach(function(record) {
        var el = fields.find(function(field) {
            return field.name === record.name && (field.getAttribute('data-module-id') || field.id) === record.id && identities.get(field) === JSON.parse(record.key)[3];
        });
        if (!el || !data[record.name] || data[record.name] === MASK) return;
        el.dataset.savedSecret = 'true';
        if (Number(el.dataset.secretEditVersion || 0) === record.secretEditVersion) {
            el.value = '';
            delete el.dataset.userEditedSecret;
        }
    });
}

function post(url, data) {
    return fetch(docsightUrl(url), {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data)
    }).then(function(response) {
        return response.json().then(function(result) {
            if (!response.ok || !result.success) throw new Error(T.save_failed || 'Save failed');
            return result;
        });
    });
}

function saveAll(options) {
    // Capture only when this FIFO job starts, including edits made while queued.
    var sent = capture();
    var data = getFormData();
    var modules = sent.filter(function(record) {
        return record.owner === 'module' && state.dirty([record], baseline.filter(function(saved) { return saved.key === record.key; }));
    }).map(function(record) { return {id: record.id, enabled: record.value === '1'}; });
    return post('/api/config', data).then(function() {
        baseline = state.acknowledge(baseline, sent, 'config');
        confirmed = {language: data.language, timezone: data.timezone};
        acknowledgeSecrets(sent, data);
        syncSaveFooter();
        return modules.length ? post('/api/modules/batch', {modules: modules}) : {};
    }).then(function(result) {
        baseline = state.acknowledge(baseline, sent, 'module');
        if (result.restart_required) {
            var banner = document.getElementById('module-restart-banner');
            if (banner) {
                banner.style.display = 'flex';
                if (typeof lucide !== 'undefined') lucide.createIcons({nodes: [banner]});
            }
        }
        failed = false;
        syncSaveFooter();
        if (!options.instant) showToast(T.settings_saved || 'Settings saved', true);
        scheduleReload();
        return true;
    });
}

function scheduleReload() {
    if (confirmed.language === currentLang && confirmed.timezone === currentTz) return;
    setTimeout(function() {
        if (!pending && !state.dirty(capture(), baseline) &&
            document.getElementById('language').value === confirmed.language &&
            document.getElementById('timezone').value === confirmed.timezone) location.reload();
    }, 800);
}

function save(options) {
    pending++;
    queue = queue.catch(function() {}).then(function() {
        var error = document.getElementById('global-error');
        error.style.display = 'none';
        return saveAll(options || {}).catch(function() {
            error.textContent = T.save_failed || T.network_error || 'Save failed';
            error.style.display = 'block';
            failed = true;
            syncSaveFooter();
            return false;
        }).finally(function() { pending--; });
    });
    return queue;
}

function saveInstantly() {
    return save({instant: true});
}

function guardUnsaved() {
    if (!pending && !state.dirty(capture(), baseline)) return Promise.resolve(true);
    return docsightConfirm({
        title: T.unsaved_changes || 'Unsaved changes',
        message: T.unsaved_confirm || 'You have unsaved settings changes. Save them before continuing?',
        confirmText: T.save || 'Save',
        cancelText: T.cancel || 'Cancel'
    }).then(function(confirmed) {
        return confirmed ? save().then(function(ok) { return ok && !pending && !state.dirty(capture(), baseline); }) : false;
    });
}

function init() {
    var form = document.getElementById('settings-form');
    baseline = capture();
    function changed(e) {
        if (_isConfigSecretField(e.target) && (!_isSavedSecretField(e.target) || _shouldTreatSavedSecretEventAsUserEdit(e))) {
            e.target.dataset.userEditedSecret = 'true';
            e.target.dataset.secretEditVersion = String(++secretVersion);
        }
        syncSaveFooter();
    }
    form.addEventListener('input', changed);
    form.addEventListener('change', changed);
    form.addEventListener('submit', function(e) {
        e.preventDefault();
        save();
    });
    form.querySelectorAll('label.toggle input[type="checkbox"]:not(#theme-toggle-appearance):not(.module-toggle-input):not(.notify-toggle), label.switch input[type="checkbox"]').forEach(function(toggle) {
        toggle.addEventListener('change', saveInstantly);
    });
    form.querySelectorAll('.module-toggle-input').forEach(function(toggle) {
        toggle.addEventListener('change', function() {
            if (toggle.dataset.isThreshold === 'true' && toggle.checked) {
                form.querySelectorAll('.module-toggle-input[data-is-threshold="true"]').forEach(function(other) {
                    if (other !== toggle) other.checked = false;
                });
            }
            saveInstantly();
        });
    });
    window.addEventListener('beforeunload', function(e) {
        if (pending || state.dirty(capture(), baseline)) {
            e.preventDefault();
            e.returnValue = '';
        }
    });
    initTimezoneHint();
    syncSaveFooter();
}
return {init, getFormData, showToast, syncSaveFooter, saveInstantly, guardUnsaved};
};
