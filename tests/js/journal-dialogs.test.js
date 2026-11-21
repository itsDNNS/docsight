'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

// The journal's scripts, in the order the page loads them.
const SCRIPTS = ['app/static/js/utils.js', 'app/static/js/trusted-html.js',
    'app/modules/journal/static/js/journal-entry.js', 'app/modules/journal/static/js/journal-import.js',
    'app/modules/journal/static/js/journal-timeline.js', 'app/modules/journal/static/js/journal-cases.js',
    'app/modules/journal/static/main.js'];

class Element {
    constructor(tagName) {
        this.tagName = tagName;
        this.children = [];
        this.attributes = {};
        this.listeners = {};
        this.className = '';
        this.innerHTML = '';
        this.value = '';
        this.hidden = false;
        this.disabled = false;
        const classes = () => this.className.split(' ').filter(Boolean);
        this.classList = {
            contains: name => classes().includes(name),
            add: name => { if (!classes().includes(name)) this.className = [...classes(), name].join(' '); },
            remove: name => { this.className = classes().filter(c => c !== name).join(' '); },
            toggle: (name, on) => (on ? this.classList.add(name) : this.classList.remove(name)),
        };
    }
    // Like the DOM: setting the text replaces the children.
    set textContent(value) { this.text = String(value); this.children = []; }
    get textContent() { return this.text || ''; }
    setAttribute(name, value) { this.attributes[name] = String(value); }
    getAttribute(name) { return this.attributes[name]; }
    appendChild(child) { this.children.push(child); return child; }
    replaceChildren() { this.children = []; }
    querySelectorAll(selector) { return this.children.filter(child => child.classList.contains(selector.slice(1))); }
    addEventListener(type, listener) { this.listeners[type] = listener; }
    click() { (this.onclick || this.listeners.click)(); }
}

function journal(fetchAnswers) {
    const nodes = new Map();
    const trace = [];
    const requests = [];
    const record = name => (...args) => { trace.push([name, ...args]); };
    const document = {
        documentElement: {lang: 'en'},
        createElement: tagName => new Element(tagName),
        getElementById(id) {
            if (!nodes.has(id)) nodes.set(id, new Element('div'));
            return nodes.get(id);
        },
        querySelector: () => null,
        querySelectorAll: () => [],
        addEventListener() {},
    };
    const context = vm.createContext({
        document, FormData,
        T: {icon_auto: 'Auto', delete_all_confirm: 'Delete {n}?', network_error: 'Network error', delete_failed: 'Delete failed', error_prefix: 'Failed', import_selected: 'Import selected',
            delete_all_success: 'entries deleted', import_success: 'imported', entries_assigned: 'assigned', entries_unassigned: 'unassigned'},
        docsightUrl: path => '/base' + path,
        fetch(url, options) {
            const {method, headers, body} = options || {};
            requests.push([url, method, headers && JSON.parse(JSON.stringify(headers)),
                typeof body === 'string' ? JSON.parse(body) : body && body.constructor.name]);
            const answer = fetchAnswers.shift();
            if (answer === 'offline') return Promise.reject(new TypeError('Failed to fetch'));
            return Promise.resolve({status: answer.status, ok: answer.status < 300,
                json: () => (answer.body === undefined ? Promise.reject(new SyntaxError('not JSON')) : Promise.resolve(answer.body))});
        },
        showToast: record('toast'),
        docsightConfirm: () => Promise.resolve(true),
        todayStr: () => '2026-11-21',
        DOCSightModal: {open: () => {}, close: record('close')},
    });
    context.window = context;
    for (const file of SCRIPTS) vm.runInContext(fs.readFileSync(file, 'utf8'), context, {filename: file});
    for (const name of ['loadJournal', 'loadIncidents', 'exitBulkMode', 'renderImportPreview', 'setImportValidationState']) {
        context[name] = record(name);
    }
    const set = (id, value) => { document.getElementById(id).value = value; };
    return {context, nodes, set, trace, requests, settle: () => new Promise(resolve => setImmediate(resolve))};
}

const JSON_HEADERS = {'Content-Type': 'application/json'};

// Each dialog request: how to start it, what it sends, what a good answer does,
// the text an error answer without a message falls back to, and the dialog
// state it leaves after a good answer and after any failure.
const SITES = [
    {
        name: 'creating an entry',
        start({context, set}) { set('entry-title-input', ' Outage '); context.saveEntry(); },
        request: ['/base/api/journal', 'POST', JSON_HEADERS, {date: '', title: 'Outage', description: '', icon: '', incident_id: null}],
        answer: {id: 7},
        done: [['loadJournal'], ['loadIncidents'], ['toast', 'Entry saved', 'ok']],
        fallback: 'Error',
        state: [({nodes}) => nodes.get('entry-id').value, {done: 7, failed: ''}],
    },
    {
        name: 'updating an entry',
        start({context, set}) { set('entry-id', '5'); set('entry-title-input', 'Call'); context.saveEntry(); },
        request: ['/base/api/journal/5', 'PUT', JSON_HEADERS, {date: '', title: 'Call', description: '', icon: '', incident_id: null}],
        answer: {id: 5},
        done: [['loadJournal'], ['loadIncidents'], ['close', 'entry-modal']],
        fallback: 'Error',
    },
    {
        name: 'saving a case',
        start({context, set}) { set('incident-container-name', 'Slow line'); context.saveIncident(); },
        request: ['/base/api/incidents', 'POST', JSON_HEADERS, {name: 'Slow line', description: '', status: '', start_date: '', end_date: '', icon: ''}],
        answer: {id: 3},
        done: [['close', 'incident-container-modal'], ['loadIncidents'], ['loadJournal']],
        fallback: 'Error',
    },
    {
        name: 'deleting all entries',
        start({context}) { context.document.querySelectorAll = () => [{}, {}]; context.deleteAllEntries(); },
        request: ['/base/api/journal/batch', 'DELETE', JSON_HEADERS, {all: true, confirm: 'DELETE_ALL'}],
        answer: {deleted: 2},
        done: [['toast', '2 entries deleted', 'ok'], ['loadJournal']],
        fallback: 'Delete failed',
    },
    {
        name: 'previewing an import',
        start({context}) { context.handleImportFile({files: [{name: 'notes.csv', size: 10}]}); },
        request: ['/base/api/journal/import/preview?lang=en', 'POST', undefined, 'FormData'],
        answer: {rows: []},
        done: [['setImportValidationState', 'Parsing file and checking rows...', 'progress'], ['renderImportPreview', {rows: []}]],
        error: text => [['setImportValidationState', 'Parsing file and checking rows...', 'progress'], ['setImportValidationState', text, 'error']],
        fallback: 'Failed',
        state: [({nodes}) => [nodes.get('import-loading').hidden, nodes.get('import-upload-zone').hidden], {done: [true, true], failed: [true, false]}],
    },
    {
        name: 'confirming an import',
        start({context}) {
            context._importPreviewData = {rows: [{date: '2026-11-01', title: 'Call', description: ''}]};
            context._importSelectedIndexes = () => [0];
            context.confirmImport();
        },
        request: ['/base/api/journal/import/confirm', 'POST', JSON_HEADERS, {rows: [{date: '2026-11-01', title: 'Call', description: ''}]}],
        answer: {imported: 1, duplicates: 0},
        done: [['toast', '1 imported', 'ok'], ['close', 'import-modal'], ['loadJournal']],
        fallback: 'Failed',
        state: [({nodes}) => [nodes.get('import-confirm-btn').disabled, nodes.get('import-confirm-btn').textContent],
            {done: [false, 'Import selected'], failed: [false, 'Import selected']}],
    },
    {
        name: 'assigning entries to a case',
        start({context, set}) { context._selectedEntryIds = [1, 2]; set('journal-bulk-incident-select', '4'); context.bulkAssign(); },
        request: ['/base/api/incidents/4/assign', 'POST', JSON_HEADERS, {entry_ids: [1, 2]}],
        answer: {updated: 2},
        done: [['toast', '2 assigned', 'success'], ['exitBulkMode'], ['loadIncidents'], ['loadJournal']],
        fallback: 'Failed',
    },
    {
        name: 'removing entries from their case',
        start({context}) { context._selectedEntryIds = [1, 2]; context.bulkUnassign(); },
        request: ['/base/api/journal/unassign', 'POST', JSON_HEADERS, {entry_ids: [1, 2]}],
        answer: {updated: 2},
        done: [['toast', '2 unassigned', 'success'], ['exitBulkMode'], ['loadIncidents'], ['loadJournal']],
        fallback: 'Failed',
    },
];

const OUTCOMES = [
    ['a good answer', site => ({status: 200, body: site.answer}), site => site.done, 'done'],
    ['an error answer', () => ({status: 404, body: {error: 'Incident not found'}}), () => 'Incident not found', 'failed'],
    ['an error answer without a message', () => ({status: 500, body: {}}), site => site.fallback, 'failed'],
    ['an answer that is not JSON', () => ({status: 502}), () => 'Network error', 'failed'],
    ['no answer', () => 'offline', () => 'Network error', 'failed'],
];

for (const site of SITES) {
    for (const [outcome, answer, expected, result] of OUTCOMES) {
        test(`${site.name} after ${outcome}`, async () => {
            const harness = journal([answer(site)]);
            site.start(harness);
            await harness.settle();
            assert.deepEqual(harness.requests, [site.request]);
            const want = expected(site);
            const trace = typeof want !== 'string' ? want : (site.error ? site.error(want) : [['toast', want, 'error']]);
            assert.deepEqual(JSON.parse(JSON.stringify(harness.trace)), trace);
            if (site.state) assert.deepEqual(site.state[0](harness), site.state[1][result]);
        });
    }
}

test('bulk assignment asks for a case first and sends nothing without a selection', async () => {
    const {context, set, trace, requests, settle} = journal([]);
    context._selectedEntryIds = [1];
    context.bulkAssign();
    context._selectedEntryIds = [];
    set('journal-bulk-incident-select', '4');
    context.bulkAssign();
    context.bulkUnassign();
    await settle();
    assert.deepEqual(requests, []);
    assert.deepEqual(trace, [['toast', 'Select an incident first', 'warning']]);
});

// Both dialogs share one icon picker; only the entry dialog updates its header icon on a pick.
for (const [dialog, open, prefix, updatesHeader] of [
    ['entry', (context, id) => context.openEntryModal(id), 'entry', true],
    ['case', (context, id) => context.openIncidentModal(id), 'incident-container', false],
]) {
    test(`the ${dialog} dialog icon picker marks the saved icon and records a pick`, async () => {
        const {context, nodes, requests, settle} = journal([{status: 200, body: {id: 5, icon: 'mail', attachments: []}}]);
        open(context, 5);
        await settle();
        assert.equal(requests[0][0], dialog === 'entry' ? '/base/api/journal/5' : '/base/api/incidents/5');
        const picker = nodes.get(prefix + '-icon-picker');
        const input = nodes.get(prefix + '-icon-value');
        const buttons = picker.children;
        const labels = ['', ...context.INCIDENT_ICONS.map(icon => icon.label)];
        assert.equal(buttons.length, labels.length);
        buttons.forEach((button, index) => {
            const title = index ? labels[index] : 'Auto';
            const icon = index ? context.INCIDENT_ICONS[index - 1].icon : context.AUTO_ICON;
            assert.equal(button.type, 'button');
            assert.equal(button.title, title);
            assert.equal(button.innerHTML, `<span class="icon-pick-symbol">${icon}</span><span class="icon-pick-label">${title}</span>`);
            assert.equal(button.className, 'icon-pick' + (labels[index] === 'mail' ? ' active' : ''));
            assert.equal(button.getAttribute('aria-pressed'), String(labels[index] === 'mail'));
        });
        assert.equal(input.value, 'mail');

        const header = context.document.getElementById('entry-modal-icon');
        header.innerHTML = 'before';
        const phone = labels.indexOf('phone');
        buttons[phone].click();
        assert.equal(input.value, 'phone');
        assert.deepEqual(buttons.map(b => b.getAttribute('aria-pressed') === 'true'), labels.map(label => label === 'phone'));
        assert.deepEqual(buttons.map(b => b.classList.contains('active')), labels.map(label => label === 'phone'));
        assert.equal(header.innerHTML, updatesHeader ? context.INCIDENT_ICONS[phone - 1].icon : 'before');
        buttons[0].click();
        assert.equal(input.value, '');
        assert.equal(buttons[0].getAttribute('aria-pressed'), 'true');
        assert.equal(buttons[phone].getAttribute('aria-pressed'), 'false');
        assert.equal(header.innerHTML, updatesHeader ? '' : 'before');
    });
}

test('uploading and deleting an attachment reload the entry\'s attachment list', async () => {
    const entry = {attachments: [{id: 11, filename: 'modem.png', mime_type: 'image/png'}]};
    const {context, nodes, set, trace, requests, settle} = journal([
        {status: 201, body: {id: 11}}, {status: 200, body: entry},
        {status: 200, body: {}}, {status: 200, body: {attachments: []}},
    ]);
    set('entry-id', '9');
    const input = {files: [{name: 'modem.png'}], value: 'modem.png'};
    context.handleEntryFileUpload(input);
    await settle();
    const list = nodes.get('entry-attachment-list');
    assert.equal(list.children.length, 1);
    assert.equal(input.value, '');
    const deleteButton = list.children[0].children[1].children[1].children[1];
    deleteButton.click();
    await settle();
    await settle();
    assert.deepEqual(requests.map(r => [r[0], r[1]]), [
        ['/base/api/journal/9/attachments', 'POST'], ['/base/api/journal/9', undefined],
        ['/base/api/attachments/11', 'DELETE'], ['/base/api/journal/9', undefined],
    ]);
    assert.equal(list.children.length, 0);
    assert.deepEqual(trace, []);
});
