"""PWA installability and offline behavior gate."""

from playwright.sync_api import expect


def test_manifest_loads_and_service_worker_can_be_enabled_for_e2e(page, live_server):
    """Local E2E should be able to opt into the same service worker path production uses."""
    page.goto(f"{live_server}/?enable-sw-test=1")
    page.wait_for_load_state("networkidle")

    manifest = page.evaluate(
        """
        async () => {
            const res = await fetch('/static/manifest.json');
            return await res.json();
        }
        """
    )
    assert manifest["id"] == "/"
    assert manifest["display"] == "standalone"
    assert manifest["shortcuts"]
    assert "screenshots" in manifest and manifest["screenshots"]

    sw_ready = page.evaluate(
        """
        async () => {
            if (!('serviceWorker' in navigator)) return false;
            const registration = await navigator.serviceWorker.ready;
            return Boolean(registration && registration.active && registration.scope.endsWith('/'));
        }
        """
    )
    assert sw_ready is True


def test_offline_cached_shell_is_explicitly_read_only(page, context, live_server):
    """Offline reload should show cached shell state without pretending live data is current."""
    page.goto(f"{live_server}/?enable-sw-test=1")
    page.wait_for_load_state("networkidle")
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
