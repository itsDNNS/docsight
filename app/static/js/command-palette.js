/* Command palette and keyboard shortcuts. Shared by the dashboard and settings.
   ⌘K / Ctrl+K opens the palette; g then o/s/c/e/v jumps to a destination and ?
   lists the shortcuts. Letter shortcuts only act outside text fields. */
(function() {
    'use strict';

    var dialog = document.getElementById('command-palette');
    var dataEl = document.getElementById('command-palette-data');
    if (!dialog || !dataEl) return;

    var data = JSON.parse(dataEl.textContent);
    var input = document.getElementById('command-palette-input');
    var list = document.getElementById('command-palette-list');
    var empty = document.getElementById('command-palette-empty');
    var help = document.getElementById('command-palette-help');
    var helpToggle = document.getElementById('command-palette-help-toggle');
    var status = document.getElementById('command-palette-status');
    var topnav = document.getElementById('topnav');
    var isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);

    var GROUP_LIMIT = {channels: 6, glossary: 6};
    var ICONS = {channels: 'activity', glossary: 'book-open'};

    var items = null;
    var channelsLoaded = false;
    var options = [];
    var activeIndex = -1;

    function text(key, values) {
        var value = data.text[key] || '';
        Object.keys(values || {}).forEach(function(name) {
            value = value.replace('{' + name + '}', values[name]);
        });
        return value;
    }

    function fold(value) {
        return String(value || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
    }

    function onDashboard() { return typeof window.switchView === 'function'; }

    function goToHash(hash) {
        if (!onDashboard()) {
            window.location.assign(docsightUrl('/') + hash);
            return;
        }
        var sameView = location.hash.split('?')[0] === hash.split('?')[0];
        location.hash = hash;
        // The router ignores a hash for the view already shown; the channel view rereads it.
        if (sameView && hash.indexOf('#channels') === 0 && typeof initChannelView === 'function') initChannelView();
    }

    /* ── Destinations ── */
    function navLabel(el) {
        var label = el.querySelector('.topnav-label');
        return (label ? label.textContent : el.textContent).replace(/\s+/g, ' ').trim();
    }

    function navGroupLabel(el) {
        var group = el.closest('.topnav-group');
        var toggle = group && group.querySelector('.topnav-toggle');
        return toggle ? navLabel(toggle) : '';
    }

    function shortcutTarget(target) {
        if (!topnav) return null;
        if (target === 'live' || target === 'events') return topnav.querySelector('.nav-item[data-view="' + target + '"]');
        return topnav.querySelector('#nav-panel-' + target + ' .nav-item');
    }

    function shortcutFor(el) {
        for (var i = 0; i < data.shortcuts.length; i++) {
            if (shortcutTarget(data.shortcuts[i][1]) === el) return data.shortcuts[i][0];
        }
        return '';
    }

    function navItems() {
        if (!topnav) return [];
        return Array.from(topnav.querySelectorAll('.nav-item')).filter(function(el) {
            return el.type !== 'submit';
        }).map(function(el) {
            var icon = el.querySelector('svg, i');
            return {
                group: el.hasAttribute('data-view') ? 'views' : 'actions',
                title: navLabel(el),
                keywords: [navGroupLabel(el), el.getAttribute('data-nav-title') || ''].join(' '),
                icon: icon ? icon.cloneNode(true) : null,
                shortcut: shortcutFor(el),
                run: function() { el.click(); }
            };
        });
    }

    function settingsItems() {
        return data.settings.map(function(section) {
            var id = section[0];
            return {
                group: 'settings',
                title: section[2],
                keywords: section[3],
                iconName: section[1],
                run: function() {
                    var entry = document.querySelector('.settings-index-item[data-section="' + id + '"]');
                    if (entry) entry.click();
                    else window.location.assign(docsightUrl('/settings') + '#' + encodeURIComponent(id));
                }
            };
        });
    }

    function glossaryItems() {
        return data.glossary.map(function(term) {
            return {
                group: 'glossary',
                title: term[1],
                keywords: (term[2] || []).join(' '),
                iconName: ICONS.glossary,
                run: function() { goToHash('#glossary?term=' + encodeURIComponent(term[0])); }
            };
        });
    }

    function channelItem(direction, ch) {
        var details = [];
        var frequency = parseFloat(ch.frequency);
        if (!isNaN(frequency)) details.push(frequency + ' MHz');
        if (ch.modulation) details.push(ch.modulation);
        var identity = ch.selector_required
            ? 'selector=' + encodeURIComponent(ch.selector)
            : 'channel=' + encodeURIComponent(ch.legacy_channel_id);
        return {
            group: 'channels',
            title: text(direction === 'ds' ? 'channel_ds' : 'channel_us', {id: ch.channel_id}),
            detail: details.join(' · '),
            keywords: [direction === 'ds' ? 'DS downstream' : 'US upstream', ch.channel_family, ch.docsis_version, ch.multiplex].join(' '),
            iconName: ICONS.channels,
            run: function() { goToHash('#channels?mode=timeline&dir=' + direction + '&' + identity + '&range=1d'); }
        };
    }

    function loadChannels() {
        if (channelsLoaded) return;
        channelsLoaded = true;
        fetch(docsightUrl('/api/channels'), {headers: {'Accept': 'application/json'}})
            .then(function(response) { return response.ok ? response.json() : null; })
            .then(function(payload) {
                if (!payload) return;
                (payload.ds_channels || []).forEach(function(ch) { items.push(channelItem('ds', ch)); });
                (payload.us_channels || []).forEach(function(ch) { items.push(channelItem('us', ch)); });
                if (dialog.open && input.value.trim()) render();
            })
            .catch(function() { /* The palette works without channels. */ });
    }

    /* ── Search ── */
    function words(value) { return value.split(/[^0-9a-z\u00c0-\uffff]+/); }

    /* Lower is better: a whole word beats a word start beats a substring, the title beats the rest. */
    function tokenScore(token, title, titleWords, rest, restWords) {
        if (titleWords.indexOf(token) >= 0) return 0;
        if (titleWords.some(function(word) { return word.indexOf(token) === 0; })) return 1;
        if (title.indexOf(token) >= 0) return 2;
        if (restWords.indexOf(token) >= 0) return 2;
        if (restWords.some(function(word) { return word.indexOf(token) === 0; })) return 3;
        if (rest.indexOf(token) >= 0) return 4;
        return -1;
    }

    function score(item, tokens, query) {
        var title = fold(item.title);
        var rest = fold([item.detail, item.keywords].join(' '));
        var titleWords = words(title);
        var restWords = words(rest);
        var total = title.indexOf(query) === 0 ? -1 : 0;
        for (var i = 0; i < tokens.length; i++) {
            var value = tokenScore(tokens[i], title, titleWords, rest, restWords);
            if (value < 0) return -1;
            total += value;
        }
        return total + 1;
    }

    function search(query) {
        var folded = fold(query).trim();
        if (!folded) {
            return items.filter(function(item) { return item.group === 'views' || item.group === 'settings'; });
        }
        var tokens = folded.split(/\s+/);
        var scored = [];
        items.forEach(function(item, index) {
            var value = score(item, tokens, folded);
            if (value >= 0) scored.push({item: item, score: value, index: index});
        });
        scored.sort(function(a, b) { return a.score - b.score || a.index - b.index; });
        var counts = {};
        return scored.map(function(entry) { return entry.item; }).filter(function(item) {
            counts[item.group] = (counts[item.group] || 0) + 1;
            return !GROUP_LIMIT[item.group] || counts[item.group] <= GROUP_LIMIT[item.group];
        });
    }

    /* Marks the query's words in the title with text nodes only. */
    function highlighted(title, query) {
        var fragment = document.createDocumentFragment();
        var folded = fold(title);
        var marks = new Array(title.length).fill(false);
        fold(query).trim().split(/\s+/).forEach(function(token) {
            if (!token) return;
            var at = folded.indexOf(token);
            // Folding keeps the length for the scripts DOCSight ships, so offsets match.
            if (at < 0 || folded.length !== title.length) return;
            for (var i = at; i < at + token.length; i++) marks[i] = true;
        });
        var start = 0;
        for (var i = 1; i <= title.length; i++) {
            if (i === title.length || marks[i] !== marks[start]) {
                var part = title.slice(start, i);
                if (marks[start]) {
                    var mark = document.createElement('mark');
                    mark.textContent = part;
                    fragment.appendChild(mark);
                } else {
                    fragment.appendChild(document.createTextNode(part));
                }
                start = i;
            }
        }
        return fragment;
    }

    function optionNode(item, query, id) {
        var option = document.createElement('div');
        option.className = 'command-palette-option';
        option.id = id;
        option.setAttribute('role', 'option');
        option.setAttribute('aria-selected', 'false');
        var icon = item.icon ? item.icon.cloneNode(true) : lucide.createElement(item.iconName);
        icon.setAttribute('aria-hidden', 'true');
        option.appendChild(icon);
        var label = document.createElement('span');
        label.className = 'command-palette-option-label';
        label.appendChild(highlighted(item.title, query));
        if (item.detail) {
            var detail = document.createElement('span');
            detail.className = 'command-palette-option-detail';
            detail.textContent = item.detail;
            label.appendChild(detail);
        }
        option.appendChild(label);
        if (item.shortcut) {
            var keys = document.createElement('span');
            keys.className = 'command-palette-option-keys';
            keys.setAttribute('aria-hidden', 'true');
            ['g', item.shortcut].forEach(function(key) {
                var kbd = document.createElement('kbd');
                kbd.className = 'command-palette-key';
                kbd.textContent = key;
                keys.appendChild(kbd);
            });
            option.appendChild(keys);
        }
        option.addEventListener('click', function() { runOption(options.indexOf(option)); });
        option.addEventListener('pointermove', function() { setActive(options.indexOf(option), false); });
        option._item = item;
        return option;
    }

    function render() {
        var query = input.value;
        var results = search(query);
        list.textContent = '';
        options = [];
        // Results come best first, so the group with the best match leads.
        var groups = [];
        results.forEach(function(item) { if (groups.indexOf(item.group) < 0) groups.push(item.group); });
        groups.forEach(function(group) {
            var groupItems = results.filter(function(item) { return item.group === group; });
            if (!groupItems.length) return;
            var section = document.createElement('div');
            section.className = 'command-palette-group';
            section.setAttribute('role', 'group');
            var title = document.createElement('div');
            title.className = 'command-palette-group-title';
            title.id = 'command-palette-group-' + group;
            title.textContent = text(group);
            section.setAttribute('aria-labelledby', title.id);
            section.appendChild(title);
            groupItems.forEach(function(item) {
                var option = optionNode(item, query, 'command-palette-option-' + options.length);
                options.push(option);
                section.appendChild(option);
            });
            list.appendChild(section);
        });
        list.hidden = !options.length;
        empty.hidden = !!options.length;
        empty.textContent = options.length ? '' : text('no_results', {query: query.trim()});
        status.textContent = options.length ? text('results', {count: options.length}) : empty.textContent;
        setActive(options.length ? 0 : -1, true);
    }

    function setActive(index, scroll) {
        if (activeIndex >= 0 && options[activeIndex]) options[activeIndex].setAttribute('aria-selected', 'false');
        activeIndex = index;
        if (index < 0) {
            input.removeAttribute('aria-activedescendant');
            return;
        }
        options[index].setAttribute('aria-selected', 'true');
        input.setAttribute('aria-activedescendant', options[index].id);
        if (scroll) options[index].scrollIntoView({block: 'nearest'});
    }

    function runOption(index) {
        var option = options[index];
        if (!option) return;
        closePalette({restoreFocus: false});
        option._item.run();
    }

    /* ── Help ── */
    function showHelp(show) {
        help.hidden = !show;
        helpToggle.setAttribute('aria-expanded', String(show));
        if (show) {
            list.hidden = true;
            empty.hidden = true;
        } else {
            render();
        }
    }

    function fillHelp() {
        help.querySelectorAll('[data-palette-mod]').forEach(function(kbd) { kbd.textContent = isMac ? '⌘' : 'Ctrl'; });
        help.querySelectorAll('[data-palette-shortcut]').forEach(function(row) {
            var target = row.getAttribute('data-palette-shortcut');
            var el = shortcutTarget(target);
            var toggle = topnav && topnav.querySelector('#nav-toggle-' + target);
            row.hidden = !el;
            if (el) row.querySelector('dd').textContent = toggle ? navLabel(toggle) : navLabel(el);
        });
    }

    /* ── Open / close ── */
    var opener = null;

    function openPalette(options) {
        options = options || {};
        if (dialog.open) return;
        if (window.DOCSightNav) window.DOCSightNav.close();
        opener = document.activeElement;
        if (!items) {
            items = navItems().concat(settingsItems(), glossaryItems());
            fillHelp();
        }
        loadChannels();
        input.value = '';
        dialog.showModal();
        showHelp(!!options.help);
        input.focus();
    }

    function closePalette(options) {
        options = options || {};
        if (dialog.open) dialog.close();
        if (options.restoreFocus !== false && opener && document.contains(opener) && opener.focus) {
            opener.focus({preventScroll: true});
        }
        opener = null;
    }

    window.openCommandPalette = function() { openPalette(); };
    window.closeCommandPalette = function() { closePalette(); };

    input.addEventListener('input', function() {
        if (!help.hidden) showHelp(false);
        else render();
    });

    input.addEventListener('keydown', function(event) {
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            if (!options.length) return;
            var step = event.key === 'ArrowDown' ? 1 : -1;
            setActive((activeIndex + step + options.length) % options.length, true);
        } else if ((event.key === 'Home' || event.key === 'End') && event.ctrlKey && options.length) {
            event.preventDefault();
            setActive(event.key === 'Home' ? 0 : options.length - 1, true);
        } else if (event.key === 'Enter') {
            event.preventDefault();
            runOption(activeIndex);
        }
    });

    helpToggle.addEventListener('click', function() {
        showHelp(help.hidden);
        input.focus();
    });

    // Escape closes the dialog natively; a click on the backdrop lands on the dialog itself.
    dialog.addEventListener('cancel', function(event) {
        event.preventDefault();
        closePalette();
    });
    dialog.addEventListener('click', function(event) {
        if (event.target === dialog) closePalette();
    });

    /* ── Keyboard shortcuts ── */
    function typingTarget(el) {
        if (!el || !(el instanceof Element)) return false;
        return !!el.closest('input, textarea, select, [contenteditable=""], [contenteditable="true"]');
    }

    var pendingG = 0;

    document.addEventListener('keydown', function(event) {
        if ((event.metaKey || event.ctrlKey) && !event.altKey && !event.shiftKey && (event.key === 'k' || event.key === 'K')) {
            event.preventDefault();
            if (dialog.open) closePalette();
            else openPalette();
            return;
        }
        if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) return;
        if (dialog.open || document.querySelector('dialog[open]') || typingTarget(event.target)) return;
        if (event.key === '?') {
            event.preventDefault();
            openPalette({help: true});
            return;
        }
        if (pendingG && Date.now() - pendingG < 1500) {
            pendingG = 0;
            for (var i = 0; i < data.shortcuts.length; i++) {
                if (data.shortcuts[i][0] !== event.key) continue;
                var el = shortcutTarget(data.shortcuts[i][1]);
                if (el) {
                    event.preventDefault();
                    if (window.DOCSightNav) window.DOCSightNav.close();
                    el.click();
                }
                return;
            }
            return;
        }
        pendingG = event.key === 'g' ? Date.now() : 0;
    });

    var trigger = document.getElementById('command-palette-open');
    if (trigger) {
        var key = trigger.querySelector('[data-palette-mod]');
        if (key) key.textContent = isMac ? '⌘K' : 'Ctrl K';
        trigger.setAttribute('aria-keyshortcuts', isMac ? 'Meta+K' : 'Control+K');
    }
})();
