'use strict';
DOCSightSettings.themes = function({showToast, guardUnsaved}) {
/* ── Theme Toggle ── */
function initThemeToggle() {
    var appearanceCheck = document.getElementById('theme-toggle-appearance');

    /* Restore saved theme */
    var saved = localStorage.getItem('docsis-theme');
    if (saved) {
        document.documentElement.setAttribute('data-theme', saved);
        if (appearanceCheck) appearanceCheck.checked = (saved === 'dark');
    }
    updatePaletteDots(document.documentElement.getAttribute('data-theme'));
}

function toggleThemeFromAppearance(checked) {
    var theme = checked ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('docsis-theme', theme);
    updatePaletteDots(theme);
}

function applyFontToggle(useSystem) {
    var el = document.getElementById('font-override');
    var hidden = document.getElementById('font_family');
    if (hidden) hidden.value = useSystem ? 'system' : 'outfit';
    if (useSystem) {
        if (!el) {
            el = document.createElement('style');
            el.id = 'font-override';
            el.textContent = ':root { --font-sans: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }';
            document.head.appendChild(el);
        }
    } else if (el) {
        el.remove();
    }
}

function updatePaletteDots(mode) {
    var keys = ['--bg', '--surface', '--accent', '--good', '--crit'];
    document.querySelectorAll('.theme-card').forEach(function(card) {
        var colors = JSON.parse(card.getAttribute('data-theme-' + mode) || '{}');
        var dots = card.querySelectorAll('.palette-dot');
        dots.forEach(function(dot, i) {
            if (keys[i] && colors[keys[i]]) dot.style.background = colors[keys[i]];
        });
    });
}

/* ── Theme System ── */
var _previewingThemeId = null;

function previewTheme(card) {
    cancelPreview();
    var themeId = card.getAttribute('data-theme-id');
    var preview = document.createElement('style');
    preview.id = 'theme-preview-vars';
    document.head.appendChild(preview);
    var active = document.getElementById('theme-module-vars');
    if (active) active.disabled = true;
    ['dark', 'light'].forEach(function(mode) {
        var vars = JSON.parse(card.getAttribute('data-theme-' + mode) || '{}');
        var index = preview.sheet.insertRule('[data-theme="' + mode + '"] {}', preview.sheet.cssRules.length);
        var style = preview.sheet.cssRules[index].style;
        Object.keys(vars).forEach(function(key) { style.setProperty(key, vars[key]); });
    });

    _previewingThemeId = themeId;
    var overlay = document.getElementById('theme-preview-overlay');
    var nameEl = document.getElementById('preview-theme-name');
    if (nameEl) nameEl.textContent = card.getAttribute('data-theme-name') || themeId;
    if (overlay) overlay.style.display = '';
}

function cancelPreview() {
    var preview = document.getElementById('theme-preview-vars');
    if (preview) preview.remove();
    var active = document.getElementById('theme-module-vars');
    if (active) active.disabled = false;
    _previewingThemeId = null;
    var overlay = document.getElementById('theme-preview-overlay');
    if (overlay) overlay.style.display = 'none';
}

function applyPreviewedTheme() {
    if (_previewingThemeId) {
        applyTheme(_previewingThemeId);
    }
}

function applyTheme(themeId) {
    guardUnsaved().then(function(proceed) {
        if (!proceed) return;
        fetch(docsightUrl('/api/modules/' + themeId + '/enable'), { method: 'POST' })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.success) {
                    location.reload();
                } else {
                    showToast(data.error || (T.theme_apply_failed || 'Failed to apply theme'), false);
                }
            })
            .catch(function(err) {
                showToast((T.error_prefix || 'Error') + ': ' + err.message, false);
            });
    });
}


/* ── Theme Registry ── */
var _themeRegistryFetching = false;
var _themeRegistryLoaded = false;

function loadThemeRegistryIfNeeded() {
    if (_themeRegistryLoaded || _themeRegistryFetching) return;
    refreshRegistry();
}

function refreshRegistry() {
    var gallery = document.getElementById('registry-gallery');
    if (!gallery || _themeRegistryFetching) return;
    _themeRegistryFetching = true;
    gallery.textContent = '';
    var p = document.createElement('p');
    p.textContent = T.loading || 'Loading...';
    var loading = document.createElement('div');
    loading.className = 'empty-state';
    loading.appendChild(p);
    gallery.appendChild(loading);

    fetch(docsightUrl('/api/themes/registry'))
        .then(function(r) { return r.json(); })
        .then(function(themes) {
            gallery.textContent = '';
            _themeRegistryLoaded = true;
            if (!themes.length) {
                var empty = document.createElement('div');
                empty.className = 'empty-state';
                var msg = document.createElement('p');
                msg.textContent = T.themes_all_installed || 'All available themes are installed';
                empty.appendChild(msg);
                gallery.appendChild(empty);
                return;
            }
            themes.forEach(function(theme) {
                var card = document.createElement('div');
                card.className = 'theme-card glass';

                var info = document.createElement('div');
                info.className = 'theme-info';
                var name = document.createElement('div');
                name.className = 'theme-name';
                name.textContent = theme.name;
                var desc = document.createElement('div');
                desc.className = 'theme-desc';
                desc.textContent = theme.description || '';
                var meta = document.createElement('div');
                meta.className = 'theme-meta';
                var ver = document.createElement('span');
                ver.textContent = 'v' + theme.version;
                var auth = document.createElement('span');
                auth.textContent = theme.author || '';
                meta.appendChild(ver);
                meta.appendChild(auth);
                info.appendChild(name);
                info.appendChild(desc);
                info.appendChild(meta);

                var actions = document.createElement('div');
                actions.className = 'theme-actions';
                var btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'btn btn-primary btn-sm';
                btn.textContent = T.theme_install || 'Install';
                btn.addEventListener('click', function() {
                    installTheme(theme.id, theme.download_url);
                });
                actions.appendChild(btn);

                card.appendChild(info);
                card.appendChild(actions);
                gallery.appendChild(card);
            });
            lucide.createIcons();
        })
        .catch(function() {
            gallery.textContent = '';
            _themeRegistryLoaded = false;
            var err = document.createElement('div');
            err.className = 'empty-state';
            var msg = document.createElement('p');
            msg.textContent = T.theme_registry_failed || 'Failed to load registry';
            err.appendChild(msg);
            gallery.appendChild(err);
        })
        .finally(function() { _themeRegistryFetching = false; });
}

function installTheme(themeId, downloadUrl) {
    fetch(docsightUrl('/api/themes/install'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: themeId, download_url: downloadUrl }),
    })
        .then(function(r) {
            return r.json().then(function(data) {
                if (r.status === 409) data.error = T.theme_install_failed || 'Install failed';
                return data;
            });
        })
        .then(function(data) {
            if (data.success) {
                showToast(T.theme_installed || 'Theme installed — restart required', true);
                refreshRegistry();
            } else {
                showToast(data.error || (T.theme_install_failed || 'Install failed'), false);
            }
        })
        .catch(function(err) {
            showToast((T.error_prefix || 'Error') + ': ' + err.message, false);
        });
}
return {init: initThemeToggle, toggleThemeFromAppearance, applyFontToggle, previewTheme, cancelPreview, applyPreviewedTheme, applyTheme, loadThemeRegistryIfNeeded, refreshRegistry};
};
