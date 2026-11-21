(function() {
    'use strict';

    // A dashboard refresh can replace the banner at any time, so it is looked up on use.
    function setBanner(disabled, message) {
        document.getElementById('demo-banner').querySelectorAll('button').forEach(function(item) { item.disabled = disabled; });
        document.getElementById('demo-banner-result').textContent = message;
    }

    var leaving = false;

    window.leaveDemo = async function(nextChoice, button) {
        if (leaving || button.disabled || !document.getElementById('demo-banner-result')) return;

        var message = (window.T && window.T.demo_migrate_confirm) ||
            'This will remove the demo data. Your own entries will be kept. Continue?';
        var confirmed = await window.docsightConfirm({
            title: (window.T && window.T.demo_migrate_title) || 'Demo Mode Active',
            message: message,
            confirmText: (window.T && window.T.demo_migrate_button) || 'Leave Demo Mode',
            cancelText: (window.T && window.T.cancel) || 'Cancel',
            danger: true
        });
        if (!confirmed || leaving) return;
        leaving = true;  // a refreshed banner must not start a second exit
        setBanner(true, '');

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
            leaving = false;
            setBanner(false, (window.T && window.T.demo_action_failed) || 'The demo could not be closed. Please try again.');
        }
    };

    /* The banner also appears on the settings page, and a dashboard refresh replaces it,
       so its buttons are handled from the document. */
    var choices = {'demo-connect-modem': 'connect', 'demo-exit': 'exit'};
    document.addEventListener('click', function(event) {
        var button = event.target.closest && event.target.closest('#demo-connect-modem, #demo-exit');
        if (button) window.leaveDemo(choices[button.id], button);
    });
})();
