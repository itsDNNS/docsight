'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(
    path.resolve(__dirname, '../../app/modules/journal/static/main.js'),
    'utf8'
);

function functionBody(name, nextName) {
    const start = source.indexOf(`function ${name}(`);
    const end = source.indexOf(`function ${nextName}(`, start + 1);
    assert.notEqual(start, -1, `${name} must exist`);
    assert.notEqual(end, -1, `${nextName} must follow ${name}`);
    return source.slice(start, end);
}

test('Journal attachments do not interpolate data into executable HTML', () => {
    const attachments = functionBody('renderAttachments', 'saveEntry');

    assert.doesNotMatch(attachments, /item\.innerHTML\s*=/);
    assert.doesNotMatch(attachments, /\.(?:innerHTML|outerHTML)\s*=|insertAdjacentHTML|\bonclick\b/);
});

test('Journal PDF actions do not interpolate incident names into inline handlers', () => {
    const timeline = functionBody('renderIncidentTimeline', '_renderTimelineChart');

    assert.doesNotMatch(timeline, /onclick=["']downloadIncidentPdf/);
});

const hostile = String.raw`'"\\'"\\');globalThis.injected = true;//<img src=x onerror="globalThis.injected=true">&quot;`.repeat(3);

// This DOM records HTML sinks without parsing them. Unexpected HTML construction
// fails immediately; listener dispatch never evaluates strings. URL properties
// record the assigned value (browser URL normalization is outside this test).
function journalHarness() {
    const nodes = new Map();
    const created = [];
    const htmlWrites = [];
    class Element {
        constructor(tagName) {
            this.tagName = tagName;
            this.children = [];
            this.className = '';
            this.style = {};
            this.listeners = new Map();
            this.disabled = false;
            this.clickCount = 0;
            this._text = '';
        }
        set textContent(value) {
            this._text = String(value);
            this.children = [];
        }
        get textContent() {
            return this._text + this.children.map(child => child.textContent).join('');
        }
        set innerHTML(value) {
            assert.doesNotMatch(value, /<[^>]*\son\w+\s*=/i, 'HTML must not contain inline handlers');
            assert.ok(
                value === '' || this.allowHeaderHTML || this.allowChartHTML ||
                (this.className === 'incident-timeline-pdf-btn' && value.startsWith('<svg ')),
                'Attachment data must not reach an HTML sink'
            );
            htmlWrites.push({node: this, value});
            this._text = '';
            this.children = [];
        }
        get innerHTML() {
            assert.fail('Do not read DOM-produced HTML for later restoration');
        }
        appendChild(child) {
            this.children.push(child);
            return child;
        }
        addEventListener(type, listener) {
            assert.equal(typeof listener, 'function');
            this.listeners.set(type, [...(this.listeners.get(type) || []), listener]);
        }
        click() {
            if (this.disabled) return;
            this.clickCount++;
            for (const listener of this.listeners.get('click') || []) {
                listener.call(this, {type: 'click', target: this});
            }
        }
        querySelector(selector) {
            for (const child of this.children) {
                if (selector === '.' + child.className) return child;
                const match = child.querySelector?.(selector);
                if (match) return match;
            }
            return null;
        }
    }
    const document = {
        createElement(tagName) {
            const node = new Element(tagName);
            created.push(node);
            return node;
        },
        createTextNode(value) { return {textContent: String(value)}; },
        getElementById(id) { return nodes.get(id) || null; },
        querySelector(selector) {
            for (const node of nodes.values()) {
                const match = node.querySelector(selector);
                if (match) return match;
            }
            return null;
        },
        addEventListener() {}
    };
    const context = vm.createContext({
        document,
        T: {},
        URLSearchParams,
        // Keep hostile values intact to test the rendering boundary even when
        // upstream URL validation would reject them in the application.
        docsightUrl: value => '/docsight' + value,
        escapeHtml: value => String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'),
        fetch: () => assert.fail('Unexpected fetch'),
        showToast: () => assert.fail('Unexpected toast')
    });
    context.window = context;
    vm.runInContext(source, context, {filename: 'journal/main.js'});
    for (const id of ['header', 'entries', 'chart-card', 'signals', 'bnetz']) {
        nodes.set('incident-timeline-' + id, document.createElement('div'));
    }
    nodes.get('incident-timeline-header').allowHeaderHTML = true;
    const chart = document.createElement('div');
    chart.className = 'incident-timeline-chart-wrap';
    chart.allowChartHTML = true;
    nodes.get('incident-timeline-chart-card').appendChild(chart);
    return {context, document, nodes, created, htmlWrites};
}

test('attachment DOM preserves hostile names, URL properties, icons and original delete arguments', () => {
    const {context, document, htmlWrites, created} = journalHarness();
    const container = document.createElement('div');
    container.appendChild(document.createElement('stale'));
    const incidentId = 'incident-' + hostile;
    const attachments = ['image/png', 'application/pdf', 'text/plain', null].map((mime_type, index) => ({
        id: index === 3 ? 123 : 'attachment-' + index + hostile,
        filename: 'file-' + index + hostile,
        mime_type
    }));
    const deleted = [];
    context.deleteAttachment = (...args) => deleted.push(args);
    context.renderAttachments(attachments, container, incidentId);

    assert.equal(container.children.length, attachments.length);
    attachments.forEach((att, index) => {
        const item = container.children[index];
        assert.equal(item.className, 'attachment-item');
        const [thumb, info] = item.children;
        if (index === 0) {
            assert.equal(thumb.tagName, 'img');
            assert.equal(thumb.className, 'attachment-thumb');
            assert.equal(thumb.src, '/docsight/api/attachments/' + att.id);
            assert.equal(thumb.alt, '');
        } else {
            assert.equal(thumb.className, 'attachment-icon');
            assert.equal(thumb.textContent, index === 1 ? '\u{1F4C4}' : '\u{1F5CE}');
        }
        assert.equal(info.className, 'attachment-info');
        const [name, actions] = info.children;
        assert.equal(name.className, 'attachment-name');
        assert.equal(name.textContent, att.filename);
        assert.equal(name.children.length, 0);
        assert.equal(actions.className, 'attachment-actions');
        const [download, remove] = actions.children;
        assert.equal(download.tagName, 'a');
        assert.equal(download.href, '/docsight/api/attachments/' + att.id);
        assert.equal(download.download, '');
        assert.equal(download.title, 'Download');
        assert.equal(download.textContent, '\u2B07');
        assert.equal(remove.tagName, 'button');
        assert.equal(remove.type, 'button');
        assert.equal(remove.title, 'Delete');
        assert.equal(remove.textContent, '\u{1F5D1}');
        assert.equal(remove.listeners.get('click').length, 1);
    });
    assert.deepEqual(deleted, []);
    // Reverse order catches listeners accidentally sharing the last attachment.
    for (const item of [...container.children].reverse()) item.children[1].children[1].children[1].click();
    assert.deepEqual(deleted, [...attachments].reverse().map(att => [att.id, incidentId]));
    assert.equal(htmlWrites.length, 0);
    assert.ok(created.every(node => node.onclick === undefined));
    assert.equal(context.injected, undefined);
    context.renderAttachments([], container, incidentId);
    assert.equal(container.children.length, 0);
});

test('PDF buttons pass raw hostile and numeric incident values through click listeners', () => {
    const {context, document, nodes, htmlWrites} = journalHarness();
    const downloads = [];
    context.downloadIncidentPdf = (...args) => downloads.push(args);
    context.T.incident_download_pdf = 'PDF label ' + hostile;
    for (const id of ['incident-' + hostile, 42]) {
        const inc = {id, name: 'incident name ' + hostile, status: 'open'};
        context.renderIncidentTimeline({incident: inc});
        const header = nodes.get('incident-timeline-header');
        assert.equal(header.children.length, 1, 'Rerender must replace the previous PDF button');
        const button = document.querySelector('.incident-timeline-pdf-btn');
        assert.ok(button, 'PDF action must be a DOM-created button');
        assert.equal(button.tagName, 'button');
        assert.equal(button.type, 'button');
        assert.equal(button.onclick, undefined);
        assert.equal(button.textContent, ' ' + context.T.incident_download_pdf);
        assert.equal(button.listeners.get('click').length, 1);
        button.click();
        assert.deepEqual(downloads.at(-1), [inc.id, inc.name]);
    }
    for (const {node, value} of htmlWrites) {
        if (node === nodes.get('incident-timeline-header')) {
            assert.ok(value.includes(context.escapeHtml('incident name ' + hostile)));
            assert.ok(!value.includes('incident-' + hostile));
            assert.doesNotMatch(value, /<button|downloadIncidentPdf/);
        } else {
            assert.ok(!value.includes(hostile));
        }
    }
    assert.equal(downloads.length, 2);
    assert.equal(context.injected, undefined);
});

for (const outcome of ['success', 'http-error', 'network-error']) {
    test(`PDF download restores static SVG and text safely after ${outcome}`, async () => {
        const {context, document, nodes, created, htmlWrites} = journalHarness();
        // Exercise download completion independently of timeline construction.
        const button = document.createElement('button');
        button.className = 'incident-timeline-pdf-btn';
        button.textContent = 'Untrusted DOM content ' + hostile;
        nodes.get('incident-timeline-header').appendChild(button);
        context.T.incident_download_pdf = outcome === 'success' ? 'Translated ' + hostile : '';
        const clicks = [];
        button.addEventListener('click', () => clicks.push('clicked'));
        const queries = {lang: 'de', name: hostile, number: 'customer-42', address: 'Somewhere & here'};
        for (const [key, value] of Object.entries(queries)) nodes.set('report-' + key, {value});
        const requests = [];
        let finishFetch;
        context.fetch = url => {
            requests.push(url);
            return new Promise((resolve, reject) => {
                finishFetch = () => outcome === 'network-error'
                    ? reject(new Error('offline'))
                    : resolve({ok: outcome === 'success', blob: async () => 'pdf-blob'});
            });
        };
        const blobs = [], revoked = [], toasts = [];
        context.URL = {
            createObjectURL: blob => { blobs.push(blob); return 'blob:report'; },
            revokeObjectURL: url => revoked.push(url)
        };
        context.showToast = (...args) => toasts.push(args);
        const incidentId = 'incident-' + hostile;
        const incidentName = 'name-' + hostile;
        context.downloadIncidentPdf(incidentId, incidentName);
        assert.equal(button.disabled, true);
        assert.equal(button.textContent, '\u23F3');
        assert.deepEqual(requests, ['/docsight/api/incidents/' + incidentId + '/report?' + new URLSearchParams(queries)]);
        finishFetch();
        await new Promise(resolve => setImmediate(resolve));

        assert.equal(button.disabled, false);
        assert.equal(button.textContent, ' ' + (context.T.incident_download_pdf || 'Download PDF Report'));
        assert.equal(htmlWrites.length, 1);
        assert.equal(htmlWrites[0].node, button);
        assert.match(htmlWrites[0].value, /^<svg .*width="16" height="16"/);
        assert.match(htmlWrites[0].value, /<path .*<polyline .*<line .*<\/svg>$/);
        assert.ok(!htmlWrites[0].value.includes(hostile));
        button.click();
        assert.deepEqual(clicks, ['clicked'], 'Restoring content must preserve the listener');
        const anchors = created.filter(node => node.tagName === 'a');
        if (outcome === 'success') {
            assert.equal(anchors.length, 1);
            assert.equal(anchors[0].href, 'blob:report');
            assert.equal(anchors[0].clickCount, 1);
            assert.equal(anchors[0].download, 'DOCSight_Beschwerde_' + incidentName.replace(/[^a-zA-Z0-9]/g, '_') + '_' + new Date().toISOString().slice(0, 10) + '.pdf');
            assert.deepEqual(blobs, ['pdf-blob']);
            assert.deepEqual(revoked, ['blob:report']);
            assert.deepEqual(toasts, []);
        } else {
            assert.equal(anchors.length, 0);
            assert.deepEqual(revoked, []);
            assert.deepEqual(toasts, [['Error generating report', 'error']]);
        }
        assert.equal(context.injected, undefined);
    });
}
