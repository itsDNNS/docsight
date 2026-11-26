/* Path checks shared by the page URL contract (url-contract.js) and the service
   worker's notification targets (sw.js, via importScripts). No document access,
   so the same file runs in both. */
(function () {
    'use strict';

    function hasControlCharacter(value) {
        for (var i = 0; i < value.length; i++) {
            var code = value.charCodeAt(i);
            if (code < 32 || code === 127) return true;
        }
        return false;
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

    /* Rejects dot segments and encoded '.', '/', '\' or control bytes, also when
       they hide behind repeated %25 encoding. */
    function hasSafeEncodedPath(pathname) {
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

    function pathnameOf(url) {
        return url.split(/[?#]/, 1)[0];
    }

    Object.defineProperty(self, 'DOCSightUrlSafety', {
        value: Object.freeze({
            hasControlCharacter: hasControlCharacter,
            hasValidPercentEscapes: hasValidPercentEscapes,
            hasSafeEncodedPath: hasSafeEncodedPath,
            pathnameOf: pathnameOf
        })
    });
})();
