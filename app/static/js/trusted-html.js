/* The one Trusted Types policy. Every HTML string DOCSight writes into the page
   passes through docsightHTML(); the markup is built by DOCSight's own scripts,
   which escape outside values with escapeHtml before this point. The CSP names
   only this policy, so the browser reports HTML that reaches a sink any other way.
   Loaded first, before every script that writes HTML. */
(function () {
    'use strict';
    var policy = window.trustedTypes && typeof window.trustedTypes.createPolicy === 'function'
        ? window.trustedTypes.createPolicy('docsight', {createHTML: function (html) { return html; }})
        : null;
    window.docsightHTML = function (html) {
        return policy ? policy.createHTML(String(html)) : String(html);
    };
})();
