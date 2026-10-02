(function () {
    'use strict';

    var element = document.getElementById('docsight-settings-bootstrap');
    var bootstrap = DOCSightBrowserContracts.parseSettingsBootstrapText(
        element && element.textContent
    );

    window.T = bootstrap.translations;
    window.__t = bootstrap.translations;
    window.SECTION_TITLES = {
        connection: T.step_modem || 'Connection',
        general: T.general || 'General',
        notifications: T.notifications || 'Notifications',
        smart_capture: T.smart_capture || 'Smart Capture',
        appearance: T.appearance || 'Appearance',
        security: T.security || 'Security',
        extensions: T.settings_extensions || 'Extensions',
        about: T.about_project || 'About Project',
        support: T.support_title || 'Support DOCSight'
    };
    bootstrap.modules.forEach(function (module) {
        var sectionId = 'mod-' + module.id.replace(/\./g, '_');
        SECTION_TITLES[sectionId] = T[module.labelKey] || module.name;
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
