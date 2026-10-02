/* Resolve light/dark before first paint: this browser's choice, then an explicitly
   saved server theme, then the operating system preference. Setup used to store
   its choice under "theme". Loaded synchronously in <head>. */
(function () {
    'use strict';
    var script = document.currentScript;
    var serverExplicit = !!(script && script.getAttribute('data-theme-explicit') === 'true');
    var stored = null;
    try {
        stored = localStorage.getItem('docsis-theme');
        var legacy = localStorage.getItem('theme');
        if (stored !== 'light' && stored !== 'dark' && (legacy === 'light' || legacy === 'dark')) {
            stored = legacy;
            localStorage.setItem('docsis-theme', legacy);
        }
    } catch (error) {}
    var theme = stored === 'light' || stored === 'dark' ? stored : null;
    if (!theme && !serverExplicit && window.matchMedia) {
        theme = window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
    }
    if (theme) document.documentElement.setAttribute('data-theme', theme);
})();
