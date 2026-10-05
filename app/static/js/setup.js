var setupBootstrapElement = document.getElementById('docsight-setup-bootstrap');
var setupBootstrap = DOCSightBrowserContracts.parseSetupBootstrapText(
    setupBootstrapElement && setupBootstrapElement.textContent
);
var SETUP_INDEX_URL = docsightUrl(setupBootstrap.indexUrl);
var SETUP_LOGIN_URL = docsightUrl(setupBootstrap.loginUrl);
let currentStep = 1;
var SETUP_T = setupBootstrap.translations;
var demoStartAccepted = false;
var demoWaitDeadline = 0;

function nextStep(step) {
    if (step > currentStep && !validateStep(currentStep)) return;
    document.querySelectorAll('.step-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.stepper-step').forEach(el => {
        el.classList.remove('active');
        el.classList.remove('done');
    });

    for(let i = 1; i < step; i++) {
        document.querySelector(`.stepper-step[data-step="${i}"]`).classList.add('done');
    }

    document.querySelector(`.step-content[data-step="${step}"]`).classList.add('active');
    document.querySelector(`.stepper-step[data-step="${step}"]`).classList.add('active');

    if(step === 3) {
        updateReview();
    }

    currentStep = step;
    window.scrollTo({top: 0, behavior: 'smooth'});
}

function prevStep(step) {
    nextStep(step);
}

function updateReview() {
    document.getElementById('review-modem-type').textContent = selectedModemName();
    document.getElementById('review-modem-url').textContent = document.getElementById('modem_url').value;
    document.getElementById('review-poll').textContent = document.getElementById('poll_interval').value;
    document.getElementById('review-tz').textContent = document.getElementById('timezone').value;
}

function _setButtonLoading(btn, iconName, text) {
    while (btn.firstChild) btn.removeChild(btn.firstChild);
    var icon = document.createElement('i');
    icon.setAttribute('data-lucide', iconName);
    icon.className = 'setup-icon-sm';
    if (iconName === 'loader-2') icon.classList.add('spin');
    btn.appendChild(icon);
    btn.appendChild(document.createTextNode(' ' + text));
    lucide.createIcons({nodes: [btn]});
}

async function testConnection() {
    var btn = document.getElementById('test-conn-btn');
    var resultDiv = document.getElementById('test-result');

    btn.disabled = true;
    _setButtonLoading(btn, 'loader-2', SETUP_T.testing);
    resultDiv.style.display = 'none';

    try {
        var data = {
            modem_type: document.getElementById('modem_type').value,
            modem_url: document.getElementById('modem_url').value,
            modem_user: document.getElementById('modem_user').value,
            modem_password: document.getElementById('modem_password').value
        };

        var response = await fetch(docsightUrl('/api/test-modem'), {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(data)
        });

        var result = await response.json();

        if(result.success) {
            resultDiv.className = 'test-result success';
            resultDiv.textContent = '✓ ' + (result.message || SETUP_T.connection_successful);
        } else {
            showSetupRecovery(
                resultDiv,
                _connectionFailureText(result, data.modem_url),
                testConnection,
                _connectionHelp(result)
            );
        }
        resultDiv.style.display = 'block';
    } catch(err) {
        showSetupRecovery(
            resultDiv,
            SETUP_T.network_error + ': ' + err.message,
            testConnection
        );
    }

    btn.disabled = false;
    _setButtonLoading(btn, 'wifi', SETUP_T.test_connection);
}

/* Name the likely cause of a failed connection test instead of a bare "failed". */
var CONNECTION_FAILURE_KEYS = {
    unreachable: 'setup_test_unreachable',
    auth: 'setup_test_auth',
    unexpected: 'setup_test_unexpected'
};

function _connectionFailureText(result, url) {
    var key = CONNECTION_FAILURE_KEYS[result && result.reason];
    var text = key && SETUP_T[key];
    if (!text) return (result && result.error) || SETUP_T.connection_failed;
    return text.replace('{url}', url || '');
}

function _connectionHelp(result) {
    var href = result && result.help_url;
    if (typeof href !== 'string' || href.indexOf('https://github.com/itsDNNS/docsight/wiki/') !== 0) return null;
    return {label: SETUP_T.setup_test_help, href: href};
}

function showSetupRecovery(resultDiv, message, retryFn, help) {
    if (!resultDiv) return;
    resultDiv.className = 'test-result error';
    resultDiv.style.display = 'block';
    resultDiv.textContent = '';
    var text = document.createElement('div');
    text.className = 'setup-recovery-message';
    text.textContent = '✗ ' + message;
    resultDiv.appendChild(text);
    var actions = document.createElement('div');
    actions.className = 'setup-recovery-actions';
    var retry = document.createElement('button');
    retry.type = 'button';
    retry.className = 'btn btn-secondary btn-sm';
    retry.textContent = SETUP_T.setup_try_again;
    retry.addEventListener('click', retryFn);
    var demo = document.createElement('button');
    demo.type = 'button';
    demo.className = 'btn btn-primary btn-sm';
    demo.textContent = SETUP_T.setup_try_demo;
    demo.addEventListener('click', startDemo);
    actions.appendChild(retry);
    actions.appendChild(demo);
    if (help) {
        var link = document.createElement('a');
        link.className = 'setup-recovery-help';
        link.href = help.href;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.textContent = help.label;
        actions.appendChild(link);
    }
    resultDiv.appendChild(actions);
    retry.focus({preventScroll: true});
}

function showSetupSubmitError(message) {
    showSetupRecovery(
        document.getElementById('setup-submit-result'),
        message,
        function() { document.getElementById('setup-form').requestSubmit(); }
    );
}

// Form submission
document.getElementById('setup-form').addEventListener('submit', async function(e) {
    e.preventDefault();

    var btn = document.getElementById('submit-btn');
    btn.disabled = true;
    _setButtonLoading(btn, 'loader-2', SETUP_T.saving);

    var formData = new FormData(e.target);
    var data = Object.fromEntries(formData.entries());
    // The connection kind only guides the modem choice; modem_type carries the result.
    delete data.connection_kind;

    try {
        var response = await fetch(docsightUrl('/api/config'), {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(data)
        });

        if(response.ok) {
            window.location.href = SETUP_INDEX_URL;
        } else {
            showSetupSubmitError(SETUP_T.setup_failed);
            btn.disabled = false;
            _setButtonLoading(btn, 'check-circle', SETUP_T.complete_setup);
        }
    } catch(err) {
        showSetupSubmitError(SETUP_T.error_generic + ': ' + err.message);
        btn.disabled = false;
        _setButtonLoading(btn, 'check-circle', SETUP_T.complete_setup);
    }
});

// Theme toggle
function toggleTheme() {
    var html = document.documentElement;
    var current = html.getAttribute('data-theme') || 'dark';
    var next = current === 'dark' ? 'light' : 'dark';
    html.setAttribute('data-theme', next);
    localStorage.setItem('docsis-theme', next);
}

// Driver hints (data-driven UI defaults)
var DRIVER_HINTS = setupBootstrap.driverHints;
var NOT_REQUIRED_TEXT = SETUP_T.not_required;

function toggleUsernameField() {
    var modemType = document.getElementById('modem_type').value;
    var usernameField = document.getElementById('modem_user');
    var urlField = document.getElementById('modem_url');
    var credGroup = document.getElementById('modem-credentials-group');
    var state = DOCSightBrowserContracts.selectSetupDriverState(
        DRIVER_HINTS, modemType, urlField.value, usernameField.value, NOT_REQUIRED_TEXT
    );
    urlField.value = state.url;

    // Nothing to log in to until a modem is chosen.
    if(!modemType || !state.credentialsVisible) {
        credGroup.style.display = 'none';
        return;
    }
    credGroup.style.display = 'grid';

    usernameField.value = state.username;
    usernameField.placeholder = state.usernamePlaceholder;
    if(!state.usernameEnabled) {
        usernameField.disabled = true;
        usernameField.style.opacity = '0.5';
        usernameField.style.cursor = 'not-allowed';
    } else {
        usernameField.disabled = false;
        usernameField.style.opacity = '1';
        usernameField.style.cursor = 'text';
    }
}

/* ── Step 1: connection kind and searchable modem list ── */
function _modemOptions(visibleOnly) {
    return Array.prototype.slice.call(document.querySelectorAll('#modem-options [role="option"]'))
        .filter(function(option) { return !visibleOnly || !option.hidden; });
}

function _showStepError(step, message) {
    var el = document.getElementById('step-' + step + '-error');
    if (!el) return;
    el.textContent = message || '';
    el.hidden = !message;
}

/* Cable connections pick a modem model; every other connection uses the
   generic router driver, so it never has to be found in the modem list. */
function chooseConnectionKind(kind) {
    document.getElementById('modem-picker').hidden = kind !== 'cable';
    document.getElementById('generic-note').hidden = kind !== 'other';
    var current = document.getElementById('modem_type').value;
    if (kind === 'other') setModemType('generic');
    else if (current === 'generic') setModemType('');
    _showStepError(1, '');
}

function setModemType(key) {
    document.getElementById('modem_type').value = key;
    _modemOptions(false).forEach(function(option) {
        option.setAttribute('aria-selected', String(option.dataset.value === key));
    });
    if (key) _showStepError(1, '');
    toggleUsernameField();
    _applyDetectedHost();
}

/* ── Opt-in modem detection (only on click) ── */
var _detectedDevice = null;

/* The chosen driver's scheme and port (from its default URL), the address the
   device answered on; without a driver default, the URL that answered. */
function _applyDetectedHost() {
    var field = document.getElementById('modem_url');
    if (!_detectedDevice || !field) return;
    var hints = DRIVER_HINTS[document.getElementById('modem_type').value] || {};
    try {
        var url = new URL(hints.default_url || _detectedDevice.url);
        url.hostname = _detectedDevice.host;
        field.value = url.origin;
    } catch (error) {
        field.value = _detectedDevice.url;
    }
}

function _modemName(key) {
    var option = document.getElementById('modem-option-' + key);
    var name = option && option.querySelector('.setup-modem-name');
    return name ? name.textContent : key;
}

function _detectButton(label, onClick) {
    var button = document.createElement('button');
    button.type = 'button';
    button.className = 'btn btn-secondary setup-detect-use';
    button.textContent = label;
    button.addEventListener('click', onClick);
    return button;
}

function _renderDetectedDevices(container, devices) {
    container.textContent = '';
    if (!devices.length) {
        var none = document.createElement('p');
        none.className = 'setup-detect-message';
        none.textContent = SETUP_T.setup_detect_none;
        container.appendChild(none);
        return;
    }
    devices.forEach(function(device) {
        var card = document.createElement('div');
        card.className = 'setup-detect-device';
        var title = document.createElement('p');
        title.className = 'setup-detect-title';
        title.textContent = SETUP_T.setup_detect_found.replace('{url}', device.url);
        card.appendChild(title);
        var actions = document.createElement('div');
        actions.className = 'setup-detect-actions';
        if (device.drivers.length) {
            var probably = document.createElement('span');
            probably.className = 'setup-detect-label';
            probably.textContent = SETUP_T.setup_detect_probably;
            actions.appendChild(probably);
            device.drivers.forEach(function(key) {
                actions.appendChild(_detectButton(SETUP_T.setup_detect_use + ': ' + _modemName(key), function() {
                    _detectedDevice = device;
                    setModemType(key);
                    var option = document.getElementById('modem-option-' + key);
                    if (option) option.scrollIntoView({block: 'nearest'});
                }));
            });
        } else {
            var unknown = document.createElement('span');
            unknown.className = 'setup-detect-label';
            unknown.textContent = SETUP_T.setup_detect_unknown;
            actions.appendChild(unknown);
            actions.appendChild(_detectButton(SETUP_T.setup_detect_use_address, function() {
                _detectedDevice = device;
                _applyDetectedHost();
                document.getElementById('modem-search').focus();
            }));
        }
        card.appendChild(actions);
        container.appendChild(card);
    });
}

async function detectModem() {
    var btn = document.getElementById('detect-modem-btn');
    var results = document.getElementById('detect-modem-results');
    btn.disabled = true;
    _setButtonLoading(btn, 'loader-2', SETUP_T.setup_detect_running);
    // A previous failure turned the container into an error box.
    results.className = 'setup-detect-results';
    results.style.display = '';
    results.textContent = '';
    try {
        var response = await fetch(docsightUrl('/api/setup/detect-modem'), {method: 'POST'});
        if (!response.ok) throw new Error('HTTP ' + response.status);
        var data = await response.json();
        _renderDetectedDevices(results, Array.isArray(data.devices) ? data.devices : []);
    } catch (err) {
        showSetupRecovery(results, SETUP_T.network_error + ': ' + err.message, detectModem);
    }
    btn.disabled = false;
    _setButtonLoading(btn, 'radar', SETUP_T.setup_detect_button);
}

function selectedModemName() {
    var input = document.getElementById('modem_type');
    if (input.value === 'generic') return input.dataset.genericName;
    var option = document.getElementById('modem-option-' + input.value);
    var name = option && option.querySelector('.setup-modem-name');
    return name ? name.textContent : input.value;
}

function filterModemOptions(query) {
    var tokens = String(query || '').toLowerCase().split(/\s+/).filter(Boolean);
    _modemOptions(false).forEach(function(option) {
        var haystack = option.dataset.search || '';
        option.hidden = !tokens.every(function(token) { return haystack.indexOf(token) !== -1; });
    });
    document.querySelectorAll('#modem-options .setup-modem-group').forEach(function(group) {
        group.hidden = !group.querySelector('[role="option"]:not([hidden])');
    });
    document.getElementById('modem-search-empty').hidden = _modemOptions(true).length > 0;
    _setActiveModemOption(null);
}

function _setActiveModemOption(option) {
    var search = document.getElementById('modem-search');
    _modemOptions(false).forEach(function(item) { item.classList.toggle('is-active', item === option); });
    if (option) {
        search.setAttribute('aria-activedescendant', option.id);
        option.scrollIntoView({block: 'nearest'});
    } else {
        search.removeAttribute('aria-activedescendant');
    }
}

function _onModemSearchKey(event) {
    var visible = _modemOptions(true);
    var active = document.querySelector('#modem-options .is-active');
    var index = visible.indexOf(active);
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        if (!visible.length) return;
        var next = event.key === 'ArrowDown' ? Math.min(visible.length - 1, index + 1) : Math.max(0, index - 1);
        _setActiveModemOption(visible[next]);
    } else if (event.key === 'Enter') {
        // Enter picks the highlighted model (or the only match) instead of submitting the form.
        event.preventDefault();
        var pick = active && !active.hidden ? active : (visible.length === 1 ? visible[0] : null);
        if (pick) setModemType(pick.dataset.value);
    } else if (event.key === 'Escape') {
        event.target.value = '';
        filterModemOptions('');
    }
}

function _initModemPicker() {
    var search = document.getElementById('modem-search');
    if (!search) return;
    search.addEventListener('input', function() { filterModemOptions(search.value); });
    search.addEventListener('keydown', _onModemSearchKey);
    document.getElementById('modem-options').addEventListener('click', function(event) {
        var option = event.target.closest('[role="option"]');
        if (!option) return;
        setModemType(option.dataset.value);
        _setActiveModemOption(option);
    });
}

/* ── Step 2: time zone, prefilled from the browser when nothing is saved ── */
function _timezoneOptions() {
    return Array.prototype.map.call(document.querySelectorAll('#timezone-options option'), function(option) {
        return option.value;
    });
}

function _prefillTimezone() {
    var field = document.getElementById('timezone');
    if (!field || field.value) return;
    var known = _timezoneOptions();
    var browserZone = '';
    try { browserZone = Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (error) { browserZone = ''; }
    if (known.indexOf(browserZone) !== -1) field.value = browserZone;
    else if (known.indexOf(field.dataset.serverTimezone) !== -1) field.value = field.dataset.serverTimezone;
}

function validateStep(step) {
    if (step === 1) {
        var kind = document.querySelector('input[name="connection_kind"]:checked');
        if (!kind) {
            _showStepError(1, SETUP_T.setup_choose_connection);
            document.querySelector('input[name="connection_kind"]').focus();
            return false;
        }
        if (!document.getElementById('modem_type').value) {
            _showStepError(1, SETUP_T.setup_choose_modem);
            document.getElementById('modem-search').focus();
            return false;
        }
    }
    if (step === 2) {
        var field = document.getElementById('timezone');
        if (_timezoneOptions().indexOf(field.value) === -1) {
            _showStepError(2, SETUP_T.setup_timezone_invalid);
            field.focus();
            return false;
        }
        _showStepError(2, '');
    }
    return true;
}

// Initialize on load
document.addEventListener('DOMContentLoaded', function() {
    toggleUsernameField();
    _initModemPicker();
    _prefillTimezone();
    lucide.createIcons();
    if (new URLSearchParams(window.location.search).get('connect') === '1') {
        startFreshSetup();
    }
});

/* ── Setup start paths ── */
function startFreshSetup() {
    document.getElementById('setup-start').style.display = 'none';
    document.getElementById('setup-stepper').style.display = '';
    document.getElementById('setup-form').style.display = '';
    nextStep(1);
}

function _showDemoStatus(text) {
    var result = document.getElementById('demo-start-result');
    result.className = 'test-result first-run-result';
    result.style.display = 'block';
    result.textContent = text;
}

function _showDemoFailure(message, retryFn) {
    var result = document.getElementById('demo-start-result');
    var button = document.getElementById('start-demo-btn');
    button.disabled = false;
    _setButtonLoading(button, 'play', SETUP_T.setup_demo_start);
    result.className = 'test-result error first-run-result';
    result.style.display = 'block';
    result.textContent = '';
    var text = document.createElement('div');
    text.textContent = '✗ ' + message;
    result.appendChild(text);
    var retry = document.createElement('button');
    retry.type = 'button';
    retry.className = 'btn btn-secondary btn-sm first-run-retry';
    retry.textContent = SETUP_T.setup_try_again;
    retry.addEventListener('click', retryFn);
    result.appendChild(retry);
}

async function waitForDemoData(resetDeadline) {
    if (resetDeadline || !demoWaitDeadline) {
        demoWaitDeadline = Date.now() + 45000;
    }
    _showDemoStatus(SETUP_T.setup_demo_waiting);
    try {
        var response = await fetch(docsightUrl('/health'), {cache: 'no-store'});
        var health = await response.json();
        if (response.ok && health.docsis_health !== 'waiting') {
            window.location.assign(SETUP_INDEX_URL);
            return;
        }
    } catch(err) {
        // Keep polling until the actionable timeout state is reached.
    }
    if (Date.now() >= demoWaitDeadline) {
        _showDemoFailure(
            SETUP_T.setup_demo_timeout,
            function() { waitForDemoData(true); }
        );
        return;
    }
    window.setTimeout(function() { waitForDemoData(false); }, 500);
}

async function startDemo() {
    document.getElementById('setup-start').style.display = '';
    document.getElementById('setup-start').classList.add('active');
    document.getElementById('setup-stepper').style.display = 'none';
    document.getElementById('setup-form').style.display = 'none';
    document.getElementById('restore-section').style.display = 'none';

    var button = document.getElementById('start-demo-btn');
    if (demoStartAccepted) {
        button.disabled = true;
        _setButtonLoading(button, 'loader-2', SETUP_T.setup_demo_waiting);
        waitForDemoData(true);
        return;
    }

    button.disabled = true;
    _setButtonLoading(button, 'loader-2', SETUP_T.setup_demo_starting);
    _showDemoStatus(SETUP_T.setup_demo_starting);
    try {
        var response = await fetch(docsightUrl('/api/demo/start'), {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: '{}'
        });
        if (response.status === 401 || response.status === 403) {
            window.location.assign(SETUP_LOGIN_URL);
            return;
        }
        var result = await response.json();
        if (!response.ok || !result.success) {
            _showDemoFailure(SETUP_T.setup_demo_failed, startDemo);
            return;
        }
        demoStartAccepted = true;
        _setButtonLoading(button, 'loader-2', SETUP_T.setup_demo_waiting);
        waitForDemoData(true);
    } catch(err) {
        _showDemoFailure(
            SETUP_T.setup_demo_failed + ' ' + SETUP_T.network_error + ': ' + err.message,
            startDemo
        );
    }
}

function startRestore() {
    document.getElementById('setup-start').style.display = 'none';
    document.getElementById('restore-section').style.display = '';
}

function backToStart() {
    document.getElementById('restore-section').style.display = 'none';
    document.getElementById('setup-stepper').style.display = 'none';
    document.getElementById('setup-form').style.display = 'none';
    document.getElementById('setup-start').style.display = '';
    document.getElementById('setup-start').classList.add('active');
    document.getElementById('restore-file').value = '';
    document.getElementById('restore-meta').style.display = 'none';
    document.getElementById('restore-result').style.display = 'none';
}

/* ── Restore Flow ── */
var T_setup = {
    validating: SETUP_T.restore_validating,
    restoring: SETUP_T.restore_restoring,
    success: SETUP_T.restore_success,
    version: SETUP_T.restore_version,
    date: SETUP_T.restore_date,
    tables: SETUP_T.restore_tables,
    network_error: SETUP_T.network_error
};

function _showResultLoading(resultDiv, text) {
    resultDiv.className = 'test-result';
    resultDiv.style.display = 'block';
    resultDiv.style.background = 'var(--amethyst-muted)';
    resultDiv.style.border = '1px solid rgba(124,58,237,0.2)';
    resultDiv.style.color = 'var(--text-secondary)';
    // Build DOM nodes instead of innerHTML
    while (resultDiv.firstChild) resultDiv.removeChild(resultDiv.firstChild);
    var icon = document.createElement('i');
    icon.setAttribute('data-lucide', 'loader-2');
    icon.className = 'spin setup-icon-sm';
    icon.style.cssText = 'display:inline-block;vertical-align:middle;margin-right:6px;';
    resultDiv.appendChild(icon);
    resultDiv.appendChild(document.createTextNode(' ' + text));
    lucide.createIcons({nodes: [resultDiv]});
}

function _showResultError(resultDiv, msg) {
    resultDiv.className = 'test-result error';
    resultDiv.style.background = '';
    resultDiv.style.border = '';
    resultDiv.style.color = '';
    resultDiv.textContent = '✗ ' + msg;
}

function _buildMetaInfo(container, meta) {
    while (container.firstChild) container.removeChild(container.firstChild);
    /* No time zone is configured yet during setup, so the browser zone applies. */
    var date = meta.timestamp ? DOCSightBrowserContracts.formatTimestamp(meta.timestamp, {
        locale: document.documentElement.lang || undefined
    }) : '?';

    var b1 = document.createElement('strong');
    b1.textContent = T_setup.version + ':';
    container.appendChild(b1);
    container.appendChild(document.createTextNode(' ' + (meta.app_version || '?')));
    container.appendChild(document.createElement('br'));

    var b2 = document.createElement('strong');
    b2.textContent = T_setup.date + ':';
    container.appendChild(b2);
    container.appendChild(document.createTextNode(' ' + date));

    if (meta.tables) {
        var tkeys = Object.keys(meta.tables);
        var tables = tkeys.map(function(k) { return k + ': ' + meta.tables[k]; }).join(', ');
        container.appendChild(document.createElement('br'));
        var b3 = document.createElement('strong');
        b3.textContent = T_setup.tables + ':';
        container.appendChild(b3);
        container.appendChild(document.createTextNode(' ' + tables));
    }
}

async function validateRestoreFile() {
    var fileInput = document.getElementById('restore-file');
    var metaDiv = document.getElementById('restore-meta');
    var resultDiv = document.getElementById('restore-result');
    metaDiv.style.display = 'none';
    resultDiv.style.display = 'none';

    if (!fileInput.files.length) return;

    _showResultLoading(resultDiv, T_setup.validating);

    var formData = new FormData();
    formData.append('file', fileInput.files[0]);

    try {
        var response = await fetch(docsightUrl('/api/restore/validate'), { method: 'POST', body: formData });
        var res = await response.json();

        if (res.valid) {
            resultDiv.style.display = 'none';
            _buildMetaInfo(document.getElementById('restore-meta-info'), res.meta);
            metaDiv.style.display = '';
        } else {
            _showResultError(resultDiv, res.error || SETUP_T.invalid_backup);
        }
    } catch(err) {
        _showResultError(resultDiv, T_setup.network_error + ': ' + err.message);
    }
}

async function doRestore() {
    var fileInput = document.getElementById('restore-file');
    var btn = document.getElementById('restore-confirm-btn');
    var resultDiv = document.getElementById('restore-result');

    if (!fileInput.files.length) return;

    btn.disabled = true;
    _showResultLoading(resultDiv, T_setup.restoring);

    var formData = new FormData();
    formData.append('file', fileInput.files[0]);

    try {
        var response = await fetch(docsightUrl('/api/restore'), { method: 'POST', body: formData });
        var res = await response.json();

        if (res.success) {
            resultDiv.className = 'test-result success';
            resultDiv.style.background = '';
            resultDiv.style.border = '';
            resultDiv.style.color = '';
            resultDiv.textContent = '✓ ' + T_setup.success;
            if (res.configured) {
                setTimeout(function() { window.location.href = SETUP_INDEX_URL; }, 2000);
            } else {
                setTimeout(function() {
                    document.getElementById('restore-section').style.display = 'none';
                    document.getElementById('setup-stepper').style.display = '';
                    document.getElementById('setup-form').style.display = '';
                }, 2000);
            }
        } else {
            _showResultError(resultDiv, res.error || SETUP_T.restore_failed);
            btn.disabled = false;
        }
    } catch(err) {
        _showResultError(resultDiv, T_setup.network_error + ': ' + err.message);
        btn.disabled = false;
    }
}
