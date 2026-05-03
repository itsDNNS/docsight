"""Regression checks for DOCSight PWA install and offline contracts."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "app" / "static" / "manifest.json"
SERVICE_WORKER = ROOT / "app" / "static" / "sw.js"
INDEX_TEMPLATE = ROOT / "app" / "templates" / "index.html"
MODULES = ROOT / "app" / "modules"


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


def test_service_worker_precaches_module_static_shell_assets():
    """The first installed offline shell should include module CSS/JS referenced by the dashboard."""
    source = SERVICE_WORKER.read_text(encoding="utf-8")
    missing = []

    for module_manifest in MODULES.glob("*/manifest.json"):
        module = json.loads(module_manifest.read_text(encoding="utf-8"))
        module_id = module["id"]
        static_dir = module_manifest.parent / "static"
        if not static_dir.exists():
            continue
        for asset in sorted(static_dir.rglob("*")):
            if asset.suffix not in {".css", ".js"}:
                continue
            relative = asset.relative_to(static_dir).as_posix()
            url = f"/modules/{module_id}/static/{relative}"
            if url not in source:
                missing.append(url)

    assert missing == []


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
