(function() {
    'use strict';

    // Store chart instances globally to prevent memory leaks on refresh
    window.donutCharts = window.donutCharts || {};

    function renderDonut(canvasId) {
        var c = document.getElementById(canvasId);
        if (!c) return;
        var container = c.parentElement;
        if (!container) return;

        var good = parseInt(container.getAttribute('data-good') || '0', 10);
        var tolerated = parseInt(container.getAttribute('data-tolerated') || '0', 10);
        var warn = parseInt(container.getAttribute('data-warn') || '0', 10);
        var crit = parseInt(container.getAttribute('data-crit') || '0', 10);
        var total = good + tolerated + warn + crit;
        if (total === 0) return;

        // Match mockup: raw Canvas arcs with thin stroke
        var dpr = window.devicePixelRatio || 1;
        var size = c.parentElement.offsetWidth || 80;
        c.width = size * dpr;
        c.height = size * dpr;
        c.style.width = size + 'px';
        c.style.height = size + 'px';
        var x = c.getContext('2d');
        x.scale(dpr, dpr);

        var cx = size / 2, cy = size / 2, r = size * 0.38, lw = size * 0.08;
        var styles = getComputedStyle(document.documentElement);
        var segments = [
            { val: good, color: styles.getPropertyValue('--good').trim() },
            { val: tolerated, color: styles.getPropertyValue('--tolerated').trim() },
            { val: warn, color: styles.getPropertyValue('--warn').trim() },
            { val: crit, color: styles.getPropertyValue('--crit').trim() }
        ];

        // Background ring
        x.beginPath();
        x.arc(cx, cy, r, 0, Math.PI * 2);
        x.strokeStyle = 'rgba(255,255,255,0.06)';
        x.lineWidth = lw;
        x.stroke();

        // Colored segments
        var angle = -Math.PI / 2;
        segments.forEach(function(s) {
            if (s.val === 0) return;
            var sweep = (s.val / total) * Math.PI * 2;
            x.beginPath();
            x.arc(cx, cy, r, angle, angle + sweep);
            x.strokeStyle = s.color;
            x.lineWidth = lw;
            x.lineCap = 'round';
            x.stroke();
            angle += sweep;
        });
    }

    function initDonuts() {
        renderDonut('ds-health-donut');
        renderDonut('us-health-donut');
    }

    // Expose refresh function globally for manual updates (refreshData after innerHTML replace)
    window.refreshDonuts = initDonuts;

    // Wait for DOM to be fully loaded
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initDonuts);
    } else {
        // DOM already loaded (script deferred or loaded late)
        initDonuts();
    }
})();
