var CACHE_VERSION = 'v8';
var SHELL_CACHE = 'docsight-shell-' + CACHE_VERSION;
var STATIC_CACHE = 'docsight-static-' + CACHE_VERSION;
var OFFLINE_SHELL_HEADERS = {
  'X-DOCSight-Offline-Shell': 'true'
};

var SHELL_URLS = [
  '/',
  '/?source=pwa'
];

var STATIC_URLS = [
  '/static/css/fonts.css',
  '/static/css/tokens.css',
  '/static/css/components.css',
  '/static/css/main.css',
  '/static/css/views.css',
  '/static/css/modals.css',
  '/static/css/glossary.css',
  '/static/css/segment-utilization.css',
  '/static/js/chart-engine.js',
  '/static/js/channels.js',
  '/static/js/utils.js',
  '/static/js/hero-chart.js',
  '/static/js/sparklines.js',
  '/static/js/events.js',
  '/static/js/bqm.js',
  '/static/js/speedtest.js',
  '/static/js/journal.js',
  '/static/js/correlation.js',
  '/static/js/trends.js',
  '/static/js/glossary.js',
  '/static/js/icons.js',
  '/static/js/settings.js',
  '/static/js/integrations.js',
  '/static/js/segment-utilization.js',
  '/static/vendor/lucide.min.js',
  '/static/vendor/uPlot.min.js',
  '/static/vendor/uPlot.min.css',
  '/static/fonts/outfit-latin.woff2',
  '/static/fonts/outfit-latin-ext.woff2',
  '/static/fonts/jetbrains-mono-latin.woff2',
  '/static/fonts/jetbrains-mono-latin-ext.woff2',
  '/static/logo.svg',
  '/static/icon.png',
  '/static/screenshots/dashboard-narrow.png',
  '/static/screenshots/dashboard-wide.png',
  '/static/manifest.json',
  '/modules/docsight.bnetz/static/style.css',
  '/modules/docsight.bqm/static/js/bqm-chart.js',
  '/modules/docsight.bqm/static/style.css',
  '/modules/docsight.comparison/static/main.js',
  '/modules/docsight.comparison/static/style.css',
  '/modules/docsight.connection_monitor/static/js/connection-monitor-card.js',
  '/modules/docsight.connection_monitor/static/js/connection-monitor-charts.js',
  '/modules/docsight.connection_monitor/static/js/connection-monitor-detail.js',
  '/modules/docsight.connection_monitor/static/style.css',
  '/modules/docsight.journal/static/style.css',
  '/modules/docsight.modulation/static/main.js',
  '/modules/docsight.modulation/static/style.css',
  '/modules/docsight.smokeping/static/main.js',
  '/modules/docsight.speedtest/static/style.css'
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
      caches.open(STATIC_CACHE).then(function(cache) { return cache.addAll(STATIC_URLS); })
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
