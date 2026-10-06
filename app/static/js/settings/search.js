'use strict';
/* Settings search: finds fields, switches and cards by their visible label and
   opens the section at the match. The index is read from the page once. */
DOCSightSettings.search = function({switchSection}) {
var MAX_RESULTS = 8;
var entries = null;

function _text(el) {
    return (el && el.textContent || '').replace(/\s+/g, ' ').trim();
}

function _buildIndex() {
    var list = [];
    document.querySelectorAll('.settings-panel').forEach(function(panel) {
        var section = panel.id.replace(/^panel-/, '');
        var sectionTitle = SECTION_TITLES[section] || section;
        panel.querySelectorAll('.card').forEach(function(card) {
            var cardTitle = _text(card.querySelector('.card-title'));
            if (cardTitle) list.push({label: cardTitle, where: sectionTitle, section: section, target: card});
            card.querySelectorAll('.form-label, .toggle-title').forEach(function(label) {
                var name = _text(label);
                if (!name) return;
                var target = label.htmlFor ? document.getElementById(label.htmlFor) : null;
                list.push({label: name, where: sectionTitle + (cardTitle && cardTitle !== sectionTitle ? ' › ' + cardTitle : ''), section: section, target: target || label});
            });
        });
    });
    return list;
}

function _matches(query) {
    var words = query.toLocaleLowerCase().split(/\s+/).filter(Boolean);
    if (!words.length) return [];
    entries = entries || _buildIndex();
    // Labels that start with the query come first, then labels that contain it,
    // then matches that only name the section or card.
    function rank(entry) {
        var label = entry.label.toLocaleLowerCase();
        if (label.indexOf(words.join(' ')) === 0) return 0;
        return words.every(function(word) { return label.indexOf(word) !== -1; }) ? 1 : 2;
    }
    return entries.filter(function(entry) {
        var haystack = (entry.label + ' ' + entry.where).toLocaleLowerCase();
        return words.every(function(word) { return haystack.indexOf(word) !== -1; });
    }).map(function(entry, order) {
        return {entry: entry, rank: rank(entry), order: order};
    }).sort(function(a, b) {
        return a.rank - b.rank || a.order - b.order;
    }).slice(0, MAX_RESULTS).map(function(item) { return item.entry; });
}

function _open(entry, input, results) {
    results.hidden = true;
    input.value = '';
    switchSection(entry.section);
    entry.target.scrollIntoView({block: 'center'});
    var focusable = entry.target.matches('input, select, textarea, button') ? entry.target : null;
    if (focusable && !focusable.closest('[inert]')) focusable.focus({preventScroll: true});
}

function init() {
    var input = document.getElementById('settings-search');
    var results = document.getElementById('settings-search-results');
    if (!input || !results) return;
    function render() {
        var found = _matches(input.value);
        results.textContent = '';
        if (!input.value.trim()) {
            results.hidden = true;
            return;
        }
        if (!found.length) {
            var none = document.createElement('p');
            none.className = 'settings-search-empty';
            none.textContent = T.settings_search_none || 'No setting matches';
            results.appendChild(none);
        }
        found.forEach(function(entry) {
            var button = document.createElement('button');
            button.type = 'button';
            button.className = 'settings-search-result';
            var label = document.createElement('span');
            label.className = 'settings-search-label';
            label.textContent = entry.label;
            var where = document.createElement('span');
            where.className = 'settings-search-where';
            where.textContent = entry.where;
            button.append(label, where);
            button.addEventListener('click', function() { _open(entry, input, results); });
            results.appendChild(button);
        });
        results.hidden = false;
    }
    input.addEventListener('input', render);
    input.addEventListener('keydown', function(event) {
        if (event.key === 'Escape') {
            input.value = '';
            render();
        } else if (event.key === 'ArrowDown' || event.key === 'Enter') {
            var first = results.querySelector('.settings-search-result');
            if (!first) return;
            event.preventDefault();
            if (event.key === 'Enter') first.click();
            else first.focus();
        }
    });
    results.addEventListener('keydown', function(event) {
        var buttons = Array.from(results.querySelectorAll('.settings-search-result'));
        var index = buttons.indexOf(document.activeElement);
        if (index < 0) return;
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            var next = index + (event.key === 'ArrowDown' ? 1 : -1);
            if (next < 0) input.focus();
            else buttons[Math.min(next, buttons.length - 1)].focus();
        } else if (event.key === 'Escape') {
            input.focus();
            input.value = '';
            render();
        }
    });
}
return {init};
};
