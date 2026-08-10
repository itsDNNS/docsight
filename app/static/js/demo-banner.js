(function() {
    'use strict';

    window.leaveDemo = async function(nextChoice, button) {
        var banner = document.getElementById('demo-banner');
        var result = document.getElementById('demo-banner-result');
        if (!banner || !result || button.disabled) return;

        var message = (window.T && window.T.demo_migrate_confirm) ||
            'This will remove the demo data. Your own entries will be kept. Continue?';
        var confirmed = await window.docsightConfirm({
            title: (window.T && window.T.demo_migrate_title) || 'Demo Mode Active',
            message: message,
            confirmText: (window.T && window.T.demo_migrate_button) || 'Leave Demo Mode',
            cancelText: (window.T && window.T.cancel) || 'Cancel',
            danger: true
        });
        if (!confirmed) return;

        var buttons = banner.querySelectorAll('button');
        buttons.forEach(function(item) { item.disabled = true; });
        result.textContent = '';

        try {
            var response = await fetch(docsightUrl('/api/demo/migrate'), {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({next: nextChoice})
            });
            if (response.status === 401 || response.status === 403) {
                window.location.assign(docsightUrl('/login'));
                return;
            }
            var payload = await response.json();
            if (!response.ok || !payload.success) throw new Error(payload.error || '');
            var expectedNext = {connect: '/setup?connect=1', exit: '/setup'}[nextChoice];
            if (!expectedNext || payload.next !== expectedNext) throw new Error('Invalid redirect');
            window.location.assign(docsightUrl(expectedNext));
        } catch (error) {
            buttons.forEach(function(item) { item.disabled = false; });
            result.textContent = (window.T && window.T.demo_action_failed) || 'The demo could not be closed. Please try again.';
        }
    };
})();
