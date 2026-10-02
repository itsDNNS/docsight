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
            'translations', 'language', 'temperatureUnit', 'connectionMonitorAvailable', 'timeZone'
        ]);
        if (!validTranslationRecord(value.translations) || !validLanguage(value.language)) failBootstrap();
        if (value.temperatureUnit !== 'celsius' && value.temperatureUnit !== 'fahrenheit') failBootstrap();
        if (typeof value.connectionMonitorAvailable !== 'boolean') failBootstrap();
        if (value.timeZone !== null && typeof value.timeZone !== 'string') failBootstrap();
        if (!validTimeZone(value.timeZone)) value.timeZone = null;
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

    var NAIVE_TIMESTAMP = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?)?$/;

    function validTimeZone(value) {
        if (typeof value !== 'string' || !value) return false;
        try {
            new Intl.DateTimeFormat('en', {timeZone: value});
            return true;
        } catch (error) {
            return false;
        }
    }

    function zoneOffsetMs(timeZone, instantMs) {
        // Offset of the zone at an instant: its wall-clock fields read as UTC, minus the instant.
        var parts = {};
        new Intl.DateTimeFormat('en-US', {
            timeZone: timeZone, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit',
            hour: '2-digit', minute: '2-digit', second: '2-digit'
        }).formatToParts(new Date(instantMs)).forEach(function (part) { parts[part.type] = part.value; });
        var asUtc = Date.UTC(+parts.year, +parts.month - 1, +parts.day, +parts.hour, +parts.minute, +parts.second);
        return asUtc - Math.floor(instantMs / 1000) * 1000;
    }

    function parseTimestamp(value, timeZone) {
        // Absolute instant for chart positions. Naive "YYYY-MM-DD[THH:MM[:SS]]" values are
        // wall-clock time in the given zone (DOCSight's configured zone); values with
        // Z/offset, epoch seconds or milliseconds, and Date objects are already absolute.
        if (value instanceof Date) return value;
        if (typeof value === 'number') return new Date(Math.abs(value) < 1e11 ? value * 1000 : value);
        var naive = typeof value === 'string' ? NAIVE_TIMESTAMP.exec(value.trim()) : null;
        if (!naive || !validTimeZone(timeZone)) return new Date(value);
        var wallClock = Date.UTC(+naive[1], +naive[2] - 1, +naive[3],
            +(naive[4] || 0), +(naive[5] || 0), +(naive[6] || 0));
        var guess = wallClock - zoneOffsetMs(timeZone, wallClock);
        // Re-check at the guessed instant so DST transitions resolve to the right offset.
        return new Date(wallClock - zoneOffsetMs(timeZone, guess));
    }

    function formatTimestamp(value, options) {
        // Absolute instants (ISO with Z/offset, epoch numbers, Date) render in the
        // configured time zone. Naive server timestamps are already local wall-clock
        // time and date-only values are calendar dates, so both keep their fields.
        if (value === null || value === undefined || value === '') return '';
        var opts = options || {};
        var style = opts.style || 'datetime';
        var date = null;
        var timeZone = validTimeZone(opts.timeZone) ? opts.timeZone : undefined;
        var naive = typeof value === 'string' ? NAIVE_TIMESTAMP.exec(value.trim()) : null;
        if (naive) {
            date = new Date(Date.UTC(+naive[1], +naive[2] - 1, +naive[3],
                +(naive[4] || 0), +(naive[5] || 0), +(naive[6] || 0)));
            timeZone = 'UTC';
            if (naive[4] === undefined && style !== 'time') style = style.indexOf('monthday') === 0 ? 'monthday' : 'date';
        } else if (typeof value === 'number') {
            date = new Date(Math.abs(value) < 1e11 ? value * 1000 : value);
        } else {
            date = value instanceof Date ? value : new Date(value);
        }
        if (!date || isNaN(date.getTime())) return String(value);
        // Styles: 'datetime', 'date', 'time', and the year-less 'monthday' and
        // 'monthday-time' used for compact chart axes.
        var parts = {};
        if (style !== 'time') {
            if (style.indexOf('monthday') !== 0) parts.year = 'numeric';
            parts.month = '2-digit';
            parts.day = '2-digit';
        }
        if (style !== 'date' && style !== 'monthday') {
            parts.hour = '2-digit';
            parts.minute = '2-digit';
            if (opts.seconds) parts.second = '2-digit';
        }
        if (timeZone) parts.timeZone = timeZone;
        try {
            return new Intl.DateTimeFormat(opts.locale || undefined, parts).format(date);
        } catch (error) {
            return new Intl.DateTimeFormat(undefined, parts).format(date);
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
        formatTimestamp: formatTimestamp,
        parseTimestamp: parseTimestamp,
        computeServiceWorkerPolicy: computeServiceWorkerPolicy
    };
});
