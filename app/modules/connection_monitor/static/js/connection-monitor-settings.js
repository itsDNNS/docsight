(function () {
    var listEl = document.getElementById('cm-targets-list');
    var addBtn = document.getElementById('cm-add-target-btn');
    var bootstrapElement = document.getElementById('docsight-connection-monitor-settings-bootstrap');
    var i18n = DOCSightBrowserContracts.parseConnectionMonitorBootstrapText(
        bootstrapElement && bootstrapElement.textContent
    );

    function makeInput(id, value, placeholder) {
        var el = document.createElement('input');
        el.className = 'form-input';
        el.type = 'text';
        el.id = id;
        el.value = value || '';
        el.placeholder = placeholder || '';
        return el;
    }

    function makeLabel(forId, text) {
        var el = document.createElement('label');
        el.className = 'form-label';
        el.htmlFor = forId;
        el.textContent = text;
        return el;
    }

    function renderTarget(target) {
        var row = document.createElement('div');
        row.className = 'form-grid cols-2';
        row.style.cssText = 'align-items: end; margin-bottom: var(--space-sm);';
        row.dataset.targetId = target.id;

        // Label field
        var labelField = document.createElement('div');
        labelField.className = 'form-field';
        var labelInput = makeInput('cm-label-' + target.id, target.label, 'Gateway');
        labelInput.dataset.field = 'label';
        labelField.appendChild(makeLabel('cm-label-' + target.id, i18n.label));
        labelField.appendChild(labelInput);

        // Host field + remove button wrapper
        var hostField = document.createElement('div');
        hostField.className = 'form-field';
        hostField.style.cssText = 'display: flex; gap: var(--space-sm); align-items: flex-end;';

        var hostWrap = document.createElement('div');
        hostWrap.style.flex = '1';
        var hostInput = makeInput('cm-host-' + target.id, target.host, '8.8.8.8');
        hostInput.dataset.field = 'host';
        hostWrap.appendChild(makeLabel('cm-host-' + target.id, i18n.host));
        hostWrap.appendChild(hostInput);

        var removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'btn btn-ghost btn-sm';
        removeBtn.style.flexShrink = '0';
        removeBtn.dataset.remove = target.id;

        var trashIcon = document.createElement('i');
        trashIcon.setAttribute('data-lucide', 'trash-2');
        trashIcon.style.cssText = 'width:14px;height:14px;';
        var removeText = document.createElement('span');
        removeText.style.marginLeft = '4px';
        removeText.textContent = i18n.remove;
        removeBtn.appendChild(trashIcon);
        removeBtn.appendChild(removeText);

        hostField.appendChild(hostWrap);
        hostField.appendChild(removeBtn);

        row.appendChild(labelField);
        row.appendChild(hostField);

        // Save on blur
        [labelInput, hostInput].forEach(function (input) {
            input.addEventListener('blur', function () {
                var patch = {};
                patch[input.dataset.field] = input.value.trim();
                if (!patch[input.dataset.field]) return;
                fetch(docsightUrl('/api/connection-monitor/targets/' + target.id), {
                    method: 'PUT',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(patch)
                }).then(function (res) {
                    if (res.ok) {
                        input.style.borderColor = 'var(--success, #10b981)';
                        setTimeout(function () { input.style.borderColor = ''; }, 1500);
                    }
                });
            });
        });

        // Remove target
        removeBtn.addEventListener('click', function () {
            var tid = removeBtn.dataset.remove;
            fetch(docsightUrl('/api/connection-monitor/targets/' + tid), {method: 'DELETE'})
                .then(function (res) {
                    if (res.ok) row.remove();
                });
        });

        if (window.lucide) window.lucide.createIcons({nameAttr: 'data-lucide', nodes: [row]});
        return row;
    }

    function loadTargets() {
        fetch(docsightUrl('/api/connection-monitor/targets'))
            .then(function (res) { return res.json(); })
            .then(function (targets) {
                while (listEl.firstChild) listEl.removeChild(listEl.firstChild);
                targets.forEach(function (target) {
                    listEl.appendChild(renderTarget(target));
                });
            })
            .catch(function () {});
    }

    addBtn.addEventListener('click', function () {
        fetch(docsightUrl('/api/connection-monitor/targets'), {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({label: 'New target', host: ''})
        })
            .then(function (res) { return res.json(); })
            .then(function (data) {
                if (data.id) {
                    var newRow = renderTarget({id: data.id, label: 'New target', host: ''});
                    listEl.appendChild(newRow);
                    if (window.lucide) window.lucide.createIcons({nameAttr: 'data-lucide'});
                    var hostInput = document.getElementById('cm-host-' + data.id);
                    if (hostInput) hostInput.focus();
                }
            })
            .catch(function () {});
    });

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', loadTargets);
    } else {
        loadTargets();
    }
})();
