/* ── Smokeping Module JS ── */

/* ── Smokeping Graphs ──
   The view uses the app's ranges. SmokePing only draws 3 h, 30 h, 10 d and 1 y,
   so each range shows the closest graph and says so. */
var SMOKEPING_SPANS = {
    '1h': '3h', '6h': '3h', '1d': '30h', '2d': '30h',
    '3d': '10d', '7d': '10d', '30d': '1y', '90d': '1y'
};
var SMOKEPING_SPAN_LABELS = {
    '3h': ['smokeping_span_3h', 'last 3 hours'],
    '30h': ['smokeping_span_30h', 'last 30 hours'],
    '10d': ['smokeping_span_10d', 'last 10 days'],
    '1y': ['smokeping_span_1y', 'last year']
};
var _smokepingRange = '1d';

function _smokepingText(key, fallback) {
    return T[key] || T['docsight.smokeping.' + key] || fallback;
}

(function() {
    var tabs = document.getElementById('smokeping-tabs');
    if (!tabs) return;
    tabs.querySelectorAll('.segmented-option').forEach(function(btn) {
        btn.addEventListener('click', function() {
            _smokepingRange = this.getAttribute('data-smokeping-range');
            syncSegments('smokeping-tabs', function(b) { return b.getAttribute('data-smokeping-range') === _smokepingRange; });
            docsightWriteViewState('smokeping', {range: _smokepingRange});
            loadSmokepingGraphs();
        });
    });
})();

function _smokepingFrame(target, span, sourceLink) {
    var frame = document.createElement('article');
    frame.className = 'graph-frame smokeping-frame';
    var head = document.createElement('div');
    head.className = 'graph-frame-head';
    var title = document.createElement('h3');
    title.className = 'graph-frame-title';
    title.textContent = 'SmokePing \u00b7 ' + target;
    head.appendChild(title);
    var label = SMOKEPING_SPAN_LABELS[span];
    var windowEl = document.createElement('span');
    windowEl.className = 'graph-frame-window';
    windowEl.textContent = _smokepingText(label[0], label[1]);
    head.appendChild(windowEl);
    var note = document.createElement('span');
    note.className = 'graph-frame-note';
    note.textContent = _smokepingText('smokeping_closest_to', 'closest to {range}').replace('{range}', _smokepingRange);
    head.appendChild(note);
    frame.appendChild(head);

    var body = document.createElement('div');
    body.className = 'graph-frame-body';
    var paper = document.createElement('div');
    paper.className = 'graph-frame-paper';
    var img = document.createElement('img');
    img.alt = title.textContent + ', ' + windowEl.textContent;
    img.src = docsightUrl('/api/smokeping/graph/' + encodeURIComponent(target) + '/' + span);
    img.onerror = function() {
        var fallback = document.createElement('p');
        fallback.className = 'graph-frame-message';
        fallback.textContent = _smokepingText('smokeping_no_data', 'Could not load graph.');
        body.replaceChildren(fallback);
    };
    paper.appendChild(img);
    body.appendChild(paper);
    frame.appendChild(body);

    var foot = document.createElement('div');
    foot.className = 'graph-frame-foot';
    var source = document.createElement('span');
    source.textContent = _smokepingText('smokeping_frame_source', 'SmokePing draws 3 h, 30 h, 10 d or 1 y');
    foot.appendChild(source);
    if (sourceLink) {
        // The address comes from the server-rendered link; only the target is added here.
        var link = sourceLink.cloneNode(true);
        link.removeAttribute('id');
        link.hidden = false;
        link.search = new URLSearchParams({target: target}).toString();
        foot.appendChild(link);
    }
    frame.appendChild(foot);
    return frame;
}

function loadSmokepingGraphs() {
    var content = document.getElementById('smokeping-content');
    var noData = document.getElementById('smokeping-no-data');
    if (!content || !noData) return;
    var range = docsightReadViewState('smokeping').range;
    if (SMOKEPING_SPANS[range] && docsightSelectSegment('smokeping-tabs', 'data-smokeping-range', range)) _smokepingRange = range;
    content.replaceChildren();
    DOCSightEmptyState.hide(noData);
    var sourceLink = document.getElementById('smokeping-source-link');

    fetch(docsightUrl('/api/smokeping/targets'))
        .then(function(r) { return r.json(); })
        .then(function(targets) {
            if (!targets || targets.length === 0) {
                DOCSightEmptyState.show(noData, {
                    icon: 'radar',
                    title: T.smokeping_empty_title || 'No SmokePing targets configured',
                    text: T.smokeping_empty_text,
                    action: {
                        label: T.smokeping_empty_action || 'Open SmokePing settings',
                        href: docsightUrl('/settings#mod-docsight_smokeping')
                    },
                    glossary: 'smokeping'
                });
                return;
            }
            var span = SMOKEPING_SPANS[_smokepingRange] || '30h';
            targets.forEach(function(target) {
                content.appendChild(_smokepingFrame(target, span, sourceLink));
            });
        })
        .catch(function() {
            DOCSightEmptyState.showError(noData, {retry: loadSmokepingGraphs});
        });
}

window.loadSmokepingGraphs = loadSmokepingGraphs;

/* ── Smokeping Setup Modal ── */
function openSmokepingSetupModal() {
    window.DOCSightModal.open('smokeping-setup-modal');
}
function closeSmokepingSetupModal() {
    window.DOCSightModal.close('smokeping-setup-modal');
}
window.openSmokepingSetupModal = openSmokepingSetupModal;
window.closeSmokepingSetupModal = closeSmokepingSetupModal;
