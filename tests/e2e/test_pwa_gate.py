"""PWA installability and offline behavior gate."""

from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError, expect

from app.web import APP_VERSION


def _open_authenticated_pwa(page, servers):
    app_url = servers["app_url"]
    page.goto(f"{app_url}/login", wait_until="domcontentloaded")
    if urlsplit(page.url).path.endswith("/login"):
        page.fill('input[name="password"]', servers["password"])
        page.click('button[type="submit"]')
        page.wait_for_load_state("networkidle")
    page.goto(f"{app_url}/?enable-sw-test=1")
    page.wait_for_load_state("networkidle")
    return app_url


def _chromium_app_id(page):
    session = page.context.new_cdp_session(page)
    try:
        return session.send("Page.getAppId").get("appId")
    except PlaywrightError as exc:
        message = str(exc).lower()
        if "page.getappid" in message and (
            "wasn't found" in message
            or "method not found" in message
            or "-32601" in message
        ):
            return None
        raise
    finally:
        session.detach()


def test_manifest_and_service_worker_resolve_to_each_mount(page, path_prefix_servers):
    """Manifest members and registration scope stay inside root and prefixed mounts."""
    requests = []
    page.on("request", lambda request: requests.append(request.url))
    app_url = _open_authenticated_pwa(page, path_prefix_servers)

    manifest = page.evaluate(
        """
        async () => {
            const manifestUrl = document.querySelector('link[rel="manifest"]').href;
            const res = await fetch(manifestUrl);
            const data = await res.json();
            const resolve = value => new URL(value, manifestUrl).href;
            const startUrl = resolve(data.start_url);
            const startUrlOrigin = new URL(startUrl).origin + '/';
            return {
                display: data.display,
                id: new URL(data.id, startUrlOrigin).href,
                rawId: data.id,
                startUrl,
                scope: resolve(data.scope),
                icons: data.icons.map(icon => resolve(icon.src)),
                shortcuts: data.shortcuts.map(shortcut => resolve(shortcut.url)),
                screenshots: data.screenshots.map(screenshot => resolve(screenshot.src))
            };
        }
        """
    )
    mounted_root = f"{app_url}/"
    assert manifest["id"] == mounted_root
    assert manifest["rawId"] == urlsplit(mounted_root).path
    assert manifest["display"] == "standalone"
    assert manifest["scope"] == mounted_root
    assert manifest["startUrl"] == f"{mounted_root}?source=pwa"
    assert set(manifest["icons"]) == {
        f"{mounted_root}static/icon.png",
        f"{mounted_root}static/logo.svg",
    }
    assert all(url.startswith(mounted_root) for url in manifest["shortcuts"])
    assert all(url.startswith(mounted_root) for url in manifest["screenshots"])

    chromium_app_id = _chromium_app_id(page)
    if chromium_app_id is not None:
        assert chromium_app_id == mounted_root

    sw_registration = page.evaluate(
        """
        async () => {
            if (!('serviceWorker' in navigator)) return null;
            const registration = await navigator.serviceWorker.ready;
            return registration && registration.active ? {
                scriptUrl: registration.active.scriptURL,
                scope: registration.scope
            } : null;
        }
        """
    )
    assert sw_registration == {
        "scriptUrl": f"{mounted_root}sw.js",
        "scope": mounted_root,
    }

    origin = f"{urlsplit(app_url).scheme}://{urlsplit(app_url).netloc}"
    mount_path = path_prefix_servers["mount_path"]
    same_origin_paths = [
        urlsplit(url).path for url in requests if url.startswith(f"{origin}/")
    ]
    assert f"{mount_path}/static/manifest.json" in same_origin_paths
    if mount_path:
        assert all(
            path == mount_path or path.startswith(f"{mount_path}/")
            for path in same_origin_paths
        )


def test_static_js_and_css_requests_include_app_version(page, live_server):
    """Rendered shell should version cache-first JS/CSS requests with the app version."""
    page.goto(f"{live_server}/")
    page.wait_for_load_state("networkidle")

    offenders = page.evaluate(
        r"""
        (expectedVersion) => Array.from(document.querySelectorAll('script[src], link[rel="stylesheet"][href]'))
            .map((el) => el.getAttribute('src') || el.getAttribute('href'))
            .filter(Boolean)
            .filter((raw) => {
                const url = new URL(raw, window.location.origin);
                return url.origin === window.location.origin
                    && (url.pathname.startsWith('/static/') || url.pathname.startsWith('/modules/'))
                    && /\.(js|css)$/.test(url.pathname)
                    && url.searchParams.get('v') !== expectedVersion;
            })
        """,
        APP_VERSION,
    )

    assert offenders == []


def test_offline_cached_shell_is_explicitly_read_only(
    page, context, path_prefix_servers
):
    """Offline reload should show cached shell state without pretending live data is current."""
    _open_authenticated_pwa(page, path_prefix_servers)
    page.evaluate("() => navigator.serviceWorker.ready")

    context.set_offline(True)
    try:
        page.reload(wait_until="domcontentloaded")
        banner = page.locator("#offline-status-banner")
        expect(banner).to_be_visible()
        expect(banner).to_contain_text("Offline")
        expect(banner).to_contain_text("read-only")
        expect(banner).to_contain_text("last-known")
        assert page.locator("#refresh-btn").is_disabled()
    finally:
        context.set_offline(False)
