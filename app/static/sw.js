var CACHE_VERSION = 'v67';
var SHELL_CACHE = 'docsight-shell-' + CACHE_VERSION;
var STATIC_CACHE = 'docsight-static-' + CACHE_VERSION;
var OFFLINE_SHELL_HEADERS = {
  'X-DOCSight-Offline-Shell': 'true'
};

var SHELL_URLS = [
  '/',
  '/?source=pwa'
];

var CRITICAL_STATIC_URLS = [
  '/static/manifest.json',
  '/static/logo.svg',
  '/static/icon.png'
];

function sameOrigin(url) {
  return url.origin === self.location.origin;
}

function isApiRequest(url) {
  return url.pathname.indexOf('/api/') === 0 || url.pathname === '/health';
}

function isStaticRequest(url) {
  return url.pathname.indexOf('/static/') === 0 || url.pathname.indexOf('/modules/') === 0;
}

function isShellRequest(request, url) {
  return request.mode === 'navigate' ||
    (request.headers.get('accept') || '').indexOf('text/html') !== -1 ||
    url.pathname === '/';
}

function shellCacheKey(url) {
  if (url.pathname === '/') return '/';
  return url.pathname + url.search;
}

function markOfflineShell(response) {
  if (!response) return response;
  return response.text().then(function(body) {
    var marker = '<script>window.__DOCSIGHT_OFFLINE_SHELL__ = true;</script>';
    var markedBody = body.indexOf('__DOCSIGHT_OFFLINE_SHELL__') === -1
      ? body.replace('</head>', marker + '</head>')
      : body;
    var headers = new Headers(response.headers);
    Object.keys(OFFLINE_SHELL_HEADERS).forEach(function(key) {
      headers.set(key, OFFLINE_SHELL_HEADERS[key]);
    });
    return new Response(markedBody, {
      status: response.status,
      statusText: response.statusText,
      headers: headers
    });
  });
}

function handleApiRequest(request) {
  return fetch(request);
}

function handleShellRequest(request, url) {
  var key = shellCacheKey(url);
  return fetch(request)
    .then(function(res) {
      if (res.ok) {
        var clone = res.clone();
        caches.open(SHELL_CACHE).then(function(cache) { cache.put(key, clone); });
        if (url.pathname === '/' && key !== '/') {
          caches.open(SHELL_CACHE).then(function(cache) { cache.put('/', res.clone()); });
        }
      }
      return res;
    })
    .catch(function() {
      return caches.match(key)
        .then(function(match) { return match || caches.match('/'); })
        .then(markOfflineShell);
    });
}

function handleStaticRequest(request) {
  return caches.match(request).then(function(cached) {
    if (cached) return cached;
    return fetch(request).then(function(res) {
      if (res.ok) {
        var clone = res.clone();
        caches.open(STATIC_CACHE).then(function(cache) { cache.put(request.url, clone); });
      }
      return res;
    });
  });
}

self.addEventListener('install', function(e) {
  e.waitUntil(
    Promise.all([
      caches.open(SHELL_CACHE).then(function(cache) { return cache.addAll(SHELL_URLS); }),
      caches.open(STATIC_CACHE).then(function(cache) { return cache.addAll(CRITICAL_STATIC_URLS); })
    ])
  );
  self.skipWaiting();
});

self.addEventListener('activate', function(e) {
  var expectedCaches = [SHELL_CACHE, STATIC_CACHE];
  e.waitUntil(
    caches.keys().then(function(keys) {
      return Promise.all(keys.filter(function(key) {
        return expectedCaches.indexOf(key) === -1;
      }).map(function(key) { return caches.delete(key); }));
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', function(e) {
  var request = e.request;
  if (request.method !== 'GET') return;

  var url = new URL(request.url);
  if (!sameOrigin(url)) return;

  if (isApiRequest(url)) {
    e.respondWith(handleApiRequest(request));
    return;
  }

  if (isStaticRequest(url)) {
    e.respondWith(handleStaticRequest(request));
    return;
  }

  if (isShellRequest(request, url)) {
    e.respondWith(handleShellRequest(request, url));
  }
});

self.addEventListener('push', function(event) {
  var fallback = {
    title: 'DOCSight notification',
    body: 'Open DOCSight for the latest signal status.',
    url: '/?source=pwa#events',
    severity: 'info'
  };
  var payload = fallback;
  try {
    if (event.data) {
      payload = Object.assign({}, fallback, event.data.json());
    }
  } catch (err) {
    try {
      payload = Object.assign({}, fallback, { body: event.data ? event.data.text() : fallback.body });
    } catch (ignore) {
      payload = fallback;
    }
  }
  event.waitUntil(self.registration.showNotification(payload.title || fallback.title, {
    body: payload.body || fallback.body,
    icon: '/static/icon.png',
    badge: '/static/icon.png',
    tag: 'docsight-' + (payload.event_type || payload.severity || 'notification'),
    data: { url: payload.url || fallback.url }
  }));
});

function safeNotificationUrl(targetUrl) {
  try {
    var url = new URL(targetUrl, self.location.origin);
    if (url.origin === self.location.origin) {
      return url.pathname + url.search + url.hash;
    }
  } catch (err) {}
  return '/?source=pwa#events';
}

self.addEventListener('notificationclick', function(event) {
  event.notification.close();
  var targetUrl = safeNotificationUrl((event.notification.data && event.notification.data.url) || '/?source=pwa#events');
  event.waitUntil(clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function(clientList) {
    for (var i = 0; i < clientList.length; i += 1) {
      var client = clientList[i];
      if (client.url.indexOf(self.location.origin) === 0 && 'focus' in client) {
        return client.focus().then(function(focusedClient) {
          if ('navigate' in focusedClient) {
            return focusedClient.navigate(targetUrl);
          }
          return focusedClient;
        });
      }
    }
    if (clients.openWindow) {
      return clients.openWindow(targetUrl);
    }
    return undefined;
  }));
});
