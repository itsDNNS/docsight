/* ── Case picker ──
   Adds a span of days to a case: an existing case's window grows to cover it,
   or a new open case starts with exactly those days. A case's timeline and
   evidence follow its window, so whatever lies in those days joins the case.
   Used by the event log ("Add to case…") and the correlation view ("Save as case"). */
(function() {
    'use strict';

    var current = null;

    function text(key, fallback) { return (window.T && T[key]) || fallback; }

    function caseOption(c) {
        var option = document.createElement('label');
        option.className = 'case-pick-option';
        var input = document.createElement('input');
        input.type = 'radio';
        input.name = 'add-to-case';
        input.value = String(c.id);
        input.setAttribute('data-change-action', 'syncAddToCase');
        var label = document.createElement('span');
        label.className = 'case-pick-text';
        var name = document.createElement('span');
        name.className = 'case-pick-name';
        name.textContent = c.name;
        var span = document.createElement('span');
        span.className = 'case-pick-window';
        span.textContent = c.start_date
            ? formatDocsightTime(c.start_date, 'date') + ' – ' + (c.end_date ? formatDocsightTime(c.end_date, 'date') : text('event_case_running', 'ongoing'))
            : text('event_case_no_window', 'No window yet');
        label.appendChild(name);
        label.appendChild(span);
        option.appendChild(input);
        option.appendChild(label);
        return option;
    }

    /* options: startDate, endDate (YYYY-MM-DD), summary, name (suggested for a new case),
       added ('… “{case}”' toast text), onAdded(result). */
    function open(options) {
        current = options;
        document.getElementById('add-to-case-summary').textContent = options.summary || '';
        document.getElementById('add-to-case-name').value = options.name || '';
        var list = document.getElementById('add-to-case-list');
        list.textContent = '';
        fetch(docsightUrl('/api/incidents'))
            .then(function(r) { return r.ok ? r.json() : []; })
            .catch(function() { return []; })
            .then(function(cases) {
                (cases || []).slice().sort(function(a, b) {
                    return (a.status === 'open' ? 0 : 1) - (b.status === 'open' ? 0 : 1);
                }).forEach(function(c) { list.appendChild(caseOption(c)); });
                var first = list.querySelector('input') || document.querySelector('#add-to-case-modal input[value="new"]');
                first.checked = true;
                sync();
                window.DOCSightModal.open('add-to-case-modal');
            });
    }

    function sync() {
        var chosen = document.querySelector('#add-to-case-modal input[name="add-to-case"]:checked');
        var nameWrap = document.querySelector('#add-to-case-modal .case-pick-new-name');
        if (nameWrap) nameWrap.hidden = !(!chosen || chosen.value === 'new');
    }

    function close() {
        window.DOCSightModal.close('add-to-case-modal');
    }

    function submit() {
        var options = current;
        var chosen = document.querySelector('#add-to-case-modal input[name="add-to-case"]:checked');
        if (!options || !chosen) return;
        var span = {start_date: options.startDate, end_date: options.endDate};
        var request;
        if (chosen.value === 'new') {
            var nameInput = document.getElementById('add-to-case-name');
            var name = nameInput.value.trim();
            if (!name) { nameInput.focus(); return; }
            request = fetch(docsightUrl('/api/incidents'), {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({name: name, status: 'open', start_date: span.start_date, end_date: span.end_date})
            }).then(function(r) {
                if (!r.ok) throw new Error('Create failed');
                return r.json().then(function(data) { return {id: data.id, name: name, created: true}; });
            });
        } else {
            var caseName = chosen.closest('label').querySelector('.case-pick-name').textContent;
            request = fetch(docsightUrl('/api/incidents/' + encodeURIComponent(chosen.value) + '/extend'), {
                method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(span)
            }).then(function(r) {
                if (!r.ok) throw new Error('Extend failed');
                return {id: Number(chosen.value), name: caseName, created: false};
            });
        }
        request.then(function(result) {
            close();
            if (options.onAdded) options.onAdded(result);
            if (typeof showToast === 'function') {
                showToast(String(options.added || '').replace('{case}', result.name), 'success', {
                    action: {label: text('event_open_case', 'Open case'), onClick: function() { openCase(result.id); }}
                });
            }
        }).catch(function() {
            if (typeof showToast === 'function') showToast(text('network_error', 'Error'), 'error');
        });
    }

    function openCase(id) {
        if (typeof switchView === 'function') switchView('journal');
        if (typeof filterByIncident === 'function') filterByIncident(id);
    }

    window.DOCSightCasePicker = {open: open};
    window.syncAddToCase = sync;
    window.closeAddToCase = close;
    window.submitAddToCase = submit;
})();
