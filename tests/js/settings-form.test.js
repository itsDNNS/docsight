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
            classList: {contains: name => classes.has(name), toggle: (name, on) => on ? classes.add(name) : classes.delete(name)},
            closest: () => null,
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
    const fields = [url, secret, fresh, toggle, hidden, module, language, timezone, isp];
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
    element('toast'); element('module-restart-banner');
    element('isp-other-row'); element('isp-icon-preview');
    const document = {getElementById: id => nodes.get(id) || null, querySelectorAll: () => [], querySelector: () => null,
        documentElement: {getAttribute: () => 'dark'}, activeElement: null,
        addEventListener: (name, fn) => listeners.set(name, fn)};
    const context = vm.createContext({document, T: {}, currentLang: 'en', currentTz: 'UTC',
        setTimeout: fn => timers.push(fn), docsightUrl: path => '/prefix' + path,
        docsightConfirm: () => Promise.resolve(true),
        fetch: (url, options) => new Promise((resolve, reject) => requests.push({url,
            data: JSON.parse(options.body), reject,
            finish: (success = true) => resolve({ok: success, json: () => Promise.resolve({success})})})),
        localStorage: {getItem: () => null}, SECTION_TITLES: {}, history: {replaceState() {}, pushState() {}},
        location: {hash: '', reload: () => { context.reloads++; }}, reloads: 0,
        addEventListener: (name, fn) => listeners.set(name, fn)});
    context.window = context;
    for (const name of ['form-state', 'form']) vm.runInContext(fs.readFileSync(`app/static/js/settings/${name}.js`, 'utf8'), context);
    const owner = context.DOCSightSettings.form({state: context.DOCSightSettings.state, showsSaveFooter: () => true});
    if (bootstrap) {
        for (const name of ['navigation', 'tokens', 'connections', 'notifications', 'backups', 'themes', 'smart-capture', 'module-registry']) {
            vm.runInContext(fs.readFileSync(`app/static/js/settings/${name}.js`, 'utf8'), context);
        }
        vm.runInContext(fs.readFileSync('app/static/js/settings.js', 'utf8'), context);
        listeners.get('DOMContentLoaded')();
    } else owner.init();
    return {context, owner, requests, timers, url, secret, fresh, toggle, hidden, module, language, timezone, footer, error,
        edit(el, value, trusted = true) { document.activeElement = el; el.value = value; el.dispatch('input', trusted); },
        dirty() { let blocked = false; listeners.get('beforeunload')({preventDefault() { blocked = true; }}); return blocked; }};
}

test('FIFO captures edits at execution and survives a rejected first request', async () => {
    const f = fixture();
    f.toggle.checked = true;
    const first = f.owner.saveInstantly();
    await tick();
    const second = f.owner.saveInstantly();
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
    const first = f.owner.saveInstantly();
    await tick();
    f.requests[0].finish();
    await tick();
    assert.equal(f.secret.value, '');
    assert.equal(f.requests[1].url, '/prefix/api/modules/batch');
    f.requests[1].finish(false);
    assert.equal(await first, false);
    assert.equal(f.footer.classList.contains('visible'), true);
    const retry = f.owner.saveInstantly();
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
    const job = f.owner.saveInstantly();
    await tick();
    f.edit(f.secret, 'second-secret');
    f.edit(f.hidden, 'later-hidden');
    f.edit(f.url, 'later-url');
    f.requests[0].finish();
    await job;
    assert.equal(f.secret.value, 'second-secret');
    assert.equal(f.footer.classList.contains('visible'), true);
    assert.equal(f.dirty(), true);
    const retry = f.owner.saveInstantly();
    await tick();
    assert.equal(f.requests[1].data.modem_password, 'second-secret');
    f.requests[1].finish();
    await retry;
    assert.equal(f.dirty(), false);
    assert.equal(f.fresh.value, '');
    assert.equal(f.fresh.dataset.savedSecret, 'true');
});

test('instant-only saves never show a footer or success toast, autofill stays masked', async () => {
    const f = fixture();
    f.edit(f.secret, 'autofill', false);
    f.context.document.activeElement = f.url;
    f.secret.dispatch('input', true);
    assert.equal(f.dirty(), false);
    f.toggle.checked = true;
    f.toggle.dispatch('change');
    assert.equal(f.footer.classList.contains('visible'), false);
    await tick();
    assert.equal(f.requests[0].data.modem_password, '••••••••');
    f.requests[0].finish();
    await tick();
    assert.equal(f.footer.classList.contains('visible'), false);
    assert.equal(f.dirty(), false);
    assert.equal(f.timers.length, 0);
});

test('reload uses confirmed values and checks for later edits and queued work at timer execution', async () => {
    const f = fixture();
    f.edit(f.language, 'de');
    const first = f.owner.saveInstantly();
    await tick();
    f.requests[0].finish();
    await first;
    f.edit(f.url, 'unsaved');
    f.timers.shift()();
    assert.equal(f.context.reloads, 0);
    const second = f.owner.saveInstantly();
    await tick();
    f.requests[1].finish();
    await second;
    f.timers.shift()();
    assert.equal(f.context.reloads, 1);
});

test('an unconfirmed language edit during an earlier save cannot cause a reload', async () => {
    const f = fixture();
    const job = f.owner.saveInstantly();
    await tick();
    f.edit(f.language, 'de');
    f.requests[0].finish();
    await job;
    assert.equal(f.timers.length, 0);
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
