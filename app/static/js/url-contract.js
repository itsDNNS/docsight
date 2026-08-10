(function() {
    'use strict';

    var contractError = 'DOCSight browser URL contract is unavailable';

    function isControlCharacter(value) {
        for (var i = 0; i < value.length; i++) {
            var code = value.charCodeAt(i);
            if (code < 32 || code === 127) return true;
        }
        return false;
    }

    function validBasePath(value) {
        if (value === '') return true;
        if (typeof value !== 'string' || value.charAt(0) !== '/' || value.charAt(1) === '/') return false;
        if (value.charAt(value.length - 1) === '/' || value.length > 1024) return false;
        if (value.indexOf('\\') !== -1 || value.indexOf('%') !== -1 || value.indexOf('?') !== -1 || value.indexOf('#') !== -1) return false;
        if (isControlCharacter(value)) return false;

        var segments = value.slice(1).split('/');
        for (var i = 0; i < segments.length; i++) {
            if (!segments[i] || segments[i] === '.' || segments[i] === '..' || segments[i].length > 128) return false;
            if (!/^[A-Za-z0-9._~-]+$/.test(segments[i])) return false;
        }
        return true;
    }

    function hasDotSegment(pathname) {
        var segments = pathname.split('/');
        for (var i = 0; i < segments.length; i++) {
            if (segments[i] === '.' || segments[i] === '..') return true;
        }
        return false;
    }

    function hasValidPercentEscapes(value) {
        for (var i = 0; i < value.length; i++) {
            if (value.charAt(i) !== '%') continue;
            if (i + 2 >= value.length || !/^[0-9A-Fa-f]{2}$/.test(value.slice(i + 1, i + 3))) return false;
            i += 2;
        }
        return true;
    }

    function validateEncodedPath(pathname) {
        var candidate = pathname;

        for (var depth = 0; depth < 16; depth++) {
            if (hasDotSegment(candidate)) return false;

            var next = '';
            var decodedPercent = false;
            for (var i = 0; i < candidate.length; i++) {
                var character = candidate.charAt(i);
                if (character !== '%') {
                    next += character;
                    continue;
                }
                if (i + 2 >= candidate.length || !/^[0-9A-Fa-f]{2}$/.test(candidate.slice(i + 1, i + 3))) return false;

                var encoded = candidate.slice(i + 1, i + 3);
                var byte = parseInt(encoded, 16);
                if (byte === 0x2e || byte === 0x2f || byte === 0x5c || byte < 0x20 || byte === 0x7f) return false;
                if (byte === 0x25) {
                    next += '%';
                    decodedPercent = true;
                } else {
                    next += '%' + encoded;
                }
                i += 2;
            }

            if (!decodedPercent) return true;
            candidate = next;
        }
        return false;
    }

    function validInternalUrl(value) {
        if (typeof value !== 'string' || value.length === 0) return false;
        if (value.charAt(0) !== '/' || value.charAt(1) === '/') return false;
        if (value.indexOf('\\') !== -1 || isControlCharacter(value)) return false;
        if (!hasValidPercentEscapes(value)) return false;

        var query = value.indexOf('?');
        var fragment = value.indexOf('#');
        var boundary = value.length;
        if (query !== -1 && query < boundary) boundary = query;
        if (fragment !== -1 && fragment < boundary) boundary = fragment;
        return validateEncodedPath(value.slice(0, boundary));
    }

    var element = document.getElementById('docsight-url-bootstrap');
    var bootstrap;
    try {
        bootstrap = element && JSON.parse(element.textContent);
    } catch (error) {
        throw new Error(contractError);
    }
    if (!bootstrap || Object.prototype.toString.call(bootstrap) !== '[object Object]') throw new Error(contractError);
    var keys = Object.keys(bootstrap);
    if (keys.length !== 1 || keys[0] !== 'basePath' || !validBasePath(bootstrap.basePath)) throw new Error(contractError);

    var basePath = '';
    if (bootstrap.basePath) {
        var segments = bootstrap.basePath.slice(1).split('/');
        var canonicalSegments = [];
        for (var segmentIndex = 0; segmentIndex < segments.length; segmentIndex++) {
            canonicalSegments.push(encodeURIComponent(segments[segmentIndex]));
        }
        basePath = '/' + canonicalSegments.join('/');
    }
    Object.defineProperty(window, 'docsightUrl', {
        configurable: false,
        writable: false,
        value: function(path) {
            if (!validInternalUrl(path)) throw new TypeError('DOCSight URL must be a safe root-relative internal URL');
            if (!basePath) return path;

            var query = path.indexOf('?');
            var fragment = path.indexOf('#');
            var boundary = path.length;
            if (query !== -1 && query < boundary) boundary = query;
            if (fragment !== -1 && fragment < boundary) boundary = fragment;
            var pathname = path.slice(0, boundary);
            if (pathname === basePath || pathname.indexOf(basePath + '/') === 0) return path;
            return basePath + path;
        }
    });
})();
