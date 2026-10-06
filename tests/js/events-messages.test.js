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
