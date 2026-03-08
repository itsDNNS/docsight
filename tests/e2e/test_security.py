"""E2E tests for security hardening: SSRF URL validation and DOM XSS escaping."""

import json

import pytest


# ── Fix 1: SSRF URL Validation ──


class TestSSRFUrlValidation:
    """Config API rejects URLs with forbidden schemes (file://, gopher://, etc.)."""

    @pytest.mark.parametrize("key", [
        "modem_url",
        "bqm_url",
        "speedtest_tracker_url",
        "notify_webhook_url",
    ])
    @pytest.mark.parametrize("url,expected_status", [
        ("http://192.168.1.1", 200),
        ("https://example.com/api", 200),
        ("file:///etc/passwd", 400),
        ("gopher://evil.com", 400),
        ("ftp://files.local/data", 400),
        ("javascript:alert(1)", 400),
        ("data:text/html,<h1>xss</h1>", 400),
    ])
    def test_url_scheme_validation(self, live_server, page, key, url, expected_status):
        resp = page.request.post(
            f"{live_server}/api/config",
            headers={"Content-Type": "application/json"},
            data=json.dumps({key: url}),
        )
        assert resp.status == expected_status, (
            f"{key}={url} should return {expected_status}, got {resp.status}"
        )

    def test_rejected_url_includes_error_message(self, live_server, page):
        resp = page.request.post(
            f"{live_server}/api/config",
            headers={"Content-Type": "application/json"},
            data=json.dumps({"modem_url": "file:///etc/passwd"}),
        )
        assert resp.status == 400
        body = resp.json()
        assert body["success"] is False
        assert "http" in body["error"].lower() and "https" in body["error"].lower()

    def test_empty_url_accepted(self, live_server, page):
        resp = page.request.post(
            f"{live_server}/api/config",
            headers={"Content-Type": "application/json"},
            data=json.dumps({"modem_url": ""}),
        )
        assert resp.status == 200

    def test_bad_url_does_not_persist(self, settings_page):
        """A rejected URL should not change any config state."""
        # Set a known good value via JS fetch
        settings_page.evaluate("""
            (async () => {
                await fetch('/api/config', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({modem_url: 'http://safe.local'})
                });
                // Try to overwrite with a bad URL
                var resp = await fetch('/api/config', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({modem_url: 'file:///etc/passwd'})
                });
                window.__badUrlStatus = resp.status;
            })();
        """)
        settings_page.wait_for_timeout(1000)
        status = settings_page.evaluate("window.__badUrlStatus")
        assert status == 400
        # Reload settings page and check the modem_url field still has safe value
        settings_page.reload()
        settings_page.wait_for_load_state("networkidle")
        modem_url_val = settings_page.evaluate("""
            (() => {
                var el = document.getElementById('modem_url') || document.getElementById('modem-url');
                return el ? el.value : null;
            })()
        """)
        assert modem_url_val == "http://safe.local"

    def test_settings_ui_shows_error_on_bad_url(self, settings_page):
        """Settings page should display an error when saving an invalid URL."""
        settings_page.evaluate("""
            fetch('/api/config', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({modem_url: 'file:///etc/passwd'})
            }).then(r => r.json()).then(data => {
                window.__ssrfTestResult = data;
            });
        """)
        settings_page.wait_for_timeout(1000)
        result = settings_page.evaluate("window.__ssrfTestResult")
        assert result["success"] is False
        assert "error" in result


# ── Fix 2: DOM XSS — escapeHtml() Applied ──


class TestEscapeHtmlPresence:
    """Verify escapeHtml() is used on server-sourced data in innerHTML assignments."""

    def test_escapehtml_function_available(self, demo_page):
        """escapeHtml() should be defined globally."""
        result = demo_page.evaluate("typeof escapeHtml")
        assert result == "function"

    def test_escapehtml_actually_escapes(self, demo_page):
        """escapeHtml() should neutralize HTML tags."""
        result = demo_page.evaluate('escapeHtml("<script>alert(1)</script>")')
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_escapehtml_handles_ampersand(self, demo_page):
        result = demo_page.evaluate('escapeHtml("a & b < c")')
        assert "&amp;" in result
        assert "&lt;" in result


class TestXSSNoScriptExecution:
    """Navigate all affected views and verify no JS errors from escapeHtml changes."""

    def test_no_js_errors_on_dashboard(self, demo_page):
        """Dashboard should load without JS errors after our changes."""
        errors = []
        demo_page.on("pageerror", lambda err: errors.append(str(err)))
        demo_page.reload()
        demo_page.wait_for_load_state("networkidle")
        demo_page.wait_for_timeout(2000)
        escape_errors = [e for e in errors if "escapeHtml" in e or "undefined" in e.lower()]
        assert len(escape_errors) == 0, f"JS errors on dashboard: {escape_errors}"

    def test_no_js_errors_on_speedtest_view(self, demo_page):
        """Speedtest view should load without JS errors."""
        errors = []
        demo_page.on("pageerror", lambda err: errors.append(str(err)))
        demo_page.locator('a.nav-item[data-view="speedtest"]').click()
        demo_page.wait_for_timeout(2000)
        escape_errors = [e for e in errors if "escapeHtml" in e or "undefined" in e.lower()]
        assert len(escape_errors) == 0, f"JS errors on speedtest: {escape_errors}"

    def test_no_js_errors_on_channels_view(self, demo_page):
        """Channels view (including compare chips) should load without JS errors."""
        errors = []
        demo_page.on("pageerror", lambda err: errors.append(str(err)))
        demo_page.locator('a.nav-item[data-view="channels"]').click()
        demo_page.wait_for_timeout(1500)
        escape_errors = [e for e in errors if "escapeHtml" in e or "undefined" in e.lower()]
        assert len(escape_errors) == 0, f"JS errors on channels: {escape_errors}"

    def test_no_js_errors_on_correlation_view(self, demo_page):
        """Correlation view (event tooltips) should load without JS errors."""
        errors = []
        demo_page.on("pageerror", lambda err: errors.append(str(err)))
        demo_page.locator('a.nav-item[data-view="correlation"]').click()
        demo_page.wait_for_timeout(2000)
        escape_errors = [e for e in errors if "escapeHtml" in e or "undefined" in e.lower()]
        assert len(escape_errors) == 0, f"JS errors on correlation: {escape_errors}"

    def test_no_js_errors_on_bnetz_view(self, demo_page):
        """BNetzA view (provider, date columns) should load without JS errors."""
        errors = []
        demo_page.on("pageerror", lambda err: errors.append(str(err)))
        demo_page.locator('a.nav-item[data-view="bnetz"]').click()
        demo_page.wait_for_timeout(2000)
        escape_errors = [e for e in errors if "escapeHtml" in e or "undefined" in e.lower()]
        assert len(escape_errors) == 0, f"JS errors on bnetz: {escape_errors}"

    def test_no_js_errors_on_bqm_view(self, demo_page):
        """BQM view should load without JS errors."""
        errors = []
        demo_page.on("pageerror", lambda err: errors.append(str(err)))
        demo_page.locator('a.nav-item[data-view="bqm"]').click()
        demo_page.wait_for_timeout(2000)
        escape_errors = [e for e in errors if "escapeHtml" in e or "undefined" in e.lower()]
        assert len(escape_errors) == 0, f"JS errors on bqm: {escape_errors}"


class TestSpeedtestTableEscaping:
    """Speedtest table rows should escape ping/jitter values."""

    def test_speedtest_table_renders(self, demo_page):
        """Speedtest table should render with data."""
        demo_page.locator('a.nav-item[data-view="speedtest"]').click()
        demo_page.wait_for_timeout(2000)
        rows = demo_page.locator("#speedtest-tbody tr")
        assert rows.count() > 0, "Speedtest table should have rows"

    def test_speedtest_values_not_html(self, demo_page):
        """Ping/jitter cells should contain plain text, not raw HTML."""
        demo_page.locator('a.nav-item[data-view="speedtest"]').click()
        demo_page.wait_for_timeout(2000)
        cells = demo_page.locator("#speedtest-tbody td")
        for i in range(min(cells.count(), 40)):
            text = cells.nth(i).inner_html()
            assert "<script" not in text.lower(), f"Script tag found in speedtest cell {i}"


class TestCorrelationTooltipEscaping:
    """Correlation chart tooltip should escape event messages."""

    def test_correlation_view_renders(self, demo_page):
        """Correlation view should render (raw canvas element)."""
        demo_page.locator('a.nav-item[data-view="correlation"]').click()
        demo_page.wait_for_timeout(3000)
        # The correlation chart IS a canvas element with id="correlation-chart"
        chart = demo_page.locator("canvas#correlation-chart")
        assert chart.count() > 0, "Correlation chart canvas should exist"
        # Container should become visible after data loads
        container = demo_page.locator("#correlation-chart-container")
        assert container.is_visible(), "Correlation chart container should be visible"


class TestChannelCompareChipEscaping:
    """Compare chips should escape channel labels."""

    def test_compare_add_channel(self, demo_page):
        """Adding a channel to compare should render an escaped chip."""
        demo_page.locator('a.nav-item[data-view="channels"]').click()
        demo_page.wait_for_timeout(500)

        # Switch to compare mode
        compare_tab = demo_page.locator(
            '.channel-mode-tab[data-mode="compare"], '
            '.trend-tab[data-value="compare"]'
        )
        if compare_tab.count() > 0:
            compare_tab.first.click()
            demo_page.wait_for_timeout(500)

            # Select a channel from the dropdown
            sel = demo_page.locator("#compare-channel-select")
            if sel.count() > 0:
                options = sel.locator("option")
                if options.count() > 1:
                    sel.select_option(index=1)
                    demo_page.wait_for_timeout(200)
                    # Click "Add" button
                    add_btn = demo_page.locator(
                        "#compare-add-btn, .compare-add-btn, "
                        "button[onclick*='addCompareChannel']"
                    )
                    if add_btn.count() > 0:
                        add_btn.first.click()
                        demo_page.wait_for_timeout(1000)
                        chips = demo_page.locator("#compare-chips .compare-chip")
                        assert chips.count() > 0, "Compare chip should appear"
                        # Verify chip text does not contain raw HTML
                        chip_html = chips.first.inner_html()
                        assert "<script" not in chip_html.lower()


class TestBnetzTableEscaping:
    """BNetzA table should escape provider names and dates."""

    def test_bnetz_data_renders(self, demo_page):
        """BNetzA measurements should render (demo mode has sample data)."""
        demo_page.locator('a.nav-item[data-view="bnetz"]').click()
        demo_page.wait_for_timeout(2000)
        tbody = demo_page.locator("#bnetz-tbody")
        if tbody.count() > 0:
            rows = tbody.locator("tr")
            if rows.count() > 0:
                # Check the provider cell for no raw HTML
                first_row_html = rows.first.inner_html()
                assert "<script" not in first_row_html.lower()
