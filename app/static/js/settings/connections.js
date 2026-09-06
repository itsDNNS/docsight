'use strict';
DOCSightSettings.connections = function({getFormData}) {
/* ── Connection Test Status Indicators ── */
function setConnectionTestStatus(boxId, labelId, state, text) {
    var box = document.getElementById(boxId);
    if (!box) return;
    box.hidden = false;
    box.classList.remove('testing', 'connected', 'disconnected');
    box.classList.add(state);
    var label = document.getElementById(labelId);
    if (label) label.textContent = text;
}

function setModemStatus(state, text) {
    setConnectionTestStatus('modem-status', 'modem-status-text', state, text);
}

function setMqttStatus(state, text) {
    setConnectionTestStatus('mqtt-status', 'mqtt-status-text', state, text);
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
        icon.src = docsightUrl(iconMap[isp] || '/static/img/providers/generic.svg');
        icon.alt = sel.value;
        icon.style.display = 'block';
        icon.style.opacity = iconMap[isp] ? '1' : '0.7';
    } else {
        icon.style.display = 'none';
    }
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
    setModemStatus('testing', T.testing);
    var data = getFormData();
    fetch(docsightUrl('/api/test-modem'), {
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
            setModemStatus('connected', T.connected + ': ' + (res.model || 'OK'));
        } else {
            el.className = 'test-result test-fail';
            var x = document.createElement('span');
            x.textContent = '\u2717';
            el.appendChild(x);
            el.appendChild(document.createTextNode(' ' + T.error_prefix + ': ' + (res.error || T.unknown_error)));
            setModemStatus('disconnected', T.error_prefix + ': ' + (res.error || T.unknown_error));
        }
    })
    .catch(function() {
        el.textContent = '';
        el.className = 'test-result test-fail';
        var x = document.createElement('span');
        x.textContent = '\u2717';
        el.appendChild(x);
        el.appendChild(document.createTextNode(' ' + T.network_error));
        setModemStatus('disconnected', T.network_error);
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
    setMqttStatus('testing', T.testing);
    var data = getFormData();
    fetch(docsightUrl('/api/test-mqtt'), {
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
            setMqttStatus('connected', T.connected);
        } else {
            el.className = 'test-result test-fail';
            var x = document.createElement('span');
            x.textContent = '\u2717';
            el.appendChild(x);
            el.appendChild(document.createTextNode(' ' + T.error_prefix + ': ' + (res.error || T.unknown_error)));
            setMqttStatus('disconnected', T.error_prefix + ': ' + (res.error || T.unknown_error));
        }
    })
    .catch(function() {
        el.textContent = '';
        el.className = 'test-result test-fail';
        var x = document.createElement('span');
        x.textContent = '\u2717';
        el.appendChild(x);
        el.appendChild(document.createTextNode(' ' + T.network_error));
        setMqttStatus('disconnected', T.network_error);
    });
}

/* ── Speedtest Tracker Test ── */
function testSpeedtest() {
    var el = document.getElementById('speedtest-test');
    el.className = 'test-result test-loading';
    el.style.display = 'flex';
    el.textContent = '';
    var span = document.createElement('span');
    span.textContent = '\u23F3';
    el.appendChild(span);
    el.appendChild(document.createTextNode(' ' + T.testing));
    var data = getFormData();
    fetch(docsightUrl('/api/test-speedtest'), {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            speedtest_tracker_url: data.speedtest_tracker_url,
            speedtest_tracker_token: data.speedtest_tracker_token,
            speedtest_tls_insecure: data.speedtest_tls_insecure
        })
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
            if (res.results > 0) {
                el.appendChild(document.createTextNode(' ' + T.connected + ': ' + res.latest.download + ' \u2193 / ' + res.latest.upload + ' \u2191 / ' + res.latest.ping));
            } else {
                el.appendChild(document.createTextNode(' ' + T.connected + ' (' + (T.speedtest_no_results || 'no results yet') + ')'));
            }
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

/* ── Speedtest Cache Clear ── */
function clearSpeedtestCache(btn) {
    var message = T.clear_cache_confirm || 'Clear all cached speedtest results? They will be re-synced on the next poll cycle.';
    docsightConfirm({
        title: T['docsight.speedtest.clear_cache'] || 'Clear Cache',
        message: message,
        confirmText: T['docsight.speedtest.clear_cache'] || 'Clear Cache',
        cancelText: T.cancel || 'Cancel',
        danger: true
    }).then(function(confirmed) {
        if (!confirmed) return null;
        btn.disabled = true;
        return fetch(docsightUrl('/api/speedtest/cache'), { method: 'DELETE' });
    })
        .then(function(r) { return r ? r.json() : null; })
        .then(function(res) {
            if (!res) return;
            btn.disabled = false;
            if (res.success) {
                var count = res.cleared || 0;
                btn.textContent = '\u2713 ' + count + ' ' + (T.cleared || 'cleared');
                setTimeout(function() {
                    btn.textContent = '';
                    var icon = document.createElement('i');
                    icon.setAttribute('data-lucide', 'trash-2');
                    btn.appendChild(icon);
                    btn.appendChild(document.createTextNode(' ' + (T['docsight.speedtest.clear_cache'] || 'Clear Cache')));
                    if (typeof lucide !== 'undefined') lucide.createIcons();
                }, 2000);
            }
        })
        .catch(function() { btn.disabled = false; });
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
    el.appendChild(document.createTextNode(' ' + (T.notify_test_sending || 'Sending test notification...')));
    fetch(docsightUrl('/api/notifications/test'), {
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
            el.appendChild(document.createTextNode(' ' + (T.notify_test_sent || 'Test notification sent')));
        } else {
            el.className = 'test-result test-fail';
            var x = document.createElement('span');
            x.textContent = '\u2717';
            el.appendChild(x);
            el.appendChild(document.createTextNode(' ' + (res.error || T.unknown_error || 'Unknown error')));
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

/* ── Username Field Toggle + Modem Defaults (data-driven) ── */
var _previousDriverDefault = '';

function toggleUsernameField() {
    var modemType = document.getElementById('modem_type');
    if (!modemType) return;

    var usernameField = document.getElementById('modem_user');
    var urlField = document.getElementById('modem_url');
    var passwordField = document.getElementById('modem_password');
    var hints = (typeof DRIVER_HINTS !== 'undefined' && DRIVER_HINTS[modemType.value]) || {};

    // Fields to hide when credentials not required (e.g. generic driver)
    var credFields = [urlField, usernameField, passwordField].map(function(f) {
        return f ? f.closest('.form-field') : null;
    });
    var testBtn = document.querySelector('[onclick="testModem()"]');
    var testBtnParent = testBtn ? testBtn.parentElement : null;
    var testResult = document.getElementById('modem-test');

    // URL default: apply only if field is empty or shows the previous driver's default
    if (hints.default_url && urlField && (!urlField.value || urlField.value === _previousDriverDefault)) {
        urlField.value = hints.default_url;
    }
    _previousDriverDefault = hints.default_url || '';

    if (hints.credentials_required === false) {
        credFields.forEach(function(el) { if (el) el.style.display = 'none'; });
        if (testBtnParent) testBtnParent.style.display = 'none';
        if (testResult) testResult.style.display = 'none';
        return;
    }
    credFields.forEach(function(el) { if (el) el.style.display = ''; });
    if (testBtnParent) testBtnParent.style.display = '';

    // Username handling
    if (hints.username_required === false) {
        usernameField.disabled = true;
        usernameField.value = '';
        usernameField.placeholder = T.not_required || 'Not required for this modem';
        usernameField.style.opacity = '0.5';
        usernameField.style.cursor = 'not-allowed';
    } else {
        usernameField.disabled = false;
        usernameField.style.opacity = '1';
        usernameField.style.cursor = 'text';
        if (hints.default_user) {
            if (!usernameField.value) usernameField.value = hints.default_user;
            usernameField.placeholder = hints.default_user;
        } else {
            usernameField.placeholder = 'admin';
        }
    }
}

function init() {
    onIspChange();
    toggleUsernameField();
    var modemType = document.getElementById('modem_type');
    if (modemType) modemType.addEventListener('change', toggleUsernameField);
}
return {init, onIspChange, testModem, testMqtt, testSpeedtest, clearSpeedtestCache, testNotifications};
};
