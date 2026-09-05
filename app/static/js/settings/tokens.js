'use strict';
DOCSightSettings.tokens = function({showToast}) {
/* ── API Token Management ── */
function _tokenCell(text, style) {
    var td = document.createElement('td');
    td.style.cssText = style || 'padding:4px 8px;';
    td.textContent = text;
    return td;
}

function loadApiTokens() {
    var table = document.getElementById('api-tokens-table');
    var body = document.getElementById('api-tokens-body');
    var empty = document.getElementById('api-tokens-empty');
    if (!table || !body) return;
    fetch(docsightUrl('/api/tokens')).then(function(r) { return r.json(); }).then(function(data) {
        var tokens = (data.tokens || []).filter(function(t) { return !t.revoked; });
        while (body.firstChild) body.removeChild(body.firstChild);
        if (tokens.length === 0) {
            table.style.display = 'none';
            if (empty) empty.style.display = 'block';
            return;
        }
        table.style.display = 'table';
        if (empty) empty.style.display = 'none';
        tokens.forEach(function(tk) {
            var tr = document.createElement('tr');
            tr.appendChild(_tokenCell(tk.name, 'padding:4px 8px;'));
            var prefixTd = document.createElement('td');
            prefixTd.style.cssText = 'padding:4px 8px;';
            var code = document.createElement('code');
            code.textContent = tk.token_prefix + '...';
            prefixTd.appendChild(code);
            tr.appendChild(prefixTd);
            tr.appendChild(_tokenCell(tk.last_used_at || '\u2014', 'padding:4px 8px;'));
            var actionTd = document.createElement('td');
            actionTd.style.cssText = 'padding:4px 8px;';
            var btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'btn btn-sm';
            btn.style.cssText = 'font-size:0.8em;padding:2px 8px;';
            btn.textContent = T.api_token_revoke || 'Revoke';
            btn.setAttribute('data-token-id', tk.id);
            btn.setAttribute('data-token-name', tk.name);
            btn.addEventListener('click', function() {
                revokeToken(parseInt(this.getAttribute('data-token-id')), this.getAttribute('data-token-name'));
            });
            actionTd.appendChild(btn);
            tr.appendChild(actionTd);
            body.appendChild(tr);
        });
    }).catch(function() {});
}

function createApiToken() {
    var inp = document.getElementById('api-token-name');
    var name = (inp.value || '').trim();
    if (!name) { inp.focus(); return; }
    fetch(docsightUrl('/api/tokens'), {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: name})
    }).then(function(r) { return r.json().then(function(d) { return {ok: r.ok, data: d}; }); })
    .then(function(res) {
        if (!res.ok) { showToast(res.data.error || (T.error_prefix || 'Error'), false); return; }
        inp.value = '';
        var banner = document.getElementById('api-token-created-banner');
        document.getElementById('api-token-plaintext').textContent = res.data.token;
        banner.style.display = 'block';
        loadApiTokens();
        if (typeof lucide !== 'undefined') lucide.createIcons();
    }).catch(function() { showToast(T.error_prefix || 'Error', false); });
}

function copyToken() {
    var text = document.getElementById('api-token-plaintext').textContent;
    navigator.clipboard.writeText(text).then(function() {
        showToast(T.api_token_copied || 'Token copied!', true);
    });
}

function revokeToken(id, name) {
    var msg = (T.api_token_revoke_confirm || 'Revoke token "{name}"?').replace('{name}', name);
    docsightConfirm({
        title: T.api_token_revoke || 'Revoke token',
        message: msg,
        confirmText: T.revoke || 'Revoke',
        cancelText: T.cancel || 'Cancel',
        danger: true
    }).then(function(confirmed) {
        if (!confirmed) return null;
        return fetch(docsightUrl('/api/tokens/' + id), {method: 'DELETE'});
    })
    .then(function(r) { return r ? r.json() : null; })
    .then(function(data) {
        if (!data) return;
        if (data.success) {
            showToast(T.api_token_revoked || 'Token revoked', true);
            document.getElementById('api-token-created-banner').style.display = 'none';
            loadApiTokens();
        } else {
            showToast(data.error || (T.error_prefix || 'Error'), false);
        }
    }).catch(function() { showToast(T.error_prefix || 'Error', false); });
}
return {loadApiTokens, createApiToken, copyToken};
};
