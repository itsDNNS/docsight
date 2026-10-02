'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');

const contracts = require('../../app/static/js/browser-contracts.js');

const translations = {refresh_success: 'Updated', month_names: ['Jan', 'Feb']};

test('dashboard bootstrap accepts the strict expected shape and null language', () => {
    const parsed = contracts.parseDashboardBootstrapText(JSON.stringify({
        translations,
        language: null,
        temperatureUnit: 'celsius',
        connectionMonitorAvailable: false,
        timeZone: 'Europe/Berlin'
    }));
    assert.deepEqual(parsed, {
        translations,
        language: null,
        temperatureUnit: 'celsius',
        connectionMonitorAvailable: false,
        timeZone: 'Europe/Berlin'
    });
});

test('dashboard bootstrap falls back to the browser zone for a zone the browser does not know', () => {
    const parsed = contracts.parseDashboardBootstrapText(JSON.stringify({
        translations,
        language: 'en',
        temperatureUnit: 'celsius',
        connectionMonitorAvailable: false,
        timeZone: 'Not/AZone'
    }));
    assert.equal(parsed.timeZone, null);
});

test('bootstrap parsing fails closed for absent, malformed, wrong, and unexpected data', () => {
    for (const value of [null, '', '{', 'null', '[]', '{"translations":{}}']) {
        assert.throws(() => contracts.parseDashboardBootstrapText(value), /bootstrap/i);
    }
    assert.throws(() => contracts.parseDashboardBootstrapText(JSON.stringify({
        translations: {},
        language: 'en',
        temperatureUnit: 'kelvin',
        connectionMonitorAvailable: true,
        timeZone: null
    })), /bootstrap/i);
    assert.throws(() => contracts.parseDashboardBootstrapText(JSON.stringify({
        translations: {constructor: 'unsafe'},
        language: 'en',
        temperatureUnit: 'celsius',
        connectionMonitorAvailable: true,
        timeZone: null
    })), /bootstrap/i);
    assert.throws(() => contracts.parseDashboardBootstrapText(JSON.stringify({
        translations: {},
        language: 'en',
        temperatureUnit: 'celsius',
        connectionMonitorAvailable: true,
        timeZone: 3600
    })), /bootstrap/i);
    assert.throws(() => contracts.parseDashboardBootstrapText(JSON.stringify({
        translations: {},
        language: 'en',
        temperatureUnit: 'celsius',
        connectionMonitorAvailable: true,
        timeZone: null,
        token: 'unexpected'
    })), /bootstrap/i);
});

test('timestamps render absolute instants in the configured zone and keep local wall-clock values', () => {
    const fmt = (value, options) => contracts.formatTimestamp(value, {timeZone: 'Europe/Berlin', ...options});

    assert.equal(fmt('2026-10-02T06:52:37Z', {locale: 'en-GB', seconds: true}), '02/10/2026, 08:52:37');
    assert.equal(fmt('2026-10-02T06:52:37+00:00', {locale: 'de', seconds: true}), '02.10.2026, 08:52:37');
    assert.equal(fmt('2026-10-02T08:52:37', {locale: 'de', seconds: true}), '02.10.2026, 08:52:37');
    assert.equal(fmt('2026-10-02 08:52', {locale: 'de'}), '02.10.2026, 08:52');
    assert.equal(fmt('2026-10-01', {locale: 'de'}), '01.10.2026');
    assert.equal(fmt('2026-10-01', {locale: 'en-US'}), '10/01/2026');
    assert.equal(fmt(1790916757, {locale: 'de', style: 'time'}), '06:52');
    assert.equal(fmt(1790916757000, {locale: 'de', style: 'time'}), '06:52');
    assert.equal(fmt(new Date('2026-01-15T12:00:00Z'), {locale: 'de'}), '15.01.2026, 13:00');
});

test('timestamp formatting handles summer time, empty, invalid, and unknown zones', () => {
    assert.equal(contracts.formatTimestamp('2026-03-29T00:30:00Z', {locale: 'de', timeZone: 'Europe/Berlin'}), '29.03.2026, 01:30');
    assert.equal(contracts.formatTimestamp('2026-03-29T01:30:00Z', {locale: 'de', timeZone: 'Europe/Berlin'}), '29.03.2026, 03:30');
    assert.equal(contracts.formatTimestamp('', {}), '');
    assert.equal(contracts.formatTimestamp(null, {}), '');
    assert.equal(contracts.formatTimestamp('not a date', {}), 'not a date');
    assert.equal(
        contracts.formatTimestamp('2026-10-02T06:52:37Z', {locale: 'de', timeZone: 'Not/AZone'}),
        contracts.formatTimestamp('2026-10-02T06:52:37Z', {locale: 'de'})
    );
});

test('settings bootstrap validates modules, cooldown fallback, secrets, and time data', () => {
    const base = {
        translations: {general: 'General'},
        modules: [{id: 'docsight.example', labelKey: 'docsight.example.title', name: 'Example'}],
        serverOffsetMin: 60,
        serverTimezone: 'Europe/Berlin',
        language: 'de',
        currentTimezone: null,
        notificationCooldowns: '{"warning":15}',
        driverHints: {},
        moduleSecretFields: ['example_token'],
        savedModuleSecretFields: []
    };
    const parsed = contracts.parseSettingsBootstrapText(JSON.stringify(base));
    assert.deepEqual(parsed.notificationCooldowns, {warning: 15});
    assert.equal(parsed.currentTimezone, '');

    const compatibleExtension = contracts.parseSettingsBootstrapText(JSON.stringify({
        ...base,
        modules: [{id: 'community..example', labelKey: 'community.example.title', name: 'Community Example'}],
        moduleSecretFields: ['community secret/token'],
        savedModuleSecretFields: ['community secret/token']
    }));
    assert.equal(compatibleExtension.modules[0].id, 'community..example');
    assert.deepEqual(compatibleExtension.moduleSecretFields, ['community secret/token']);
    assert.deepEqual(contracts.parseSettingsBootstrapText(JSON.stringify({
        ...base,
        notificationCooldowns: 'malformed'
    })).notificationCooldowns, {});
    assert.throws(() => contracts.parseSettingsBootstrapText(JSON.stringify({
        ...base,
        modules: [{id: '../../escape', labelKey: 'x', name: 'Bad'}]
    })), /bootstrap/i);
    assert.throws(() => contracts.parseSettingsBootstrapText(JSON.stringify({
        ...base,
        savedModuleSecretFields: ['not_declared']
    })), /bootstrap/i);
});

test('setup bootstrap and pure driver defaults preserve explicit user choices', () => {
    const parsed = contracts.parseSetupBootstrapText(JSON.stringify({
        translations: {not_required: 'Not required'},
        indexUrl: '/docsight/',
        loginUrl: '/docsight/login',
        driverHints: {
            fritzbox: {default_url: 'http://192.168.178.1', default_user: '', username_required: false, credentials_required: true},
            demo: {default_url: null, default_user: null, username_required: false, credentials_required: false}
        }
    }));
    assert.equal(parsed.driverHints.fritzbox.default_url, 'http://192.168.178.1');

    assert.deepEqual(contracts.selectSetupDriverState(parsed.driverHints, 'fritzbox', '', 'saved'), {
        url: 'http://192.168.178.1',
        credentialsVisible: true,
        usernameEnabled: false,
        username: '',
        usernamePlaceholder: 'Not required'
    });
    assert.equal(
        contracts.selectSetupDriverState(parsed.driverHints, 'fritzbox', 'http://custom.test', '').url,
        'http://custom.test'
    );
    assert.equal(
        contracts.selectSetupDriverState(parsed.driverHints, 'demo', '', '').credentialsVisible,
        false
    );
    assert.throws(() => contracts.parseSetupBootstrapText(JSON.stringify({
        translations: {},
        indexUrl: '/',
        loginUrl: '/login',
        driverHints: {bad: {default_url: 'javascript:alert(1)'}}
    })), /bootstrap/i);
    assert.throws(() => contracts.parseSetupBootstrapText(JSON.stringify({
        translations: {},
        indexUrl: '//evil.test/',
        loginUrl: '/login',
        driverHints: {}
    })), /bootstrap/i);
});

test('last-known timestamp formatting keeps the legacy missing and error fallbacks', () => {
    assert.equal(contracts.formatLastKnownTimestamp(null, String), '');
    assert.equal(contracts.formatLastKnownTimestamp('', String), '');
    assert.equal(contracts.formatLastKnownTimestamp('2026-08-15T12:00:00Z', value => 'local:' + value), 'local:2026-08-15T12:00:00Z');
    assert.equal(contracts.formatLastKnownTimestamp('legacy-value', () => { throw new Error('bad date'); }), 'legacy-value');
});

test('service-worker policy is prefix-scoped and only disables local development by default', () => {
    assert.deepEqual(
        contracts.computeServiceWorkerPolicy('localhost', '', 'https://example.test/docsight/'),
        {action: 'cleanup', scopeHref: 'https://example.test/docsight/', cacheNamespace: 'docsight-%2Fdocsight%2F-'}
    );
    assert.equal(
        contracts.computeServiceWorkerPolicy('127.0.0.1', '?enable-sw-test=1', 'https://example.test/docsight/').action,
        'register'
    );
    assert.equal(
        contracts.computeServiceWorkerPolicy('docsight.test', '', 'https://docsight.test/').cacheNamespace,
        'docsight-%2F-'
    );
    for (const unsafe of ['not a url', 'javascript:alert(1)', 'https://example.test/docsight/?query=1']) {
        assert.throws(() => contracts.computeServiceWorkerPolicy('localhost', '', unsafe), /scope/i);
    }
});
