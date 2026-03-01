var CACHE_NAME = 'docsight-v1';
var SHELL_URLS = [
  '/',
  '/static/css/tokens.css',
  '/static/css/components.css',
  '/static/css/main.css',
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
