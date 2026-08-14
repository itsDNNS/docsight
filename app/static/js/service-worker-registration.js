if ('serviceWorker' in navigator) {
    var docsightServiceWorkerScope = new URL(docsightUrl('/'), window.location.origin).href;
    var docsightServiceWorkerPolicy = DOCSightBrowserContracts.computeServiceWorkerPolicy(
        window.location.hostname, window.location.search, docsightServiceWorkerScope
    );
    var docsightCacheNamespace = docsightServiceWorkerPolicy.cacheNamespace;
    if (docsightServiceWorkerPolicy.action === 'cleanup') {
        navigator.serviceWorker.getRegistrations()
            .then(function(registrations) {
                return Promise.all(registrations.filter(function(registration) {
                    return registration.scope === docsightServiceWorkerScope;
                }).map(function(registration) {
                    return registration.unregister();
                }));
            })
            .then(function() {
                if (!window.caches) return;
                return caches.keys().then(function(keys) {
                    return Promise.all(keys.filter(function(key) {
                        return key.indexOf(docsightCacheNamespace) === 0;
                    }).map(function(key) { return caches.delete(key); }));
                });
            })
            .catch(function(err) { console.warn('SW cleanup failed:', err); });
    } else {
        navigator.serviceWorker.register(docsightUrl('/sw.js'), { scope: docsightUrl('/') })
            .catch(function(err) { console.warn('SW registration failed:', err); });
    }
}
