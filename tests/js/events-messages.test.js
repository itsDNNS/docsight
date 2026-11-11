'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const root = path.resolve(__dirname, '../..');
const german = JSON.parse(fs.readFileSync(path.join(root, 'app/i18n/de.json'), 'utf8'));

function formatter() {
    const context = {
        T: german, URLSearchParams, setInterval() {}, docsightUrl: url => url, formatDocsightTime: String,
        fetch: () => new Promise(() => {}),
        escapeHtml: value => String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'),
        document: {getElementById: () => null, querySelectorAll: () => [], addEventListener() {}, documentElement: {lang: 'de'}},
    };
    context.window = context;
    vm.createContext(context);
    for (const file of ['view-state.js', 'event-log-data.js', 'events.js']) {
        vm.runInContext(fs.readFileSync(path.join(root, 'app/static/js', file), 'utf8'), context, {filename: file});
    }
    return ev => context.formatEventMessage(ev).replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
}

// Server-side messages stay English for exports and notifications; the UI renders from details.
const EVENTS = [
    {event_type: 'modulation_change', message: 'Modulation dropped on 1 channel(s)',
     details: {direction: 'downgrade', changes: [{direction: 'DS', channel: 5, prev: '256QAM', current: '64QAM', rank_drop: 2}]}},
    {event_type: 'snr_change', message: 'DS SNR/MER health changed to warning (min: 32.1 dB)',
     details: {prev: 34, current: 32.1, threshold: 'warning',
               affected_channels: Array.from({length: 8}, (_, i) => ({channel: i + 1, prev: 34, current: 32 - i, delta: -2 - i}))}},
    {event_type: 'modem_restart_detected', message: 'Detected modem restart or counter reset pattern',
     details: {affected_channels: [1, 2, 3], total_channels: 4}},
    {event_type: 'device_sw_update', message: 'Prior uptime: 1d 2h 3m, SW: v1 → v2, Reason: firmware upgrade',
     details: {old_sw: 'v1', new_sw: 'v2', prior_uptime: 93780, ip_changed: true, reboot_reason: 'firmware upgrade'}},
    {event_type: 'device_reboot', message: 'Prior uptime: 2h 0m', details: {prior_uptime: 7200, ip_changed: false}},
    {event_type: 'cm_packet_loss_warning', message: 'Target 2: 4.5% packet loss over 60s',
     details: {target_id: 2, packet_loss_pct: 4.5, window_seconds: 60}},
    {event_type: 'smart_capture_triggered', message: 'Speedtest triggered by health_change',
     details: {trigger_type: 'health_change', source_event: 'Health changed from good to marginal'}},
];

test('event messages render from details in the UI language', () => {
    const format = formatter();
    const english = /\b(?:dropped|improved|channel\(s\)|rank|affected|Detected|Prior uptime|Reason|triggered|packet loss over|Health changed)\b/;
    for (const ev of EVENTS) {
        const text = format(ev);
        assert.doesNotMatch(text, english, `${ev.event_type}: ${text}`);
    }
    assert.match(format(EVENTS[0]), /Kanäle mit niedrigerer Modulation: 1/);
    assert.match(format(EVENTS[0]), /DS Kanal 5/);
    assert.match(format(EVENTS[0]), /2 QAM-Stufe\(n\)/);
    assert.match(format(EVENTS[1]), /\+2 weitere Kanäle/);
    assert.match(format(EVENTS[3]), /Firmware v1 v2 · Laufzeit davor 1 d 2 h 3 min · WAN-IP geändert · Grund: firmware upgrade/);
    assert.match(format(EVENTS[6]), /Speedtest ausgelöst durch Gesundheitsänderung/);
});

// Connection Monitor events name the target as it was when they happened (#1106).
function rawFormatter() {
    const context = {
        T: german, URLSearchParams, setInterval() {}, docsightUrl: url => url, formatDocsightTime: String,
        fetch: () => new Promise(() => {}),
        escapeHtml: value => String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'),
        document: {getElementById: () => null, querySelectorAll: () => [], addEventListener() {}, documentElement: {lang: 'de'}},
    };
    context.window = context;
    vm.createContext(context);
    for (const file of ['view-state.js', 'event-log-data.js', 'events.js']) {
        vm.runInContext(fs.readFileSync(path.join(root, 'app/static/js', file), 'utf8'), context, {filename: file});
    }
    return context;
}

const CM_DETAILS = {
    cm_target_unreachable: {consecutive_timeouts: 5},
    cm_target_recovered: {was_down_for: 7},
    cm_packet_loss_warning: {packet_loss_pct: 4.5, window_seconds: 60},
};
const cmEvent = (type, identity) => ({
    event_type: type, message: 'English raw message',
    details: Object.assign({target_id: 3}, identity, CM_DETAILS[type]),
});

test('connection events name the target snapshot in the UI language', () => {
    const format = formatter();
    const named = {target_label: 'Cloudflare DNS', target_host: '1.1.1.1'};
    assert.equal(format(cmEvent('cm_target_unreachable', named)), 'Cloudflare DNS (1.1.1.1): 5 Zeitüberschreitungen in Folge');
    assert.equal(format(cmEvent('cm_target_recovered', named)), 'Cloudflare DNS (1.1.1.1): wieder erreichbar nach 7 Zeitüberschreitungen');
    assert.equal(format(cmEvent('cm_packet_loss_warning', named)), 'Cloudflare DNS (1.1.1.1): 4,5 % Paketverlust über 60 s');
    assert.equal(format(cmEvent('cm_packet_loss_warning', {target_label: '', target_host: '1.1.1.1'})), '1.1.1.1: 4,5 % Paketverlust über 60 s');
    assert.equal(format(cmEvent('cm_packet_loss_warning', {target_label: '1.1.1.1', target_host: '1.1.1.1'})), '1.1.1.1: 4,5 % Paketverlust über 60 s');
    assert.equal(format(cmEvent('cm_packet_loss_warning', {target_label: 'Gateway', target_host: ''})), 'Gateway: 4,5 % Paketverlust über 60 s');
});

test('older connection events without a snapshot name only the target ID', () => {
    const format = formatter();
    for (const type of Object.keys(CM_DETAILS)) {
        const text = format(cmEvent(type, {}));
        assert.match(text, /^Ziel-ID 3: /, `${type}: ${text}`);
        assert.doesNotMatch(text, /English|gelöscht/, `${type}: ${text}`);
    }
    assert.equal(format(cmEvent('cm_target_unreachable', {target_label: '', target_host: ''})), 'Ziel-ID 3: 5 Zeitüberschreitungen in Folge');
    assert.equal(format(cmEvent('cm_target_unreachable', {target_label: null, target_host: null})), 'Ziel-ID 3: 5 Zeitüberschreitungen in Folge');
    assert.equal(format(cmEvent('cm_target_recovered', {target_label: null, target_host: '1.1.1.1'})), '1.1.1.1: wieder erreichbar nach 7 Zeitüberschreitungen');
    assert.equal(format(cmEvent('cm_packet_loss_warning', {target_label: 'Gateway', target_host: null})), 'Gateway: 4,5 % Paketverlust über 60 s');
});

test('connection event types have translated labels', () => {
    const context = rawFormatter();
    for (const type of Object.keys(CM_DETAILS)) {
        assert.equal(context._eventTypeLabel(type), german['event_type_' + type], type);
    }
});

test('target labels and addresses are escaped and never treated as replacement patterns', () => {
    const context = rawFormatter();
    const identity = {target_label: '<img src=x onerror=alert(1)> $& $1 {loss}', target_host: '<b>h</b> $` {window} {count}'};
    for (const type of Object.keys(CM_DETAILS)) {
        const html = context.formatEventMessage(cmEvent(type, identity));
        assert.doesNotMatch(html, /<img|<b>/, `${type}: ${html}`);
        assert.ok(html.includes('&lt;img src=x onerror=alert(1)&gt; $&amp; $1 {loss} (&lt;b&gt;h&lt;/b&gt; $` {window} {count})'), `${type}: ${html}`);
    }
});
