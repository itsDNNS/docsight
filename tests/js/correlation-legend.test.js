'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const legend = require('../../app/static/js/correlation-legend.js');

const event = (event_type, severity) => ({source: 'event', event_type, severity});

test('operational events start hidden, every other type and severity starts shown', () => {
    const filter = legend.eventFilter();
    assert.equal(filter.allowed(event('monitoring_started', 'info')), false);
    assert.equal(filter.allowed(event('health_change', 'warning')), true);
    assert.equal(filter.allowed({source: 'event'}), true, 'a missing type counts as unknown');
    assert.deepEqual({...filter.types}, {monitoring_started: false, health_change: true, unknown: true});
    assert.deepEqual({...filter.severity('health_change')}, {info: true, warning: true, critical: true});
});

test('a type or one severity of it can be filtered out on its own', () => {
    const filter = legend.eventFilter();
    filter.severity('error_spike').critical = false;
    assert.equal(filter.allowed(event('error_spike', 'critical')), false);
    assert.equal(filter.allowed(event('error_spike', 'warning')), true);
    filter.types.error_spike = false;
    assert.equal(filter.allowed(event('error_spike', 'warning')), false);
});

test('the summary counts per type and severity and how many pass', () => {
    const filter = legend.eventFilter();
    const summary = filter.summary([event('health_change', 'warning'), event('health_change', 'critical'),
        event('monitoring_started', 'info'), event('health_change', 'bogus')]);
    assert.deepEqual(summary.types, {health_change: 3, monitoring_started: 1});
    assert.deepEqual(summary.severities, {health_change: {warning: 1, critical: 1, info: 1}, monitoring_started: {info: 1}});
    assert.equal(summary.visible, 3);
    assert.equal(summary.total, 4);
});

const colors = {dsPower: 'p', txPower: 't', snr: 's', health: {good: 'g'}, download: 'd', upload: 'u', warn: 'w',
    temperature: 'temp', segmentDs: 'sd', segmentUs: 'su', accent: 'a'};
const state = over => Object.assign({colors, modem: [], speedtest: [], events: [], weather: [], segment: [],
    reachabilityBuckets: [], hasPowerData: false, hasTxData: false, hasErrorData: false}, over);

test('legend entries follow the data in display order', () => {
    const filter = legend.eventFilter();
    const all = legend.items(state({modem: [{}], hasPowerData: true, hasTxData: true, hasErrorData: true,
        speedtest: [{}], events: [event('health_change', 'info')], weather: [{}], segment: [{}], reachabilityBuckets: [{}]}),
    filter, {}, true);
    assert.deepEqual(all.map(item => item.metric), ['dsPower', 'txPower', 'snr', 'signalState', 'errors', 'download',
        'upload', 'events', 'temperature', 'segmentDs', 'segmentUs', 'reachability']);
    assert.equal(all.find(item => item.metric === 'events').events.total, 1);
    assert.match(all.find(item => item.metric === 'temperature').label, /°F/);

    const modemOnly = legend.items(state({modem: [{}]}), filter, {chart_snr: 'Störabstand'}, false);
    assert.deepEqual(modemOnly.map(item => item.metric), ['snr', 'signalState']);
    assert.match(modemOnly[0].label, /Störabstand/);
});

test('a legend click never hides the last visible series', () => {
    const visible = {snr: true, events: false};
    assert.equal(legend.toggle(visible, 'snr'), false);
    assert.equal(visible.snr, true);
    assert.equal(legend.toggle(visible, 'events'), true);
    assert.equal(legend.toggle(visible, 'snr'), true);
    assert.deepEqual(visible, {snr: false, events: true});
});
