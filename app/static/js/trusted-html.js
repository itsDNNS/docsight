/* The one Trusted Types policy. Every HTML string DOCSight writes into the page
   passes through docsightHTML(); the markup is built by DOCSight's own scripts,
   which escape outside values with escapeHtml before this point. Script URLs
   (the service worker) pass through docsightScriptURL() and must stay on this
   origin. The CSP names only this policy, so the browser reports anything that
   reaches a sink any other way. Loaded first, before every script that writes HTML. */
(function () {
    'use strict';
    function sameOrigin(url) {
        var parsed = new URL(url, window.location.href);
        if (parsed.origin !== window.location.origin) throw new TypeError('Scripts must come from DOCSight: ' + url);
        return parsed.href;
    }
    var policy = window.trustedTypes && typeof window.trustedTypes.createPolicy === 'function'
        ? window.trustedTypes.createPolicy('docsight', {
            createHTML: function (html) { return html; },
            createScriptURL: sameOrigin
        })
        : null;
    window.docsightHTML = function (html) {
        return policy ? policy.createHTML(String(html)) : String(html);
    };
    window.docsightScriptURL = function (url) {
        return policy ? policy.createScriptURL(String(url)) : sameOrigin(String(url));
    };
})();
