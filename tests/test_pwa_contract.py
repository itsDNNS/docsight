"""Behavioral regression checks for DOCSight PWA mount and offline contracts."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from urllib.parse import urljoin

import pytest


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "app" / "static" / "manifest.json"
SERVICE_WORKER = ROOT / "app" / "static" / "sw.js"
INDEX_TEMPLATE = ROOT / "app" / "templates" / "index.html"
DASHBOARD_SCRIPT = ROOT / "app" / "static" / "js" / "dashboard.js"
SERVICE_WORKER_REGISTRATION_SCRIPT = ROOT / "app" / "static" / "js" / "service-worker-registration.js"
BROWSER_CONTRACTS_SCRIPT = ROOT / "app" / "static" / "js" / "browser-contracts.js"


SW_NODE_HARNESS = r"""
const fs = require('fs');
const vm = require('vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const listeners = {};
const operations = {added: [], deleted: [], opened: [], puts: [], notifications: [], focused: [], navigated: [], openedWindows: []};
let fetchCount = 0;
let runtimeStarted = false;

function cacheFor(name) {
  return {
    addAll: async function(urls) { operations.added.push({cache: name, urls: urls.slice()}); },
    match: async function(key) {
      if (input.cachedShell && name === context.SHELL_CACHE && key === context.MOUNT_ROOT) {
        return new Response('<html><head></head><body>Cached DOCSight</body></html>', {
          status: 200,
          headers: {'Content-Type': 'text/html'}
        });
      }
      return null;
    },
    put: async function(key) {
      operations.puts.push({cache: name, key: typeof key === 'string' ? key : key.url});
      if (runtimeStarted && input.failCachePut) throw new Error('cache put failed');
    }
  };
}

const clientObjects = (input.clients || []).map(function(url) {
  return {
    url: url,
    focus: async function() { operations.focused.push(url); return this; },
    navigate: async function(target) { operations.navigated.push(target); return this; }
  };
});
const clients = {
  claim: async function() {},
  matchAll: async function() { return clientObjects; },
  openWindow: async function(target) { operations.openedWindows.push(target); return target; }
};
const origin = new URL(input.scope).origin;
const context = {
  URL: URL,
  Headers: Headers,
  Response: Response,
  Promise: Promise,
  Object: Object,
  encodeURIComponent: encodeURIComponent,
  parseInt: parseInt,
  clients: clients,
  caches: {
    open: async function(name) {
      operations.opened.push(name);
      if (runtimeStarted && input.failCacheOpen) throw new Error('cache open failed');
      return cacheFor(name);
    },
    keys: async function() { return input.cacheKeys || []; },
    delete: async function(name) { operations.deleted.push(name); return true; }
  },
  fetch: async function() {
    fetchCount += 1;
    if (input.failFetch) throw new Error('offline');
    return new Response('<html><head></head><body>DOCSight</body></html>', {
      status: 200,
      headers: {'Content-Type': 'text/html'}
    });
  }
};
context.self = {
  location: {origin: origin},
  registration: {
    scope: input.scope,
    showNotification: async function(title, options) {
      operations.notifications.push({title: title, options: options});
    }
  },
  clients: clients,
  addEventListener: function(name, handler) { listeners[name] = handler; },
  skipWaiting: function() {}
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);

async function waitedEvent(extra) {
  let promise = Promise.resolve();
  const event = Object.assign({}, extra || {}, {
    waitUntil: function(value) { promise = Promise.resolve(value); }
  });
  return {event: event, wait: async function() { await promise; }};
}

async function probeFetch(probe) {
  const beforeFetch = fetchCount;
  const beforeOpened = operations.opened.length;
  let responsePromise = null;
  const event = {
    request: {
      method: probe.method,
      url: probe.url,
      mode: probe.mode || 'cors',
      headers: {get: function(name) { return name.toLowerCase() === 'accept' ? (probe.accept || '') : null; }}
    },
    respondWith: function(value) { responsePromise = Promise.resolve(value); }
  };
  listeners.fetch(event);
  let response = null;
  if (responsePromise) response = await responsePromise;
  const result = {
    responded: responsePromise !== null,
    fetches: fetchCount - beforeFetch,
    openedCaches: operations.opened.slice(beforeOpened)
  };
  if (input.inspectResponses) {
    result.status = response ? response.status : null;
    result.offlineHeader = response ? response.headers.get('X-DOCSight-Offline-Shell') : null;
    result.offlineMarked = response ? (await response.text()).includes('name="docsight-offline-shell"') : false;
  }
  return result;
}

(async function() {
  const install = await waitedEvent();
  listeners.install(install.event);
  await install.wait();

  const activate = await waitedEvent();
  listeners.activate(activate.event);
  await activate.wait();
  runtimeStarted = true;

  const fetches = [];
  for (const probe of (input.fetches || [])) fetches.push(await probeFetch(probe));

  for (const payload of (input.pushPayloads || [])) {
    const push = await waitedEvent({data: {json: function() { return payload; }, text: function() { return ''; }}});
    listeners.push(push.event);
    await push.wait();
  }

  for (const target of (input.clickTargets || [])) {
    const click = await waitedEvent({
      notification: {data: {url: target}, close: function() {}}
    });
    listeners.notificationclick(click.event);
    await click.wait();
  }

  process.stdout.write(JSON.stringify({
    mountPath: context.MOUNT_PATH,
    mountRoot: context.MOUNT_ROOT,
    cacheNamespace: context.CACHE_NAMESPACE,
    shellCache: context.SHELL_CACHE,
    staticCache: context.STATIC_CACHE,
    shellUrls: Array.from(context.SHELL_URLS),
    criticalStaticUrls: Array.from(context.CRITICAL_STATIC_URLS),
    safeTargets: (input.safeTargets || []).map(function(value) { return context.safeNotificationUrl(value); }),
    fetches: fetches,
    operations: operations
  }));
})().catch(function(error) {
  process.stderr.write(error.stack || String(error));
  process.exit(1);
});
"""


def _run_service_worker(scope: str, **inputs: object) -> dict[str, object]:
    completed = subprocess.run(
        ["node", "-e", SW_NODE_HARNESS, str(SERVICE_WORKER)],
        input=json.dumps({"scope": scope, **inputs}),
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(completed.stdout)


@pytest.mark.parametrize(
    ("manifest_url", "app_root"),
    [
        ("https://example.test/static/manifest.json", "https://example.test/"),
        (
            "https://example.test/docsight/static/manifest.json",
            "https://example.test/docsight/",
        ),
    ],
)
def test_base_manifest_urls_resolve_to_the_active_mount(manifest_url, app_root):
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert "id" not in manifest
    assert manifest["lang"] == "en"
    assert manifest["display"] == "standalone"
    assert "network-monitoring" in manifest["categories"]
    assert urljoin(manifest_url, manifest["scope"]) == app_root
    assert urljoin(manifest_url, manifest["start_url"]) == f"{app_root}?source=pwa"
    assert {urljoin(manifest_url, item["src"]) for item in manifest["icons"]} == {
        f"{app_root}static/icon.png",
        f"{app_root}static/logo.svg",
    }
    assert {urljoin(manifest_url, item["url"]) for item in manifest["shortcuts"]} >= {
        f"{app_root}?source=pwa#live",
        f"{app_root}?source=pwa#events",
        f"{app_root}?source=pwa#channels",
    }
    assert {
        urljoin(manifest_url, icon["src"])
        for shortcut in manifest["shortcuts"]
        for icon in shortcut["icons"]
    } == {f"{app_root}static/icon.png"}
    assert {urljoin(manifest_url, shot["src"]) for shot in manifest["screenshots"]} == {
        f"{app_root}static/screenshots/dashboard-narrow.png",
        f"{app_root}static/screenshots/dashboard-wide.png",
    }


@pytest.mark.parametrize(
    ("scope", "mount", "shell_urls", "critical_urls"),
    [
        (
            "https://example.test/",
            "",
            ["/", "/?source=pwa"],
            ["/static/manifest.json", "/static/logo.svg", "/static/icon.png"],
        ),
        (
            "https://example.test/docsight/",
            "/docsight",
            ["/docsight/", "/docsight/?source=pwa"],
            [
                "/docsight/static/manifest.json",
                "/docsight/static/logo.svg",
                "/docsight/static/icon.png",
            ],
        ),
    ],
)
def test_service_worker_derives_mounted_install_urls_from_registration_scope(
    scope, mount, shell_urls, critical_urls
):
    result = _run_service_worker(scope)

    assert result["mountPath"] == mount
    assert result["mountRoot"] == f"{mount}/"
    assert result["shellUrls"] == shell_urls
    assert result["criticalStaticUrls"] == critical_urls
    assert result["operations"]["added"] == [
        {"cache": result["shellCache"], "urls": shell_urls},
        {"cache": result["staticCache"], "urls": critical_urls},
    ]


@pytest.mark.parametrize(
    ("scope", "mount"),
    [
        ("https://example.test/", ""),
        ("https://example.test/docsight/", "/docsight"),
    ],
)
def test_service_worker_classifies_requests_identically_at_root_and_prefix(
    scope, mount
):
    origin = "https://example.test"
    probes = [
        {"method": "GET", "url": f"{origin}{mount}/api/poll"},
        {"method": "GET", "url": f"{origin}{mount}/health"},
        {"method": "GET", "url": f"{origin}{mount}/static/app.js"},
        {"method": "GET", "url": f"{origin}{mount}/modules/example/main.js"},
        {"method": "GET", "url": f"{origin}{mount}/deep-link", "mode": "navigate"},
        {"method": "GET", "url": "https://outside.test/docsight/", "mode": "navigate"},
        {"method": "POST", "url": f"{origin}{mount}/api/poll"},
        {"method": "DELETE", "url": f"{origin}{mount}/static/app.js"},
    ]
    if mount:
        probes.insert(
            5,
            {"method": "GET", "url": f"{origin}/outside", "mode": "navigate"},
        )

    result = _run_service_worker(scope, fetches=probes)

    expected = [
        {"responded": True, "fetches": 1, "openedCaches": []},
        {"responded": True, "fetches": 1, "openedCaches": []},
        {"responded": True, "fetches": 1, "openedCaches": [result["staticCache"]]},
        {"responded": True, "fetches": 1, "openedCaches": [result["staticCache"]]},
        {"responded": True, "fetches": 1, "openedCaches": [result["shellCache"]]},
        {"responded": False, "fetches": 0, "openedCaches": []},
        {"responded": False, "fetches": 0, "openedCaches": []},
        {"responded": False, "fetches": 0, "openedCaches": []},
    ]
    if mount:
        expected.insert(5, {"responded": False, "fetches": 0, "openedCaches": []})
    assert result["fetches"] == expected


def test_cache_names_and_activation_cleanup_are_mount_isolated():
    root = _run_service_worker("https://example.test/")
    prefixed = _run_service_worker("https://example.test/docsight/")
    keys = [
        prefixed["shellCache"],
        prefixed["cacheNamespace"] + "shell-v1",
        root["cacheNamespace"] + "shell-v1",
        "another-app-cache-v1",
    ]

    activated = _run_service_worker(
        "https://example.test/docsight/",
        cacheKeys=keys,
    )

    assert root["cacheNamespace"] != prefixed["cacheNamespace"]
    assert activated["operations"]["deleted"] == [
        prefixed["cacheNamespace"] + "shell-v1"
    ]


def test_offline_shell_uses_the_mounted_fallback_and_explicit_marker():
    result = _run_service_worker(
        "https://example.test/docsight/",
        failFetch=True,
        cachedShell=True,
        inspectResponses=True,
        fetches=[
            {
                "method": "GET",
                "url": "https://example.test/docsight/?source=pwa",
                "mode": "navigate",
            }
        ],
    )

    assert result["fetches"] == [
        {
            "responded": True,
            "fetches": 1,
            "openedCaches": [result["shellCache"]],
            "status": 200,
            "offlineHeader": "true",
            "offlineMarked": True,
        }
    ]


@pytest.mark.parametrize("failure", ["open", "put"])
@pytest.mark.parametrize(
    "probe",
    [
        {
            "method": "GET",
            "url": "https://example.test/docsight/dashboard",
            "mode": "navigate",
        },
        {
            "method": "GET",
            "url": "https://example.test/docsight/static/app.js",
        },
    ],
    ids=["shell", "static"],
)
def test_successful_runtime_fetch_survives_cache_failures(probe, failure):
    result = _run_service_worker(
        "https://example.test/docsight/",
        failCacheOpen=failure == "open",
        failCachePut=failure == "put",
        inspectResponses=True,
        fetches=[probe],
    )

    assert result["fetches"] == [
        {
            "responded": True,
            "fetches": 1,
            "openedCaches": [
                result["shellCache"]
                if probe.get("mode") == "navigate"
                else result["staticCache"]
            ],
            "status": 200,
            "offlineHeader": None,
            "offlineMarked": False,
        }
    ]


def test_notification_targets_are_mounted_once_and_unsafe_targets_fall_back():
    fallback = "/docsight/?source=pwa#events"
    targets = [
        "/?source=pwa#events",
        "/settings#notifications",
        "/docsight/settings#notifications",
        "https://example.test/docsight/events?id=1#details",
        "https://evil.test/docsight/events",
        "//evil.test/docsight/events",
        "https://example.test/admin",
        "https://example.test/docsight-other/events",
        "/docsight/../admin",
        "/docsight/%2e%2e/admin",
        "/docsight/%252e%252e/admin",
        "/docsight/%GG",
        "/docsight\\admin",
        "/docsight/\u0000admin",
    ]
    result = _run_service_worker(
        "https://example.test/docsight/",
        safeTargets=targets,
    )

    assert result["safeTargets"] == [
        fallback,
        "/docsight/settings#notifications",
        "/docsight/settings#notifications",
        "/docsight/events?id=1#details",
        fallback,
        fallback,
        fallback,
        fallback,
        fallback,
        fallback,
        fallback,
        fallback,
        fallback,
        fallback,
    ]


def test_push_assets_and_notification_click_clients_stay_inside_mount():
    fallback = "/docsight/?source=pwa#events"
    result = _run_service_worker(
        "https://example.test/docsight/",
        clients=[
            "https://example.test/outside",
            "https://example.test/docsight/dashboard",
        ],
        pushPayloads=[{"title": "Signal", "url": "https://evil.test/escape"}],
        clickTargets=["https://example.test/admin"],
    )

    assert result["operations"]["notifications"] == [
        {
            "title": "Signal",
            "options": {
                "body": "Open DOCSight for the latest signal status.",
                "icon": "/docsight/static/icon.png",
                "badge": "/docsight/static/icon.png",
                "tag": "docsight-info",
                "data": {"url": fallback},
            },
        }
    ]
    assert result["operations"]["focused"] == [
        "https://example.test/docsight/dashboard"
    ]
    assert result["operations"]["navigated"] == [fallback]
    assert result["operations"]["openedWindows"] == []


def test_root_push_urls_remain_root_relative():
    result = _run_service_worker(
        "https://example.test/",
        safeTargets=["/?source=pwa#events", "https://example.test/settings"],
        pushPayloads=[{}],
    )

    assert result["safeTargets"] == ["/?source=pwa#events", "/settings"]
    options = result["operations"]["notifications"][0]["options"]
    assert options["icon"] == "/static/icon.png"
    assert options["badge"] == "/static/icon.png"
    assert options["data"]["url"] == "/?source=pwa#events"


def test_notification_click_does_not_focus_an_out_of_mount_client():
    fallback = "/docsight/?source=pwa#events"
    result = _run_service_worker(
        "https://example.test/docsight/",
        clients=["https://example.test/outside"],
        clickTargets=["//evil.test/escape"],
    )

    assert result["operations"]["focused"] == []
    assert result["operations"]["navigated"] == []
    assert result["operations"]["openedWindows"] == [fallback]


def test_index_template_exposes_honest_offline_state_and_scoped_pwa_lifecycle():
    template = INDEX_TEMPLATE.read_text(encoding="utf-8")
    dashboard = DASHBOARD_SCRIPT.read_text(encoding="utf-8")
    registration = SERVICE_WORKER_REGISTRATION_SCRIPT.read_text(encoding="utf-8")
    contracts = BROWSER_CONTRACTS_SCRIPT.read_text(encoding="utf-8")
    service_worker = SERVICE_WORKER.read_text(encoding="utf-8")

    assert 'id="offline-status-banner"' in template
    assert "updateOfflineStatus" in dashboard
    assert "enable-sw-test" in contracts
    assert "read-only" in template.lower()
    assert "last-known" in template.lower()
    assert "__DOCSIGHT_OFFLINE_SHELL__" in dashboard
    assert 'meta[name="docsight-offline-shell"][content="true"]' in dashboard
    assert '<meta name="docsight-offline-shell" content="true">' in service_worker
    assert "<script>" not in service_worker
    assert "X-DOCSight-Offline-Shell" in dashboard
    assert "navigator.onLine && window.__DOCSIGHT_OFFLINE_SHELL__ !== true" in dashboard
    assert "registration.scope === docsightServiceWorkerScope" in registration
    assert "key.indexOf(docsightCacheNamespace) === 0" in registration
    assert "register(docsightUrl('/sw.js'), { scope: docsightUrl('/') })" in registration
