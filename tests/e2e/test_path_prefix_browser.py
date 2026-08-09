"""Browser smoke coverage for root and reverse-proxy path-prefix behavior."""

from __future__ import annotations

from urllib.parse import urlsplit


def _record_browser_activity(page, origins):
    requests = []
    generated_urls = []
    console_errors = []
    page_errors = []

    def record_request(request):
        if any(request.url.startswith(origin + "/") for origin in origins):
            requests.append(request.url)

    page.on("request", record_request)
    page.on(
        "console",
        lambda message: console_errors.append(message.text)
        if message.type == "error"
        else None,
    )
    page.on("pageerror", lambda error: page_errors.append(str(error)))

    def snapshot_urls():
        generated_urls.extend(
            page.eval_on_selector_all(
                "[href], [src]",
                """elements => elements.flatMap(element => ['href', 'src']
                    .filter(name => element.hasAttribute(name))
                    .map(name => ({name, value: element[name] || element.getAttribute(name)})))""",
            )
        )

    return requests, generated_urls, console_errors, page_errors, snapshot_urls


def _assert_prefix_safe(urls, origins, mount_path):
    if not mount_path:
        return
    escaped = []
    for value in urls:
        parsed = urlsplit(value)
        if f"{parsed.scheme}://{parsed.netloc}" not in origins:
            continue
        if parsed.path == mount_path or parsed.path.startswith(mount_path + "/"):
            continue
        escaped.append(value)
    assert escaped == []


def test_browser_urls_stay_within_root_or_docsight_mount(page, path_prefix_servers):
    mount_path = path_prefix_servers["mount_path"]
    app_url = path_prefix_servers["app_url"]
    setup_url = path_prefix_servers["setup_url"]
    app_origin = urlsplit(app_url)
    setup_origin = urlsplit(setup_url)
    origins = {
        f"{app_origin.scheme}://{app_origin.netloc}",
        f"{setup_origin.scheme}://{setup_origin.netloc}",
    }
    requests, generated, console_errors, page_errors, snapshot_urls = (
        _record_browser_activity(page, origins)
    )
    # The E2E server intentionally has no active poll collector. Keep the real
    # browser request (and therefore its URL) observable without turning this
    # client-URL smoke into a collector integration test.
    page.route(
        "**/api/poll",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"success":true}',
        ),
    )

    page.goto(f"{setup_url}/setup", wait_until="domcontentloaded")
    assert page.evaluate("docsightUrl('/health')") == f"{mount_path}/health"
    assert page.evaluate(
        "async () => (await fetch(docsightUrl('/health'))).status"
    ) == 200
    snapshot_urls()

    page.goto(f"{app_url}/login", wait_until="domcontentloaded")
    assert page.evaluate("docsightUrl('/login')") == f"{mount_path}/login"
    page.fill('input[name="password"]', path_prefix_servers["password"])
    page.click('button[type="submit"]')
    page.wait_for_load_state("domcontentloaded")
    assert urlsplit(page.url).path in {mount_path, f"{mount_path}/"}
    snapshot_urls()

    refresh = page.locator("#refresh-btn")
    if refresh.count():
        # The canonical refresh control is hidden at desktop width, while a
        # desktop proxy button delegates to its click handler. Dispatch the
        # same real DOM click without making this URL smoke viewport-dependent.
        page.evaluate("document.getElementById('refresh-btn').click()")
        page.wait_for_timeout(250)

    # Exercise representative built-in module scripts and their constructed URLs.
    for view in (
        "evidence",
        "connection-monitor",
        "comparison",
        "modulation",
        "smokeping",
        "events",
    ):
        button = page.locator(f'.nav-item[data-view="{view}"]')
        if button.count():
            button.first.click()
            # These views start asynchronous API work. Let each real journey
            # settle before switching views so the test does not manufacture
            # aborted fetch errors.
            page.wait_for_timeout(750)
    snapshot_urls()

    # The events CSV is a representative download href; it must remain mounted.
    export_href = page.locator("#events-export-csv").get_attribute("href")
    assert export_href is not None
    assert urlsplit(export_href).path.startswith(f"{mount_path}/api/")

    page.goto(f"{app_url}/settings", wait_until="domcontentloaded")
    page.wait_for_timeout(500)
    assert page.evaluate("docsightUrl('/api/config')") == f"{mount_path}/api/config"
    snapshot_urls()

    assert requests
    assert generated
    _assert_prefix_safe(requests, origins, mount_path)
    _assert_prefix_safe(
        [item["value"] for item in generated if item.get("value")],
        origins,
        mount_path,
    )
    assert page_errors == []
    assert console_errors == []
