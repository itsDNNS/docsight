"""Regression checks for DOCSight PWA install and offline contracts."""

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "app" / "static" / "manifest.json"
SERVICE_WORKER = ROOT / "app" / "static" / "sw.js"
INDEX_TEMPLATE = ROOT / "app" / "templates" / "index.html"
MODULES = ROOT / "app" / "modules"


def _array_entries(source: str, name: str) -> set[str]:
    match = re.search(rf"var {name} = \[(.*?)\];", source, flags=re.S)
    assert match is not None
    return set(re.findall(r"'([^']+)'", match.group(1)))


def test_manifest_exposes_modern_install_metadata():
    """The web app manifest should describe a stable installed app identity."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert manifest["id"] == "/"
    assert manifest["lang"] == "en"
    assert "network-monitoring" in manifest["categories"]
    assert manifest["start_url"] == "/?source=pwa"
    assert {shortcut["url"] for shortcut in manifest["shortcuts"]} >= {
        "/?source=pwa#live",
        "/?source=pwa#events",
        "/?source=pwa#channels",
    }
    assert manifest["screenshots"], "Install surfaces need screenshot metadata"


def test_service_worker_does_not_cache_live_api_or_mutating_requests():
    """Offline support must not make stale live monitoring API responses look current."""
    source = SERVICE_WORKER.read_text(encoding="utf-8")

    assert "isApiRequest" in source
    assert "return fetch(request);" in source
    assert "request.method !== 'GET'" in source
    assert "res.ok" in source
    assert "c.put(request, clone)" not in source
    assert "c.put(e.request, clone)" not in source


def test_service_worker_has_explicit_shell_and_static_asset_strategies():
    """The service worker should separate HTML shell and immutable-ish static assets."""
    source = SERVICE_WORKER.read_text(encoding="utf-8")

    assert "STATIC_CACHE" in source
    assert "SHELL_CACHE" in source
    assert "handleShellRequest" in source
    assert "handleStaticRequest" in source
    assert "OFFLINE_SHELL_HEADERS" in source
    assert "__DOCSIGHT_OFFLINE_SHELL__" in source


def test_service_worker_handles_web_push_and_notification_clicks():
    """Installed DOCSight PWAs should display push payloads and deep-link clicks."""
    source = SERVICE_WORKER.read_text(encoding="utf-8")

    assert "addEventListener('push'" in source or 'addEventListener("push"' in source
    assert "self.registration.showNotification" in source
    assert "addEventListener('notificationclick'" in source or 'addEventListener("notificationclick"' in source
    assert "event.notification.close()" in source
    assert "clients.openWindow" in source
    assert "client.focus()" in source
    assert "safeNotificationUrl" in source
    assert "new URL(targetUrl, self.location.origin)" in source


def test_service_worker_precaches_only_shell_and_critical_static_assets():
    """Install should keep the offline shell small and cache other assets on demand."""
    source = SERVICE_WORKER.read_text(encoding="utf-8")
    shell_urls = _array_entries(source, "SHELL_URLS")
    critical_urls = _array_entries(source, "CRITICAL_STATIC_URLS")

    assert shell_urls == {"/", "/?source=pwa"}
    assert critical_urls == {
        "/static/manifest.json",
        "/static/logo.svg",
        "/static/icon.png",
    }
    assert "var STATIC_URLS =" not in source
    assert "cache.addAll(CRITICAL_STATIC_URLS)" in source
    assert "handleStaticRequest" in source
    assert "cache.put(request.url, clone)" in source
    assert all(not url.startswith("/modules/") for url in critical_urls)
    assert "/modules/docsight." not in source
    assert "/static/vendor/" not in source
    assert "/static/screenshots/" not in source


def test_service_worker_uses_runtime_cache_for_module_static_assets():
    """Module CSS/JS should be runtime cached instead of hand-listed for install."""
    source = SERVICE_WORKER.read_text(encoding="utf-8")
    assert "url.pathname.indexOf('/modules/') === 0" in source
    assert "if (isStaticRequest(url))" in source
    assert "e.respondWith(handleStaticRequest(request));" in source

    module_static_assets = []
    for module_manifest in MODULES.glob("*/manifest.json"):
        module = json.loads(module_manifest.read_text(encoding="utf-8"))
        module_id = module["id"]
        static_dir = module_manifest.parent / "static"
        if not static_dir.exists():
            continue
        for asset in sorted(static_dir.rglob("*")):
            if asset.suffix in {".css", ".js"}:
                relative = asset.relative_to(static_dir).as_posix()
                module_static_assets.append(f"/modules/{module_id}/static/{relative}")

    assert module_static_assets
    assert all(asset not in source for asset in module_static_assets)


def test_index_template_exposes_honest_offline_state_and_pwa_test_mode():
    """The UI should make offline cached shell state explicit and testable on localhost."""
    template = INDEX_TEMPLATE.read_text(encoding="utf-8")

    assert 'id="offline-status-banner"' in template
    assert "updateOfflineStatus" in template
    assert "enable-sw-test" in template
    assert "read-only" in template.lower()
    assert "last-known" in template.lower()
    assert "__DOCSIGHT_OFFLINE_SHELL__" in template
    assert "X-DOCSight-Offline-Shell" in template
    assert "navigator.onLine && window.__DOCSIGHT_OFFLINE_SHELL__ !== true" in template
