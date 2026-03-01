var CACHE_NAME = 'docsight-v2';
var SHELL_URLS = [
  '/',
  '/static/css/fonts.css',
  '/static/css/tokens.css',
  '/static/css/components.css',
  '/static/css/main.css',
  '/static/css/views.css',
  '/static/css/modals.css',
  '/static/vendor/lucide.min.js',
  '/static/vendor/chart.umd.min.js',
  '/static/vendor/chartjs-adapter-date-fns.bundle.min.js',
  '/static/fonts/outfit-latin.woff2',
  '/static/fonts/outfit-latin-ext.woff2',
  '/static/fonts/jetbrains-mono-latin.woff2',
  '/static/fonts/jetbrains-mono-latin-ext.woff2',
  '/static/logo.svg',
  '/static/icon.png'
];

self.addEventListener('install', function(e) {
  e.waitUntil(caches.open(CACHE_NAME).then(function(c) { return c.addAll(SHELL_URLS); }));
  self.skipWaiting();
});

self.addEventListener('activate', function(e) {
  e.waitUntil(
    caches.keys().then(function(keys) {
      return Promise.all(keys.filter(function(k) { return k !== CACHE_NAME; }).map(function(k) { return caches.delete(k); }));
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', function(e) {
  if (e.request.method !== 'GET') return;
  e.respondWith(
    fetch(e.request)
      .then(function(res) {
        var clone = res.clone();
        caches.open(CACHE_NAME).then(function(c) { c.put(e.request, clone); });
        return res;
      })
      .catch(function() { return caches.match(e.request); })
  );
});
