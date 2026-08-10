/* ── Smokeping Module JS ── */

/* ── Smokeping Graphs ── */
var _smokepingSpan = '3h';
var smokepingTabs = document.querySelectorAll('#smokeping-tabs .trend-tab');
smokepingTabs.forEach(function(btn) {
    btn.addEventListener('click', function() {
        _smokepingSpan = this.getAttribute('data-span');
        smokepingTabs.forEach(function(b) {
            b.classList.toggle('active', b.getAttribute('data-span') === _smokepingSpan);
        });
        loadSmokepingGraphs();
    });
});

function loadSmokepingGraphs() {
    var content = document.getElementById('smokeping-content');
    var noData = document.getElementById('smokeping-no-data');
    if (!content || !noData) return;
    content.replaceChildren();
    noData.style.display = 'none';

    fetch(docsightUrl('/api/smokeping/targets'))
        .then(function(r) { return r.json(); })
        .then(function(targets) {
            if (!targets || targets.length === 0) {
                noData.textContent = T.smokeping_no_data || T['docsight.smokeping.smokeping_no_data'] || 'Could not load Smokeping graphs.';
                noData.style.display = 'block';
                return;
            }
            targets.forEach(function(target) {
                var card = document.createElement('div');
                card.className = 'bqm-card';
                var header = document.createElement('div');
                header.className = 'chart-card-header';
                var headerContent = document.createElement('div');
                headerContent.className = 'chart-header-content';
                var headerLabel = document.createElement('div');
                headerLabel.className = 'chart-label';
                headerLabel.textContent = target;
                headerContent.appendChild(headerLabel);
                header.appendChild(headerContent);
                card.appendChild(header);
                var wrap = document.createElement('div');
                wrap.style.textAlign = 'center';
                var img = document.createElement('img');
                img.style.maxWidth = '100%';
                img.style.borderRadius = '8px';
                img.alt = target;
                img.src = docsightUrl('/api/smokeping/graph/' + encodeURIComponent(target) + '/' + _smokepingSpan);
                img.onerror = function() {
                    var fallback = document.createElement('div');
                    fallback.className = 'no-data-msg';
                    fallback.style.display = 'block';
                    fallback.textContent = T.smokeping_no_data || T['docsight.smokeping.smokeping_no_data'] || 'Could not load graph.';
                    wrap.replaceChildren(fallback);
                };
                wrap.appendChild(img);
                card.appendChild(wrap);
                content.appendChild(card);
            });
        })
        .catch(function() {
            noData.textContent = T.smokeping_no_data || T['docsight.smokeping.smokeping_no_data'] || 'Could not load Smokeping graphs.';
            noData.style.display = 'block';
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
