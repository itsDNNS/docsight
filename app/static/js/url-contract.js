(function() {
    'use strict';

    var contractError = 'DOCSight browser URL contract is unavailable';
    var safety = window.DOCSightUrlSafety;

    function validBasePath(value) {
        if (value === '') return true;
        if (typeof value !== 'string' || value.charAt(0) !== '/' || value.charAt(1) === '/') return false;
        if (value.charAt(value.length - 1) === '/' || value.length > 1024) return false;
        if (value.indexOf('\\') !== -1 || value.indexOf('%') !== -1 || value.indexOf('?') !== -1 || value.indexOf('#') !== -1) return false;
        if (safety.hasControlCharacter(value)) return false;

        var segments = value.slice(1).split('/');
        for (var i = 0; i < segments.length; i++) {
            if (!segments[i] || segments[i] === '.' || segments[i] === '..' || segments[i].length > 128) return false;
            if (!/^[A-Za-z0-9._~-]+$/.test(segments[i])) return false;
        }
        return true;
    }

    function validInternalUrl(value) {
        if (typeof value !== 'string' || value.length === 0) return false;
        if (value.charAt(0) !== '/' || value.charAt(1) === '/') return false;
        if (value.indexOf('\\') !== -1 || safety.hasControlCharacter(value)) return false;
        if (!safety.hasValidPercentEscapes(value)) return false;
        return safety.hasSafeEncodedPath(safety.pathnameOf(value));
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
            var pathname = safety.pathnameOf(path);
            if (pathname === basePath || pathname.indexOf(basePath + '/') === 0) return path;
            return basePath + path;
        }
    });
})();
