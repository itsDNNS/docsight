'use strict';
DOCSightSettings.module_registry = function({showToast}) {
/* ── Community Module Registry ── */
var _registryFetching = false;

function refreshModuleRegistry() {
    var gallery = document.getElementById('module-registry-gallery');
    var empty = document.getElementById('module-registry-empty');
    var loading = document.getElementById('module-registry-loading');
    if (!gallery || _registryFetching) return;
    _registryFetching = true;

    if (loading) loading.style.display = '';
    if (empty) empty.style.display = 'none';
    gallery.style.display = 'none';

    fetch(docsightUrl('/api/modules/registry'))
        .then(function(r) { return r.json(); })
        .then(function(modules) {
            if (loading) loading.style.display = 'none';
            if (!modules || modules.length === 0) {
                gallery.style.display = 'none';
                if (empty) empty.style.display = '';
                return;
            }
            gallery.style.display = '';
            if (empty) empty.style.display = 'none';

            // Build cards — dynamic content assigned via textContent (inherently safe)
            _renderRegistryCards(gallery, modules);
            if (typeof lucide !== 'undefined') lucide.createIcons();
        })
        .catch(function() {
            if (loading) loading.style.display = 'none';
            gallery.style.display = 'none';
            if (empty) empty.style.display = '';
            showToast(T.extensions_fetch_failed || 'Failed to load registry.', false);
        })
        .finally(function() { _registryFetching = false; });
}

function _renderRegistryCards(gallery, modules) {
    while (gallery.firstChild) gallery.removeChild(gallery.firstChild);

    modules.forEach(function(mod) {
        var status = mod.status || 'not_installed';

        var card = document.createElement('div');
        card.className = 'module-registry-card';

        var info = document.createElement('div');
        info.className = 'registry-card-info';

        var nameRow = document.createElement('div');
        nameRow.className = 'registry-card-name';
        nameRow.textContent = mod.name || mod.id;
        if (mod.verified) {
            var vBadge = document.createElement('span');
            vBadge.className = 'module-badge badge-verified';
            vBadge.textContent = T.extensions_verified || 'Verified';
            nameRow.appendChild(vBadge);
        }

        var desc = document.createElement('div');
        desc.className = 'registry-card-desc';
        desc.textContent = mod.description || '';

        var meta = document.createElement('div');
        meta.className = 'registry-card-meta';
        meta.textContent = (mod.author || '') + ' \u00B7 v' + (mod.version || '') + ' \u00B7 ';
        var statusSpan = document.createElement('span');
        if (status === 'not_installed') {
            statusSpan.textContent = T.extensions_not_installed || 'Not installed';
        } else if (status === 'installed_disabled') {
            statusSpan.textContent = T.extensions_installed || 'Installed';
            statusSpan.className = 'registry-status-warn';
        } else {
            statusSpan.textContent = T.extensions_installed || 'Installed';
            statusSpan.className = 'registry-status-good';
        }
        meta.appendChild(statusSpan);

        info.appendChild(nameRow);
        info.appendChild(desc);
        info.appendChild(meta);

        var action = document.createElement('div');
        action.className = 'registry-card-action';

        var btn = document.createElement('button');
        if (status === 'not_installed') {
            btn.className = 'btn btn-sm btn-install';
            btn.textContent = T.extensions_install || 'Install';
            btn.addEventListener('click', function(e) { installModule(e, mod.id, mod.download_url); });
        } else {
            btn.className = 'btn btn-sm btn-uninstall';
            btn.textContent = T.extensions_uninstall || 'Uninstall';
            btn.addEventListener('click', function(e) { uninstallModule(e, mod.id); });
        }
        action.appendChild(btn);

        card.appendChild(info);
        card.appendChild(action);
        gallery.appendChild(card);
    });
}

function _runModuleAction(e, id, action, downloadUrl) {
    var btn = e.currentTarget;
    var installing = action === 'install';
    var idleClass = installing ? 'btn-install' : 'btn-uninstall';
    var idleText = installing
        ? (T.extensions_install || 'Install')
        : (T.extensions_uninstall || 'Uninstall');
    var failedText = installing
        ? (T.extensions_install_failed || 'Installation failed')
        : (T.extensions_uninstall_failed || 'Uninstall failed');
    if (btn.dataset.confirmPending !== 'true') {
        btn.dataset.confirmPending = 'true';
        btn.className = 'btn btn-sm btn-confirm';
        btn.textContent = T.extensions_confirm || 'Confirm?';
        btn._resetTimer = setTimeout(function() {
            btn.dataset.confirmPending = 'false';
            btn.className = 'btn btn-sm ' + idleClass;
            btn.textContent = idleText;
        }, 3000);
        return;
    }
    clearTimeout(btn._resetTimer);
    btn.dataset.confirmPending = 'false';
    btn.disabled = true;
    btn.textContent = '...';

    var payload = {id: id};
    if (installing) payload.download_url = downloadUrl;
    fetch(docsightUrl('/api/modules/' + action), {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload),
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.success) {
            showToast(
                installing
                    ? (T.extensions_install_success || 'Module installed successfully')
                    : (T.extensions_uninstall_success || 'Module uninstalled'),
                true
            );
            var banner = document.getElementById('module-restart-banner');
            if (banner) { banner.style.display = ''; if (typeof lucide !== 'undefined') lucide.createIcons({nodes: [banner]}); }
            refreshModuleRegistry();
        } else {
            showToast(data.error || failedText, false);
            btn.disabled = false;
            btn.className = 'btn btn-sm ' + idleClass;
            btn.textContent = idleText;
        }
    })
    .catch(function(err) {
        showToast(failedText + ': ' + err.message, false);
        btn.disabled = false;
        btn.className = 'btn btn-sm ' + idleClass;
        btn.textContent = idleText;
    });
}

/* Thin public entry points retained for existing card click handlers. */
function installModule(e, id, downloadUrl) {
    _runModuleAction(e, id, 'install', downloadUrl);
}

function uninstallModule(e, id) {
    _runModuleAction(e, id, 'uninstall');
}
return {refreshModuleRegistry};
};
