(function () {
    'use strict';

    var element = document.getElementById('docsight-settings-bootstrap');
    var bootstrap = DOCSightBrowserContracts.parseSettingsBootstrapText(
        element && element.textContent
    );

    window.T = bootstrap.translations;
    window.__t = bootstrap.translations;
    // Section titles come from the section index, which lists every section once.
    window.SECTION_TITLES = {};
    document.querySelectorAll('.settings-index-item[data-section]').forEach(function (item) {
        var title = item.querySelector('.settings-index-title') || item;
        SECTION_TITLES[item.getAttribute('data-section')] = title.textContent.trim();
    });

    window.serverOffsetMin = bootstrap.serverOffsetMin;
    window.serverTz = bootstrap.serverTimezone;
    window.currentLang = bootstrap.language;
    window.currentTz = bootstrap.currentTimezone;
    /* Same timestamp display as the dashboard: UI language, configured zone. */
    window.formatDocsightTime = function(value, style, seconds) {
        return DOCSightBrowserContracts.formatTimestamp(value, {
            locale: bootstrap.language || document.documentElement.lang || undefined,
            timeZone: bootstrap.currentTimezone || bootstrap.serverTimezone,
            style: style || 'datetime',
            seconds: !!seconds
        });
    };
    window.savedCooldowns = bootstrap.notificationCooldowns;
    window.DRIVER_HINTS = bootstrap.driverHints;
    window.MODULE_SECRET_FIELDS = bootstrap.moduleSecretFields;
    window.SAVED_MODULE_SECRET_FIELDS = bootstrap.savedModuleSecretFields;
})();
