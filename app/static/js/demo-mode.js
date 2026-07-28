(function() {
    'use strict';

    var pending = false;
    var fallbackPaths = {
        connect: '/setup?connect=1',
        exit: '/setup'
    };

    function setPending(isPending) {
        document.querySelectorAll('[data-demo-action]').forEach(function(button) {
            button.disabled = isPending;
        });
        var banner = document.getElementById('demo-mode-banner');
        if (banner) banner.setAttribute('aria-busy', isPending ? 'true' : 'false');
    }

    function setStatus(message, isError) {
        var status = document.getElementById('demo-mode-banner-status');
        if (!status) return;
        status.textContent = message;
        status.classList.toggle('error', Boolean(isError));
    }

    function exitDemoMode(action) {
        if (pending || !fallbackPaths[action]) return;
        pending = true;
        setPending(true);
        setStatus(T.demo_banner_pending, false);

        fetch('/api/demo/migrate', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({action: action})
        })
            .then(function(response) {
                return response.json().then(function(result) {
                    if (!response.ok || !result.success) throw new Error('exit');
                    return result;
                });
            })
            .then(function(result) {
                window.location.assign(result.next_path || fallbackPaths[action]);
            })
            .catch(function() {
                pending = false;
                setPending(false);
                setStatus(T.demo_banner_error, true);
            });
    }

    window.exitDemoMode = exitDemoMode;
})();
