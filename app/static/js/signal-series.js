/** One rolling signal series per dashboard generation. No theme dependency. */
(function() {
    'use strict';
    var generation = 0;
    var pending = null;
    var refreshScheduled = false;

    function invalidate() {
        generation++;
        pending = null;
        return generation;
    }

    function get() {
        if (pending) return pending;
        var requested = generation;
        var promise = fetch(docsightUrl('/api/trends/signal?range=1d'))
            .then(function(response) {
                if (!response.ok) throw new Error('API error: ' + response.status);
                return response.json();
            })
            .then(function(rows) {
                if (requested !== generation) throw new Error('Stale signal series');
                if (!Array.isArray(rows)) throw new Error('Invalid signal series');
                return rows;
            })
            .catch(function(error) {
                if (pending === promise) pending = null;
                throw error;
            });
        pending = promise;
        return promise;
    }

    // Public Hero/spark refresh calls made together share one new generation.
    function refresh() {
        if (!refreshScheduled) {
            invalidate();
            refreshScheduled = true;
            queueMicrotask(function() { refreshScheduled = false; });
        }
        return generation;
    }

    window.DOCSightSignalSeries = {
        get: get,
        invalidate: invalidate,
        refresh: refresh,
        generation: function() { return generation; },
        isCurrent: function(value) { return value === generation; }
    };
})();
