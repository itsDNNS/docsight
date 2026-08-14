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
    const modemType = document.getElementById('modem_type');
    const selectedOption = modemType.options[modemType.selectedIndex].text;

    document.getElementById('review-modem-type').textContent = selectedOption;
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
                result.error || SETUP_T.connection_failed,
                testConnection
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

function showSetupRecovery(resultDiv, message, retryFn) {
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
    retry.className = 'btn btn-ghost btn-sm';
    retry.textContent = SETUP_T.setup_try_again;
    retry.addEventListener('click', retryFn);
    var demo = document.createElement('button');
    demo.type = 'button';
    demo.className = 'btn btn-primary btn-sm';
    demo.textContent = SETUP_T.setup_try_demo;
    demo.addEventListener('click', startDemo);
    actions.appendChild(retry);
    actions.appendChild(demo);
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
    localStorage.setItem('theme', next);
}

// Load theme preference
(function() {
    var saved = localStorage.getItem('theme');
    if(saved) {
        document.documentElement.setAttribute('data-theme', saved);
    }
})();

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

    if(!state.credentialsVisible) {
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

// Initialize on load
document.addEventListener('DOMContentLoaded', function() {
    toggleUsernameField();
    document.getElementById('modem_type').addEventListener('change', toggleUsernameField);
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
    retry.className = 'btn btn-ghost btn-sm first-run-retry';
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
    var date = meta.timestamp ? new Date(meta.timestamp).toLocaleString() : '?';

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
