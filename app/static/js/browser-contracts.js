(function (root, factory) {
    'use strict';
    var api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) Object.defineProperty(root, 'DOCSightBrowserContracts', {
        configurable: false,
        writable: false,
        value: api
    });
})(typeof window !== 'undefined' ? window : null, function () {
    'use strict';

    var BOOTSTRAP_ERROR = 'Invalid DOCSight bootstrap data';
    var UNSAFE_KEYS = {__proto__: true, constructor: true, prototype: true};
    var DRIVER_HINT_KEYS = {
        needs_user: true,
        needs_password: true,
        default_url: true,
        default_user: true,
        username_required: true,
        credentials_required: true,
        url_hint: true,
        user_hint: true,
        password_hint: true
    };

    function failBootstrap() {
        throw new Error(BOOTSTRAP_ERROR);
    }

    function isRecord(value) {
        return value !== null && Object.prototype.toString.call(value) === '[object Object]';
    }

    function hasExactKeys(value, expected) {
        var actual = Object.keys(value).sort();
        var wanted = expected.slice().sort();
        if (actual.length !== wanted.length) return false;
        for (var i = 0; i < actual.length; i++) {
            if (actual[i] !== wanted[i]) return false;
        }
        return true;
    }

    function isSafeJson(value, depth) {
        depth = depth || 0;
        if (depth > 12) return false;
        if (value === null || typeof value === 'boolean') return true;
        if (typeof value === 'number') return Number.isFinite(value);
        if (typeof value === 'string') return value.length <= 20000;
        if (Array.isArray(value)) {
            if (value.length > 5000) return false;
            return value.every(function (item) { return isSafeJson(item, depth + 1); });
        }
        if (!isRecord(value) || Object.keys(value).length > 5000) return false;
        return Object.keys(value).every(function (key) {
            return key.length <= 256 && !UNSAFE_KEYS[key] && isSafeJson(value[key], depth + 1);
        });
    }

    function parseRecord(text, keys) {
        if (typeof text !== 'string' || text.length === 0 || text.length > 1000000) failBootstrap();
        var value;
        try {
            value = JSON.parse(text);
        } catch (error) {
            failBootstrap();
        }
        if (!isRecord(value) || !hasExactKeys(value, keys) || !isSafeJson(value)) failBootstrap();
        return value;
    }

    function validLanguage(value) {
        return value === null || (typeof value === 'string' && /^[A-Za-z]{2}(?:-[A-Za-z0-9]{2,8})?$/.test(value));
    }

    function validTranslationRecord(value) {
        return isRecord(value) && isSafeJson(value);
    }

    function validateDriverHints(value) {
        if (!isRecord(value)) failBootstrap();
        Object.keys(value).forEach(function (driverId) {
            if (!/^[A-Za-z0-9._-]{1,128}$/.test(driverId) || !isRecord(value[driverId])) failBootstrap();
            Object.keys(value[driverId]).forEach(function (key) {
                var hint = value[driverId][key];
                if (!DRIVER_HINT_KEYS[key]) failBootstrap();
                if (key === 'needs_user' || key === 'needs_password' || key === 'username_required' || key === 'credentials_required') {
                    if (typeof hint !== 'boolean') failBootstrap();
                } else if (hint !== null && typeof hint !== 'string') {
                    failBootstrap();
                }
            });
            var defaultUrl = value[driverId].default_url;
            if (defaultUrl) {
                var parsed;
                try { parsed = new URL(defaultUrl); } catch (error) { failBootstrap(); }
                if ((parsed.protocol !== 'http:' && parsed.protocol !== 'https:') || parsed.username || parsed.password) failBootstrap();
            }
        });
        return value;
    }

    function parseDashboardBootstrapText(text) {
        var value = parseRecord(text, [
            'translations', 'language', 'temperatureUnit', 'connectionMonitorAvailable'
        ]);
        if (!validTranslationRecord(value.translations) || !validLanguage(value.language)) failBootstrap();
        if (value.temperatureUnit !== 'celsius' && value.temperatureUnit !== 'fahrenheit') failBootstrap();
        if (typeof value.connectionMonitorAvailable !== 'boolean') failBootstrap();
        return value;
    }

    function validInternalCandidate(value) {
        return typeof value === 'string' && value.charAt(0) === '/' && value.charAt(1) !== '/';
    }

    function parseSetupBootstrapText(text) {
        var value = parseRecord(text, ['translations', 'driverHints', 'indexUrl', 'loginUrl']);
        if (!validTranslationRecord(value.translations)) failBootstrap();
        validateDriverHints(value.driverHints);
        if (!validInternalCandidate(value.indexUrl) || !validInternalCandidate(value.loginUrl)) failBootstrap();
        return value;
    }

    function parseConnectionMonitorBootstrapText(text) {
        var value = parseRecord(text, ['label', 'host', 'remove']);
        if (typeof value.label !== 'string' || typeof value.host !== 'string' || typeof value.remove !== 'string') failBootstrap();
        return value;
    }

    function validModule(value) {
        return isRecord(value) && hasExactKeys(value, ['id', 'labelKey', 'name']) &&
            typeof value.id === 'string' && /^[a-z][a-z0-9_.]+$/.test(value.id) &&
            typeof value.labelKey === 'string' &&
            typeof value.name === 'string';
    }

    function validStringList(value) {
        return Array.isArray(value) && value.every(function (item) {
            return typeof item === 'string';
        });
    }

    function parseSettingsBootstrapText(text) {
        var value = parseRecord(text, [
            'translations', 'modules', 'serverOffsetMin', 'serverTimezone', 'language',
            'currentTimezone', 'notificationCooldowns', 'driverHints',
            'moduleSecretFields', 'savedModuleSecretFields'
        ]);
        if (!validTranslationRecord(value.translations) || !Array.isArray(value.modules) || !value.modules.every(validModule)) failBootstrap();
        if (typeof value.serverOffsetMin !== 'number' || !Number.isFinite(value.serverOffsetMin) || Math.abs(value.serverOffsetMin) > 1440) failBootstrap();
        if (typeof value.serverTimezone !== 'string' || value.serverTimezone.length > 128) failBootstrap();
        if (!validLanguage(value.language) || (value.currentTimezone !== null && typeof value.currentTimezone !== 'string')) failBootstrap();
        if (typeof value.notificationCooldowns !== 'string' || value.notificationCooldowns.length > 100000) failBootstrap();
        validateDriverHints(value.driverHints);
        if (!validStringList(value.moduleSecretFields) || !validStringList(value.savedModuleSecretFields)) failBootstrap();
        if (!value.savedModuleSecretFields.every(function (key) { return value.moduleSecretFields.indexOf(key) !== -1; })) failBootstrap();

        var cooldowns = {};
        try {
            var candidate = JSON.parse(value.notificationCooldowns);
            if (isRecord(candidate) && isSafeJson(candidate)) cooldowns = candidate;
        } catch (error) {
            cooldowns = {};
        }
        return {
            translations: value.translations,
            modules: value.modules,
            serverOffsetMin: value.serverOffsetMin,
            serverTimezone: value.serverTimezone,
            language: value.language,
            currentTimezone: value.currentTimezone || '',
            notificationCooldowns: cooldowns,
            driverHints: value.driverHints,
            moduleSecretFields: value.moduleSecretFields,
            savedModuleSecretFields: value.savedModuleSecretFields
        };
    }

    function selectSetupDriverState(driverHints, modemType, currentUrl, currentUsername, notRequiredText) {
        var hints = isRecord(driverHints) && isRecord(driverHints[modemType]) ? driverHints[modemType] : {};
        var knownDefaults = {};
        Object.keys(driverHints || {}).forEach(function (key) {
            var hint = driverHints[key];
            if (isRecord(hint) && hint.default_url) knownDefaults[hint.default_url] = true;
        });
        var url = currentUrl || '';
        if (hints.default_url && (!url || knownDefaults[url])) url = hints.default_url;
        var credentialsVisible = hints.credentials_required !== false;
        var usernameEnabled = credentialsVisible && hints.username_required !== false;
        var username = usernameEnabled ? (currentUsername || '') : '';
        var placeholder = usernameEnabled ? (hints.default_user || 'admin') : (notRequiredText || 'Not required');
        if (usernameEnabled && !username && hints.default_user) username = hints.default_user;
        return {
            url: url,
            credentialsVisible: credentialsVisible,
            usernameEnabled: usernameEnabled,
            username: username,
            usernamePlaceholder: placeholder
        };
    }

    function formatLastKnownTimestamp(value, formatter) {
        if (!value) return '';
        try {
            return formatter ? formatter(value) : new Date(value).toLocaleString();
        } catch (error) {
            return value;
        }
    }

    function computeServiceWorkerPolicy(hostname, search, scopeHref) {
        var scope;
        try { scope = new URL(scopeHref); } catch (error) { throw new Error('Invalid service-worker scope'); }
        if ((scope.protocol !== 'http:' && scope.protocol !== 'https:') || scope.search || scope.hash || !scope.pathname.endsWith('/')) {
            throw new Error('Invalid service-worker scope');
        }
        var params = new URLSearchParams(typeof search === 'string' ? search : '');
        var local = hostname === 'localhost' || hostname === '127.0.0.1';
        return {
            action: local && !params.has('enable-sw-test') ? 'cleanup' : 'register',
            scopeHref: scope.href,
            cacheNamespace: 'docsight-' + encodeURIComponent(scope.pathname) + '-'
        };
    }

    return {
        parseDashboardBootstrapText: parseDashboardBootstrapText,
        parseSetupBootstrapText: parseSetupBootstrapText,
        parseSettingsBootstrapText: parseSettingsBootstrapText,
        parseConnectionMonitorBootstrapText: parseConnectionMonitorBootstrapText,
        selectSetupDriverState: selectSetupDriverState,
        formatLastKnownTimestamp: formatLastKnownTimestamp,
        computeServiceWorkerPolicy: computeServiceWorkerPolicy
    };
});
