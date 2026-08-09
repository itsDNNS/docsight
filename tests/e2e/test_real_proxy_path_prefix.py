"""Chromium qualification through a real prefix-stripping network proxy."""

from __future__ import annotations

from urllib.parse import urlsplit

import pytest


def _require(condition: bool, message: str) -> None:
    if not condition:
        pytest.fail(message, pytrace=False)


def _record_same_origin_requests(page, origins):
    requests = []

    def record(request):
        parsed = urlsplit(request.url)
        if f"{parsed.scheme}://{parsed.netloc}" in origins:
            requests.append(request.url)

    page.on("request", record)
    return requests


def _assert_requests_remain_mounted(requests, origins, mount_path):
    for value in requests:
        parsed = urlsplit(value)
        if f"{parsed.scheme}://{parsed.netloc}" not in origins:
            continue
        if parsed.path == mount_path or parsed.path.startswith(mount_path + "/"):
            continue
        pytest.fail(
            "a same-origin browser request escaped the configured mount",
            pytrace=False,
        )


def test_critical_browser_journeys_through_real_prefix_stripping_proxy(
    page, real_proxy_servers
):
    mount_path = real_proxy_servers["mount_path"]
    app_url = real_proxy_servers["app_url"]
    setup_url = real_proxy_servers["setup_url"]
    app_origin = f"{urlsplit(app_url).scheme}://{urlsplit(app_url).netloc}"
    setup_origin = f"{urlsplit(setup_url).scheme}://{urlsplit(setup_url).netloc}"
    origins = {app_origin, setup_origin}
    requests = _record_same_origin_requests(page, origins)
    browser_errors = []
    page.on("pageerror", lambda error: browser_errors.append(str(error)))

    page.goto(f"{setup_url}/setup", wait_until="domcontentloaded")
    setup_contract = page.evaluate(
        """
        async (mountPath) => {
            const mounted = value => {
                const path = new URL(value, window.location.href).pathname;
                return path === mountPath || path.startsWith(mountPath + '/');
            };
            const registrations = 'serviceWorker' in navigator
                ? await navigator.serviceWorker.getRegistrations()
                : [];
            const health = await fetch(docsightUrl('/health'));
            return {
                formAction: mounted(document.getElementById('setup-form').action),
                manifest: mounted(document.querySelector('link[rel="manifest"]').href),
                configTarget: mounted(docsightUrl('/api/config')),
                healthTarget: mounted(health.url) && health.ok,
                noServiceWorker: registrations.length === 0
            };
        }
        """,
        mount_path,
    )
    _require(all(setup_contract.values()), "setup mount contract failed")

    outside_setup = page.request.get(
        f"{setup_origin}/health", fail_on_status_code=False
    )
    _require(
        outside_setup.status == 404,
        "the proxy accepted a request outside its configured mount",
    )

    page.goto(f"{app_url}/login", wait_until="domcontentloaded")
    login_has_no_worker = page.evaluate(
        """
        async () => !('serviceWorker' in navigator)
            || (await navigator.serviceWorker.getRegistrations()).length === 0
        """
    )
    _require(login_has_no_worker, "login unexpectedly registered a service worker")
    page.fill('input[name="password"]', real_proxy_servers["password"])
    page.click('button[type="submit"]')
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_load_state("networkidle")
    _require(
        page.evaluate(
            "mountPath => location.pathname === mountPath || location.pathname === mountPath + '/'",
            mount_path,
        ),
        "login did not reach the mounted dashboard",
    )

    page.goto(f"{app_url}/?enable-sw-test=1", wait_until="networkidle")
    api_contract = page.evaluate(
        """
        async (mountPath) => {
            const response = await fetch(docsightUrl('/api/events?limit=1'));
            const contentType = response.headers.get('content-type') || '';
            if (!response.ok || !contentType.includes('application/json')) {
                return false;
            }
            const payload = await response.json().catch(() => null);
            const responsePath = new URL(response.url).pathname;
            return payload !== null
                && typeof payload === 'object'
                && Array.isArray(payload.events)
                && responsePath.startsWith(mountPath + '/api/');
        }
        """,
        mount_path,
    )
    _require(api_contract, "representative API request failed its mount contract")

    evidence_nav = page.locator('.nav-item[data-view="evidence"]')
    _require(evidence_nav.count() == 1, "dashboard module navigation is missing")
    evidence_nav.click()
    _require(
        page.locator("#view-evidence.active").count() == 1,
        "dashboard module navigation did not activate its view",
    )

    export_contract = page.evaluate(
        """
        async () => {
            const response = await fetch(
                docsightUrl('/api/events/export.csv?exclude_operational=true')
            );
            const body = await response.text();
            return response.ok
                && (response.headers.get('content-type') || '').startsWith('text/csv')
                && (response.headers.get('content-disposition') || '').startsWith('attachment;')
                && body.startsWith('timestamp,severity,event_type,');
        }
        """
    )
    _require(export_contract, "mounted CSV export response contract failed")

    manifest_contract = page.evaluate(
        """
        async (mountPath) => {
            const manifestUrl = document.querySelector('link[rel="manifest"]').href;
            const response = await fetch(manifestUrl);
            const manifest = await response.json().catch(() => null);
            if (!response.ok || manifest === null) return false;
            const resolve = value => new URL(value, manifestUrl);
            const rootPath = mountPath + '/';
            return response.ok
                && manifest.display === 'standalone'
                && new URL(manifest.id, window.location.origin).pathname === rootPath
                && resolve(manifest.scope).pathname === rootPath
                && resolve(manifest.start_url).pathname === rootPath
                && resolve(manifest.start_url).search === '?source=pwa';
        }
        """,
        mount_path,
    )
    _require(manifest_contract, "mounted manifest contract failed")

    worker_contract = page.evaluate(
        """
        async (mountPath) => {
            if (!('serviceWorker' in navigator)) return false;
            const registration = await navigator.serviceWorker.ready;
            return new URL(registration.scope).pathname === mountPath + '/'
                && registration.active
                && new URL(registration.active.scriptURL).pathname === mountPath + '/sw.js';
        }
        """,
        mount_path,
    )
    _require(worker_contract, "mounted service-worker scope contract failed")

    page.goto(f"{app_url}/settings", wait_until="domcontentloaded")
    module_nav = page.locator('.nav-item[data-section^="mod-"]').first
    _require(module_nav.count() == 1, "settings module navigation is missing")
    module_section = module_nav.get_attribute("data-section")
    module_nav.click()
    _require(
        page.locator(f"#panel-{module_section}.active").count() == 1,
        "settings module navigation did not activate its panel",
    )

    page.goto(f"{app_url}/", wait_until="domcontentloaded")
    page.locator('form[action$="/logout"] button[type="submit"]').click()
    page.wait_for_load_state("domcontentloaded")
    _require(
        page.evaluate(
            "mountPath => location.pathname === mountPath + '/login'",
            mount_path,
        ),
        "logout did not return to the mounted login page",
    )

    outside_app = page.request.get(
        f"{app_origin}/health", fail_on_status_code=False
    )
    _require(
        outside_app.status == 404,
        "the proxy accepted a request outside its configured mount",
    )

    _require(bool(requests), "no same-origin browser requests were observed")
    _assert_requests_remain_mounted(requests, origins, mount_path)
    _require(not browser_errors, "the browser reported a page error")
