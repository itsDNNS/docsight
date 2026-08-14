var CACHE_VERSION = 'v82';
var REGISTRATION_SCOPE = new URL(self.registration.scope);

if (REGISTRATION_SCOPE.origin !== self.location.origin || REGISTRATION_SCOPE.pathname.slice(-1) !== '/') {
  throw new Error('DOCSight service worker requires a same-origin directory scope');
}

var MOUNT_PATH = REGISTRATION_SCOPE.pathname === '/'
  ? ''
  : REGISTRATION_SCOPE.pathname.slice(0, -1);
var MOUNT_ROOT = MOUNT_PATH + '/';
var CACHE_NAMESPACE = 'docsight-' + encodeURIComponent(REGISTRATION_SCOPE.pathname) + '-';
var SHELL_CACHE = CACHE_NAMESPACE + 'shell-' + CACHE_VERSION;
var STATIC_CACHE = CACHE_NAMESPACE + 'static-' + CACHE_VERSION;
var OFFLINE_SHELL_HEADERS = {
  'X-DOCSight-Offline-Shell': 'true'
};

function mountedUrl(logicalUrl) {
  return MOUNT_PATH + logicalUrl;
}

var SHELL_URLS = [
  mountedUrl('/'),
  mountedUrl('/?source=pwa')
];

var CRITICAL_STATIC_URLS = [
  mountedUrl('/static/manifest.json'),
  mountedUrl('/static/logo.svg'),
  mountedUrl('/static/icon.png')
];

function sameOrigin(url) {
  return url.origin === self.location.origin;
}

function isWithinMount(url) {
  if (!sameOrigin(url)) return false;
  if (!MOUNT_PATH) return url.pathname.charAt(0) === '/';
  return url.pathname === MOUNT_PATH || url.pathname.indexOf(MOUNT_ROOT) === 0;
}

function logicalPathname(url) {
  if (!MOUNT_PATH) return url.pathname;
  if (url.pathname === MOUNT_PATH) return '/';
  return url.pathname.slice(MOUNT_PATH.length);
}

function isApiRequest(url) {
  var pathname = logicalPathname(url);
  return pathname === '/api' || pathname.indexOf('/api/') === 0 || pathname === '/health';
}

function isStaticRequest(url) {
  var pathname = logicalPathname(url);
  return pathname.indexOf('/static/') === 0 || pathname.indexOf('/modules/') === 0;
}

function isShellRequest(request, url) {
  return request.mode === 'navigate' ||
    (request.headers.get('accept') || '').indexOf('text/html') !== -1 ||
    logicalPathname(url) === '/';
}

function shellCacheKey(url) {
  if (logicalPathname(url) === '/') return MOUNT_ROOT;
  return url.pathname + url.search;
}

function markOfflineShell(response) {
  if (!response) return response;
  return response.text().then(function(body) {
    var marker = '<meta name="docsight-offline-shell" content="true">';
    var markedBody = body.indexOf('name="docsight-offline-shell"') === -1
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
      if (!res.ok) return res;
      return caches.open(SHELL_CACHE).then(function(cache) {
        return cache.put(key, res.clone()).then(function() {
          if (logicalPathname(url) === '/' && key !== MOUNT_ROOT) {
            return cache.put(MOUNT_ROOT, res.clone());
          }
          return undefined;
        }).then(function() { return res; });
      }).catch(function() { return res; });
    }, function() {
      return caches.open(SHELL_CACHE)
        .then(function(cache) {
          return cache.match(key).then(function(match) {
            return match || cache.match(MOUNT_ROOT);
          });
        })
        .then(markOfflineShell);
    });
}

function handleStaticRequest(request) {
  return caches.open(STATIC_CACHE).then(function(cache) {
    return cache.match(request).then(function(cached) {
      return { cache: cache, response: cached };
    }, function() {
      return { cache: null, response: null };
    });
  }, function() {
    return { cache: null, response: null };
  }).then(function(result) {
    if (result.response) return result.response;
    return fetch(request).then(function(res) {
      if (!res.ok || !result.cache) return res;
      return result.cache.put(request.url, res.clone()).then(
        function() { return res; },
        function() { return res; }
      );
    });
  });
}

self.addEventListener('install', function(event) {
  event.waitUntil(
    Promise.all([
      caches.open(SHELL_CACHE).then(function(cache) { return cache.addAll(SHELL_URLS); }),
      caches.open(STATIC_CACHE).then(function(cache) { return cache.addAll(CRITICAL_STATIC_URLS); })
    ])
  );
  self.skipWaiting();
});

self.addEventListener('activate', function(event) {
  var expectedCaches = [SHELL_CACHE, STATIC_CACHE];
  event.waitUntil(
    Promise.all([
      caches.keys().then(function(keys) {
        return Promise.all(keys.filter(function(key) {
          return key.indexOf(CACHE_NAMESPACE) === 0 && expectedCaches.indexOf(key) === -1;
        }).map(function(key) { return caches.delete(key); }));
      }),
      self.clients.claim()
    ])
  );
});

self.addEventListener('fetch', function(event) {
  var request = event.request;
  if (request.method !== 'GET') return;

  var url = new URL(request.url);
  if (!isWithinMount(url)) return;

  if (isApiRequest(url)) {
    event.respondWith(handleApiRequest(request));
    return;
  }

  if (isStaticRequest(url)) {
    event.respondWith(handleStaticRequest(request));
    return;
  }

  if (isShellRequest(request, url)) {
    event.respondWith(handleShellRequest(request, url));
  }
});

function hasControlCharacter(value) {
  for (var i = 0; i < value.length; i += 1) {
    var code = value.charCodeAt(i);
    if (code < 32 || code === 127) return true;
  }
  return false;
}

function hasValidPercentEscapes(value) {
  for (var i = 0; i < value.length; i += 1) {
    if (value.charAt(i) !== '%') continue;
    if (i + 2 >= value.length || !/^[0-9A-Fa-f]{2}$/.test(value.slice(i + 1, i + 3))) return false;
    i += 2;
  }
  return true;
}

function hasDotSegment(pathname) {
  var segments = pathname.split('/');
  for (var i = 0; i < segments.length; i += 1) {
    if (segments[i] === '.' || segments[i] === '..') return true;
  }
  return false;
}

function hasSafeEncodedPath(pathname) {
  var candidate = pathname;
  for (var depth = 0; depth < 16; depth += 1) {
    if (hasDotSegment(candidate)) return false;
    var next = '';
    var decodedPercent = false;
    for (var i = 0; i < candidate.length; i += 1) {
      if (candidate.charAt(i) !== '%') {
        next += candidate.charAt(i);
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

function validatedNotificationTarget(targetUrl) {
  if (typeof targetUrl !== 'string' || !targetUrl || targetUrl.length > 4096) return null;
  if (hasControlCharacter(targetUrl) || targetUrl.indexOf('\\') !== -1 || !hasValidPercentEscapes(targetUrl)) return null;
  if (targetUrl.indexOf('//') === 0) return null;

  var isAbsolute = targetUrl.charAt(0) !== '/';
  var rawInternal = targetUrl;
  var parsed;
  if (isAbsolute) {
    var absoluteMatch = targetUrl.match(/^[A-Za-z][A-Za-z0-9+.-]*:\/\/[^/?#]*/);
    if (!absoluteMatch) return null;
    try {
      parsed = new URL(targetUrl);
    } catch (error) {
      return null;
    }
    if (parsed.origin !== self.location.origin) return null;
    rawInternal = targetUrl.slice(absoluteMatch[0].length) || '/';
    if (rawInternal.charAt(0) !== '/') rawInternal = '/' + rawInternal;
  } else if (targetUrl.charAt(1) === '/') {
    return null;
  }

  var queryIndex = rawInternal.indexOf('?');
  var fragmentIndex = rawInternal.indexOf('#');
  var boundary = rawInternal.length;
  if (queryIndex !== -1 && queryIndex < boundary) boundary = queryIndex;
  if (fragmentIndex !== -1 && fragmentIndex < boundary) boundary = fragmentIndex;
  var rawPathname = rawInternal.slice(0, boundary);
  if (!rawPathname || rawPathname.charAt(0) !== '/' || !hasSafeEncodedPath(rawPathname)) return null;

  try {
    parsed = new URL(rawInternal, self.location.origin);
  } catch (error) {
    return null;
  }
  if (parsed.origin !== self.location.origin) return null;

  var mounted = !MOUNT_PATH || parsed.pathname === MOUNT_PATH || parsed.pathname.indexOf(MOUNT_ROOT) === 0;
  if (mounted) return parsed.pathname + parsed.search + parsed.hash;
  if (isAbsolute) return null;
  return MOUNT_PATH + parsed.pathname + parsed.search + parsed.hash;
}

function fallbackNotificationUrl() {
  return mountedUrl('/?source=pwa#events');
}

function safeNotificationUrl(targetUrl) {
  return validatedNotificationTarget(targetUrl) || fallbackNotificationUrl();
}

self.addEventListener('push', function(event) {
  var fallback = {
    title: 'DOCSight notification',
    body: 'Open DOCSight for the latest signal status.',
    url: fallbackNotificationUrl(),
    severity: 'info'
  };
  var payload = fallback;
  try {
    if (event.data) payload = Object.assign({}, fallback, event.data.json());
  } catch (error) {
    try {
      payload = Object.assign({}, fallback, { body: event.data ? event.data.text() : fallback.body });
    } catch (ignore) {
      payload = fallback;
    }
  }
  event.waitUntil(self.registration.showNotification(payload.title || fallback.title, {
    body: payload.body || fallback.body,
    icon: mountedUrl('/static/icon.png'),
    badge: mountedUrl('/static/icon.png'),
    tag: 'docsight-' + (payload.event_type || payload.severity || 'notification'),
    data: { url: safeNotificationUrl(payload.url || fallback.url) }
  }));
});

function isMountedClient(client) {
  try {
    return isWithinMount(new URL(client.url));
  } catch (error) {
    return false;
  }
}

self.addEventListener('notificationclick', function(event) {
  event.notification.close();
  var targetUrl = safeNotificationUrl(
    event.notification.data && event.notification.data.url
  );
  event.waitUntil(clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function(clientList) {
    for (var i = 0; i < clientList.length; i += 1) {
      var client = clientList[i];
      if (isMountedClient(client) && 'focus' in client) {
        return client.focus().then(function(focusedClient) {
          if (isMountedClient(focusedClient) && 'navigate' in focusedClient) {
            return focusedClient.navigate(targetUrl);
          }
          return focusedClient;
        });
      }
    }
    if (clients.openWindow) return clients.openWindow(targetUrl);
    return undefined;
  }));
});
