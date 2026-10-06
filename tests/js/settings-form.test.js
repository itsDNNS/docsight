'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const tick = () => new Promise(resolve => setImmediate(resolve));

function fixture(bootstrap = false) {
    const listeners = new Map(), requests = [], timers = [], nodes = new Map();
    function element(id, type = 'text', value = '', instant = false) {
        const events = {}, attributes = {}, classes = new Set();
        const el = {id, name: id, type, value, instant, checked: false, tagName: 'INPUT', dataset: {}, style: {},
            addEventListener: (name, fn) => (events[name] ||= []).push(fn),
            getAttribute: name => attributes[name] || '',
            setAttribute: (name, value) => { attributes[name] = value; },
            removeAttribute: name => { delete attributes[name]; },
            toggleAttribute: (name, on) => { if (on) attributes[name] = ''; else delete attributes[name]; },
            classList: {contains: name => classes.has(name), toggle: (name, on) => on ? classes.add(name) : classes.delete(name),
                add: name => classes.add(name), remove: name => classes.delete(name)},
            closest: selector => selector === '.settings-panel' && el.panel || null,
            dispatchEvent: event => el.dispatch(event.type),
            matches: selector => selector === '.module-toggle-input' ? !!el.module : instant,
            dispatch(name, trusted = true) {
                const event = {target: el, isTrusted: trusted, preventDefault() {}};
                for (const fn of events[name] || []) fn(event);
                if (el.form) for (const fn of el.form.events[name] || []) fn(event);
            }
        };
        nodes.set(id, el);
        return el;
    }
    const url = element('modem_url', 'text', 'old');
    const secret = element('modem_password', 'password');
    secret.dataset.savedSecret = 'true';
    const fresh = element('admin_password', 'password', 'initial-secret');
    const toggle = element('enabled', 'checkbox', 'true', true);
    const hidden = element('companion', 'hidden', 'false');
    hidden.name = toggle.name;
    const module = element('module', 'checkbox', 'true', true);
    module.module = true;
    module.setAttribute('data-module-id', 'docsight.example');
    const language = element('language', 'select-one', 'en');
    const timezone = element('timezone', 'select-one', 'UTC');
    const isp = element('isp_select');
    const email = element('community_email', 'email', 'a@example.org,b@example.org');
    email.multiple = true;
    url.panel = {id: 'panel-connection'};
    language.panel = {id: 'panel-general'};
    const fields = [url, secret, fresh, toggle, hidden, module, language, timezone, isp, email];
    const form = {elements: fields, events: {},
        addEventListener(name, fn) { (this.events[name] ||= []).push(fn); },
        querySelectorAll(selector) {
            if (selector.startsWith('input:not')) return fields.filter(el => !el.module);
            return selector === '.module-toggle-input' ? [module] : [toggle];
        }
    };
    fields.forEach(el => { el.form = form; });
    nodes.set('settings-form', form);
    const footer = element('save-footer'), error = element('global-error');
    Object.defineProperty(error, 'innerHTML', {set() { assert.fail('Errors must use textContent'); }});
    const discard = element('save-bar-discard'), count = element('save-bar-count'), sections = element('save-bar-sections');
    element('toast'); element('module-restart-banner');
    element('isp-other-row'); element('isp-icon-preview');
    const document = {getElementById: id => nodes.get(id) || null, querySelectorAll: () => [], querySelector: () => null,
        documentElement: {getAttribute: () => 'dark'}, activeElement: null,
        addEventListener: (name, fn) => listeners.set(name, fn)};
    const context = vm.createContext({document, T: {}, currentLang: 'en', currentTz: 'UTC',
        setTimeout: fn => timers.push(fn), clearTimeout() {}, docsightUrl: path => '/prefix' + path,
        docsightConfirm: () => Promise.resolve(true),
        fetch: (url, options) => new Promise((resolve, reject) => requests.push({url,
            data: JSON.parse(options.body), reject,
            finish: (success = true, error) => resolve({ok: success, json: () => Promise.resolve({success, error})})})),
        localStorage: {getItem: () => null}, SECTION_TITLES: {connection: 'Modem', general: 'General'},
        Event: class { constructor(type) { this.type = type; } }, history: {replaceState() {}, pushState() {}},
        location: {hash: '', reload: () => { context.reloads++; }}, reloads: 0,
        addEventListener: (name, fn) => listeners.set(name, fn)});
    context.window = context;
    for (const name of ['form-state', 'form']) vm.runInContext(fs.readFileSync(`app/static/js/settings/${name}.js`, 'utf8'), context);
    const owner = context.DOCSightSettings.form({state: context.DOCSightSettings.state, showsSaveFooter: () => true});
    if (bootstrap) {
        for (const name of ['navigation', 'tokens', 'connections', 'notifications', 'backups', 'themes', 'smart-capture', 'module-registry', 'search']) {
            vm.runInContext(fs.readFileSync(`app/static/js/settings/${name}.js`, 'utf8'), context);
        }
        vm.runInContext(fs.readFileSync('app/static/js/settings.js', 'utf8'), context);
        listeners.get('DOMContentLoaded')();
    } else owner.init();
    return {context, owner, requests, timers, url, secret, fresh, toggle, hidden, module, language, timezone, footer, error, discard, count, sections,
        edit(el, value, trusted = true) { document.activeElement = el; el.value = value; el.dispatch('input', trusted); },
        dirty() { let blocked = false; listeners.get('beforeunload')({preventDefault() { blocked = true; }}); return blocked; }};
}

test('the save bar counts manual changes with their sections and discard restores the saved values', () => {
    const f = fixture();
    f.edit(f.url, 'new-url');
    f.edit(f.fresh, 'typed-secret');
    f.edit(f.language, 'de');
    f.toggle.checked = true;
    assert.equal(f.footer.classList.contains('visible'), true);
    assert.equal(f.count.textContent, 'Unsaved changes (3)');
    assert.equal(f.sections.textContent, 'Modem, General');
    f.discard.dispatch('click');
    assert.equal(f.url.value, 'old');
    assert.equal(f.language.value, 'en');
    assert.equal(f.fresh.value, '');
    assert.equal(f.fresh.dataset.userEditedSecret, undefined);
    assert.equal(f.toggle.checked, true, 'instant controls are not reverted');
    assert.equal(f.footer.classList.contains('visible'), false);
});

test('FIFO captures edits at execution and survives a rejected first request', async () => {
    const f = fixture();
    f.toggle.checked = true;
    const first = f.owner.save();
    await tick();
    const second = f.owner.save();
    f.edit(f.url, 'before-second-start');
    assert.equal(f.requests.length, 1);
    f.requests[0].reject(new Error('network'));
    assert.equal(await first, false);
    await tick();
    assert.equal(f.requests[1].data.modem_url, 'before-second-start');
    f.requests[1].finish();
    assert.equal(await second, true);
    assert.equal(f.dirty(), false);
});

test('partial failure acknowledges config and secrets, retries modules, and preserves later module edits', async () => {
    const f = fixture();
    f.edit(f.secret, 'submitted-secret');
    f.module.checked = true;
    const first = f.owner.save();
    await tick();
    f.requests[0].finish();
    await tick();
    assert.equal(f.secret.value, '');
    assert.equal(f.requests[1].url, '/prefix/api/modules/batch');
    f.requests[1].finish(false, 'Exactly one threshold profile must be active.');
    assert.equal(await first, false);
    assert.equal(f.error.textContent, 'Exactly one threshold profile must be active.');
    assert.equal(f.error.style.display, 'block');
    assert.equal(f.footer.classList.contains('visible'), true);
    const retry = f.owner.save();
    await tick();
    assert.equal(f.requests[2].data.modem_password, '••••••••');
    f.requests[2].finish();
    await tick();
    assert.equal(f.requests[3].data.modules[0].enabled, true);
    f.module.checked = false;
    f.requests[3].finish();
    await retry;
    assert.equal(f.dirty(), true);
});

test('secret reedit, hidden companion and manual edits after dispatch survive acknowledgement', async () => {
    const f = fixture();
    f.edit(f.secret, 'first-secret');
    const job = f.owner.save();
    await tick();
    f.edit(f.secret, 'second-secret');
    f.edit(f.hidden, 'later-hidden');
    f.edit(f.url, 'later-url');
    f.requests[0].finish();
    await job;
    assert.equal(f.secret.value, 'second-secret');
    assert.equal(f.footer.classList.contains('visible'), true);
    assert.equal(f.dirty(), true);
    const retry = f.owner.save();
    await tick();
    assert.equal(f.requests[1].data.modem_password, 'second-secret');
    f.requests[1].finish();
    await retry;
    assert.equal(f.dirty(), false);
    assert.equal(f.fresh.value, '');
    assert.equal(f.fresh.dataset.savedSecret, 'true');
});

test('config validation messages and missing-message fallbacks render as text and allow retry', async () => {
    const f = fixture();
    f.context.T.save_failed = 'Speichern fehlgeschlagen';
    f.edit(f.url, 'invalid');
    for (const message of ['Invalid timezone', "Invalid URL scheme 'javascript' for modem_url. Only http and https are allowed.", undefined, null]) {
        const job = f.owner.save();
        await tick();
        assert.equal(f.requests.at(-1).url, '/prefix/api/config');
        if (message === null) f.requests.at(-1).reject(new Error());
        else f.requests.at(-1).finish(false, message);
        assert.equal(await job, false);
        assert.equal(f.error.textContent, message || 'Speichern fehlgeschlagen');
        assert.equal(f.error.style.display, 'block');
        assert.equal(f.dirty(), true);
    }
    const retry = f.owner.save();
    await tick();
    assert.equal(f.requests.at(-1).data.community_email, 'a@example.org,b@example.org');
    f.requests.at(-1).finish();
    assert.equal(await retry, true);
    assert.equal(f.dirty(), false);
    assert.equal(f.error.style.display, 'none');
});

test('instant controls save only themselves, without a footer or success toast', async () => {
    const f = fixture();
    f.edit(f.secret, 'autofill', false);
    f.context.document.activeElement = f.url;
    f.secret.dispatch('input', true);
    assert.equal(f.dirty(), false);
    f.toggle.checked = true;
    f.toggle.dispatch('change');
    assert.equal(f.footer.classList.contains('visible'), false);
    await tick();
    assert.deepEqual(f.requests[0].data, {enabled: 'true'});
    f.requests[0].finish();
    await tick();
    assert.equal(f.footer.classList.contains('visible'), false);
    assert.equal(f.dirty(), false);
    assert.equal(f.timers.length, 0);
});

test('an instant save leaves manual edits unsaved and counted', async () => {
    const f = fixture();
    f.edit(f.url, 'manual-edit');
    f.toggle.checked = true;
    f.toggle.dispatch('change');
    await tick();
    assert.deepEqual(f.requests[0].data, {enabled: 'true'});
    f.requests[0].finish();
    await tick();
    assert.equal(f.url.value, 'manual-edit');
    assert.equal(f.footer.classList.contains('visible'), true);
    assert.equal(f.count.textContent, 'Unsaved changes (1)');
    assert.equal(f.dirty(), true);
});

test('a module switch sends only the module change', async () => {
    const f = fixture();
    f.edit(f.url, 'manual-edit');
    f.module.checked = true;
    f.module.dispatch('change');
    await tick();
    assert.equal(f.requests.length, 1);
    assert.equal(f.requests[0].url, '/prefix/api/modules/batch');
    assert.deepEqual(f.requests[0].data, {modules: [{id: 'docsight.example', enabled: true}]});
    f.requests[0].finish();
    await tick();
    assert.equal(f.footer.classList.contains('visible'), true);
    assert.equal(f.count.textContent, 'Unsaved changes (1)');
});

test('reload uses confirmed values and checks for later edits and queued work at timer execution', async () => {
    const f = fixture();
    f.edit(f.language, 'de');
    const first = f.owner.save();
    await tick();
    f.requests[0].finish();
    await first;
    f.edit(f.url, 'unsaved');
    f.timers.splice(0).forEach(fn => fn());
    assert.equal(f.context.reloads, 0);
    const second = f.owner.save();
    await tick();
    f.requests[1].finish();
    await second;
    f.timers.splice(0).forEach(fn => fn());
    assert.equal(f.context.reloads, 1);
});

test('an unconfirmed language edit during an earlier save cannot cause a reload', async () => {
    const f = fixture();
    const job = f.owner.save();
    await tick();
    f.edit(f.language, 'de');
    f.requests[0].finish();
    await job;
    f.timers.splice(0).forEach(fn => fn());
    assert.equal(f.context.reloads, 0);
    assert.equal(f.dirty(), true);
});


test('all settings owners initialize together and expose only the legacy handler boundary', () => {
    const f = fixture(true);
    assert.equal(typeof f.context.getFormData, 'function');
    assert.equal(typeof f.context.testModem, 'function');
    for (const section of ['connection', 'general', 'notifications', 'appearance', 'security', 'smart_capture', 'extensions']) {
        f.context.switchSection(section);
    }
    for (const privateName of ['_formDirty', '_finishSettingsSave', '_serializeSettingsForm', 'saveAll', 'capture']) {
        assert.equal(f.context[privateName], undefined);
    }
    assert.equal(f.dirty(), false);
});

test('theme installation localizes conflicts and preserves success and other failures', async t => {
    const T = JSON.parse(fs.readFileSync('app/i18n/de.json', 'utf8'));
    const theme = {id: 'community.example', name: 'Example', version: '1.0.0',
        download_url: 'https://api.github.com/repos/example/themes/contents/theme'};
    for (const scenario of [
        {name: '409 conflict', status: 409, data: {success: false, error: 'Theme already installed'}, expected: T.theme_install_failed},
        {name: '409 without message', status: 409, data: {success: false}, expected: T.theme_install_failed},
        {name: '400 retains API message', status: 400, data: {success: false, error: 'Theme already installed'}, expected: 'Theme already installed'},
        {name: '500 retains API message', status: 500, data: {success: false, error: 'Download failed'}, expected: 'Download failed'},
        {name: '500 without message', status: 500, data: {success: false}, expected: T.theme_install_failed},
        {name: 'successful install', status: 200, data: {success: true, restart_required: true}, expected: T.theme_installed, success: true},
        {name: 'network failure', failure: new Error('offline'), expected: T.error_prefix + ': offline'},
        {name: 'invalid response JSON', status: 500, jsonFailure: new Error('invalid JSON'), expected: T.error_prefix + ': invalid JSON'},
    ]) {
        await t.test(scenario.name, async () => {
            const requests = [], toasts = [], buttons = [];
            const element = () => ({appendChild() {}, addEventListener(event, fn) {
                assert.equal(event, 'click');
                this.click = fn;
            }});
            const gallery = element();
            const context = vm.createContext({DOCSightSettings: {}, T,
                document: {
                    getElementById: id => id === 'registry-gallery' ? gallery : null,
                    createElement(tag) {
                        const node = element();
                        if (tag === 'button') buttons.push(node);
                        return node;
                    }
                },
                docsightUrl: path => '/prefix' + path, lucide: {createIcons() {}},
                async fetch(url, options) {
                    requests.push({url, options});
                    if (url === '/prefix/api/themes/registry') return {json: async () => [theme]};
                    assert.equal(url, '/prefix/api/themes/install');
                    if (scenario.failure) throw scenario.failure;
                    return {status: scenario.status, json: async () => {
                        if (scenario.jsonFailure) throw scenario.jsonFailure;
                        return {...scenario.data};
                    }};
                }
            });
            vm.runInContext(fs.readFileSync('app/static/js/settings/themes.js', 'utf8'), context);
            const owner = context.DOCSightSettings.themes({showToast: (...args) => toasts.push(args)});
            owner.refreshRegistry();
            await tick();
            assert.equal(buttons.length, 1);
            buttons[0].click();
            await tick();
            assert.equal(requests[1].options.method, 'POST');
            assert.equal(requests[1].options.headers['Content-Type'], 'application/json');
            assert.deepEqual(JSON.parse(requests[1].options.body), {id: theme.id, download_url: theme.download_url});
            assert.deepEqual(toasts, [[scenario.expected, !!scenario.success]]);
            assert.deepEqual(requests.map(request => request.url), [
                '/prefix/api/themes/registry', '/prefix/api/themes/install',
                ...(scenario.success ? ['/prefix/api/themes/registry'] : [])
            ]);
            assert.equal(buttons.length, scenario.success ? 2 : 1);
        });
    }
});
