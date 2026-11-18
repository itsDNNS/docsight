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
    row.hidden = sel.value !== '__other__';
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

/* ── Connection Tests ── */
function showTestResult(el, state, text) {
    el.className = 'test-result test-' + state;
    el.style.display = 'flex';
    el.textContent = '';
    var mark = document.createElement('span');
    mark.textContent = {loading: '\u23F3', ok: '\u2713', fail: '\u2717'}[state];
    if (state === 'ok') mark.className = 'check-icon';
    el.appendChild(mark);
    el.appendChild(document.createTextNode(' ' + text));
}

function errorText(res) {
    return T.error_prefix + ': ' + (res.error || T.unknown_error);
}

/* Posts body to url and shows progress and result in the element with the given id.
   opts.status(state, text) mirrors the result in a connection status box. */
function runConnectionTest(opts) {
    var el = document.getElementById(opts.id);
    var status = opts.status || function() {};
    showTestResult(el, 'loading', opts.testingText || T.testing);
    status('testing', T.testing);
    fetch(docsightUrl(opts.url), {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(opts.body)
    })
    .then(function(r) { return r.json(); })
    .then(function(res) {
        var text = res.success ? opts.success(res) : (opts.failure || errorText)(res);
        showTestResult(el, res.success ? 'ok' : 'fail', text);
        status(res.success ? 'connected' : 'disconnected', text);
    })
    .catch(function() {
        var text = opts.networkText || T.network_error;
        showTestResult(el, 'fail', text);
        status('disconnected', text);
    });
}

function testModem() {
    var data = getFormData();
    runConnectionTest({
        id: 'modem-test', url: '/api/test-modem', status: setModemStatus,
        body: {modem_type: data.modem_type, modem_url: data.modem_url, modem_user: data.modem_user, modem_password: data.modem_password},
        success: function(res) { return T.connected + ': ' + (res.model || 'OK'); }
    });
}

function testMqtt() {
    var data = getFormData();
    runConnectionTest({
        id: 'mqtt-test', url: '/api/test-mqtt', status: setMqttStatus,
        // An anonymous broker gets no password, not even the saved-password mask.
        body: {mqtt_host: data.mqtt_host, mqtt_port: data.mqtt_port, mqtt_user: data.mqtt_user, mqtt_password: data.mqtt_user ? data.mqtt_password : '', mqtt_tls_insecure: data.mqtt_tls_insecure},
        success: function() { return T.connected; }
    });
}

function testSpeedtest() {
    var data = getFormData();
    runConnectionTest({
        id: 'speedtest-test', url: '/api/test-speedtest',
        body: {
            speedtest_tracker_url: data.speedtest_tracker_url,
            speedtest_tracker_token: data.speedtest_tracker_token,
            speedtest_tls_insecure: data.speedtest_tls_insecure
        },
        success: function(res) {
            if (res.results > 0) {
                return T.connected + ': ' + res.latest.download + ' \u2193 / ' + res.latest.upload + ' \u2191 / ' + res.latest.ping;
            }
            return T.connected + ' (' + (T.speedtest_no_results || 'no results yet') + ')';
        }
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

function testNotifications() {
    runConnectionTest({
        id: 'notify-test', url: '/api/notifications/test', body: {},
        testingText: T.notify_test_sending || 'Sending test notification...',
        success: function() { return T.notify_test_sent || 'Test notification sent'; },
        failure: function(res) { return res.error || T.unknown_error || 'Unknown error'; },
        networkText: T.network_error || 'Network error'
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
    var testBtn = document.querySelector('[data-action="testModem"]');
    var testBtnParent = testBtn ? testBtn.parentElement : null;
    var testResult = document.getElementById('modem-test');

    // URL default: apply only if field is empty or shows the previous driver's default
    if (hints.default_url && urlField && (!urlField.value || urlField.value === _previousDriverDefault)) {
        urlField.value = hints.default_url;
    }
    _previousDriverDefault = hints.default_url || '';

    if (hints.credentials_required === false) {
        credFields.forEach(function(el) { if (el) el.style.display = 'none'; });
        if (testBtnParent) testBtnParent.hidden = true;
        if (testResult) testResult.style.display = 'none';
        return;
    }
    credFields.forEach(function(el) { if (el) el.style.display = ''; });
    if (testBtnParent) testBtnParent.hidden = false;

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
