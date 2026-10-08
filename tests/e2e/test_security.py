"""E2E tests for security hardening: SSRF URL validation and DOM XSS escaping."""

import json

import pytest
from playwright.sync_api import expect
from tests.e2e.support.correlation import wait_for_correlation
from tests.e2e.support.navigation import open_view


def wait_for_view_data(page, content_id, empty_id):
    """Wait until a view shows its data or its empty state.

    Both start hidden, so this holds once the view's first load has finished.
    """
    page.wait_for_function(
        "([content, empty]) => !document.getElementById(content).hidden || !document.getElementById(empty).hidden",
        arg=[content_id, empty_id],
    )


def wait_for_channel_list(page):
    page.wait_for_function("() => document.getElementById('channel-select').options.length > 1")


# ── Fix 1: SSRF URL Validation ──


class TestSSRFUrlValidation:
    """Config API rejects URLs with forbidden schemes (file://, gopher://, etc.)."""

    @pytest.mark.parametrize("key", [
        "modem_url",
        "bqm_url",
        "speedtest_tracker_url",
        "notify_webhook_url",
        "notify_apprise_url",
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
        status = settings_page.evaluate("""
            async () => {
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
                return resp.status;
            }
        """)
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
        result = settings_page.evaluate("""
            () => fetch('/api/config', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({modem_url: 'file:///etc/passwd'})
            }).then(r => r.json())
        """)
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
        expect(demo_page.locator(".line-status-row")).to_have_count(2)
        escape_errors = [e for e in errors if "escapeHtml" in e or "undefined" in e.lower()]
        assert len(escape_errors) == 0, f"JS errors on dashboard: {escape_errors}"

    def test_no_js_errors_on_speedtest_view(self, demo_page):
        """Speedtest view should load without JS errors."""
        errors = []
        demo_page.on("pageerror", lambda err: errors.append(str(err)))
        open_view(demo_page, "speedtest")
        wait_for_view_data(demo_page, "speedtest-table", "speedtest-no-data")
        escape_errors = [e for e in errors if "escapeHtml" in e or "undefined" in e.lower()]
        assert len(escape_errors) == 0, f"JS errors on speedtest: {escape_errors}"

    def test_no_js_errors_on_channels_view(self, demo_page):
        """Channels view (including compare chips) should load without JS errors."""
        errors = []
        demo_page.on("pageerror", lambda err: errors.append(str(err)))
        open_view(demo_page, "channels")
        wait_for_channel_list(demo_page)
        escape_errors = [e for e in errors if "escapeHtml" in e or "undefined" in e.lower()]
        assert len(escape_errors) == 0, f"JS errors on channels: {escape_errors}"

    def test_no_js_errors_on_correlation_view(self, demo_page):
        """Correlation view (event tooltips) should load without JS errors."""
        errors = []
        demo_page.on("pageerror", lambda err: errors.append(str(err)))
        open_view(demo_page, "correlation")
        wait_for_correlation(demo_page)
        escape_errors = [e for e in errors if "escapeHtml" in e or "undefined" in e.lower()]
        assert len(escape_errors) == 0, f"JS errors on correlation: {escape_errors}"

    def test_no_js_errors_on_bnetz_view(self, demo_page):
        """BNetzA view (provider, date columns) should load without JS errors."""
        errors = []
        demo_page.on("pageerror", lambda err: errors.append(str(err)))
        open_view(demo_page, "bnetz")
        wait_for_view_data(demo_page, "bnetz-table-card", "bnetz-empty")
        escape_errors = [e for e in errors if "escapeHtml" in e or "undefined" in e.lower()]
        assert len(escape_errors) == 0, f"JS errors on bnetz: {escape_errors}"

    def test_no_js_errors_on_bqm_view(self, demo_page):
        """BQM view should load without JS errors."""
        errors = []
        demo_page.on("pageerror", lambda err: errors.append(str(err)))
        open_view(demo_page, "bqm")
        wait_for_view_data(demo_page, "bqm-card", "bqm-no-data")
        escape_errors = [e for e in errors if "escapeHtml" in e or "undefined" in e.lower()]
        assert len(escape_errors) == 0, f"JS errors on bqm: {escape_errors}"


class TestSpeedtestTableEscaping:
    """Speedtest table rows should escape ping/jitter values."""

    def test_speedtest_table_renders(self, demo_page):
        """Speedtest table should render with data."""
        open_view(demo_page, "speedtest")
        expect(demo_page.locator("#speedtest-tbody tr").first).to_be_visible()

    def test_speedtest_values_not_html(self, demo_page):
        """Ping/jitter cells should contain plain text, not raw HTML."""
        open_view(demo_page, "speedtest")
        expect(demo_page.locator("#speedtest-tbody tr").first).to_be_visible()
        cells = demo_page.locator("#speedtest-tbody td")
        for i in range(min(cells.count(), 40)):
            text = cells.nth(i).inner_html()
            assert "<script" not in text.lower(), f"Script tag found in speedtest cell {i}"

    def test_speedtest_signal_detail_hides_unsupported_error_counters(self, demo_page):
        """Unsupported signal counters must not be rendered as fake zeroes."""
        detail_text = demo_page.evaluate("""
            () => {
                const div = document.createElement('div');
                _renderSignalDetail({
                    found: true,
                    health: 'good',
                    ds_power_min: 1.0,
                    ds_power_avg: 1.5,
                    ds_power_max: 2.0,
                    ds_snr_min: 37.0,
                    ds_snr_avg: 38.0,
                    us_power_min: 41.0,
                    us_power_avg: 42.0,
                    us_power_max: 43.0,
                    ds_correctable_errors: null,
                    ds_uncorrectable_errors: null,
                    ds_total: 32,
                    us_total: 4,
                    snapshot_timestamp: '2026-05-01T12:00:00Z'
                }, div);
                return div.textContent;
            }
        """)

        assert "0 corr" not in detail_text
        assert "0 uncorr" not in detail_text
        assert "Errors" not in detail_text


class TestCorrelationTooltipEscaping:
    """Correlation chart tooltip should escape event messages."""

    def test_correlation_view_renders(self, demo_page):
        """Correlation view should render (raw canvas element)."""
        open_view(demo_page, "correlation")
        wait_for_correlation(demo_page)
        # The correlation chart IS a canvas element with id="correlation-chart"
        assert demo_page.locator("canvas#correlation-chart").count() > 0, "Correlation chart canvas should exist"
        expect(demo_page.locator("#correlation-chart-container")).to_be_visible()


class TestChannelCompareChipEscaping:
    """Compare chips should escape channel labels."""

    def test_compare_add_channel(self, demo_page):
        """Adding a channel to compare should render an escaped chip."""
        open_view(demo_page, "channels")
        demo_page.locator('#channel-mode-tabs .segmented-option[data-value="compare"]').click()
        demo_page.wait_for_function("() => document.getElementById('compare-channel-select').options.length > 1")
        demo_page.locator("#compare-channel-select").select_option(index=1)
        demo_page.locator("#compare-add-btn").click()
        chips = demo_page.locator("#compare-chips .compare-chip")
        expect(chips).to_have_count(1)
        # Verify chip text does not contain raw HTML
        assert "<script" not in chips.first.inner_html().lower()


class TestBnetzTableEscaping:
    """BNetzA table should escape provider names and dates."""

    def test_bnetz_data_renders(self, demo_page):
        """BNetzA measurements should render (demo mode has sample data)."""
        open_view(demo_page, "bnetz")
        first_row = demo_page.locator("#bnetz-tbody tr[data-bnetz-idx]").first
        expect(first_row).to_be_visible()
        # Check the provider cell for no raw HTML
        assert "<script" not in first_row.inner_html().lower()

    def test_bnetz_api_markup_is_rendered_only_as_text(self, demo_page):
        marker = '<img src=x onerror="window.__bnetzDomXss = true">'
        payload = [
            {
                "id": "measurement-42",
                "date": marker,
                "provider": marker,
                "source": "csv_import",
                "verdict_download": "deviation",
                "verdict_upload": "ok",
                "download_max_tariff": 100,
                "download_measured_avg": 50,
                "upload_max_tariff": 20,
                "upload_measured_avg": 20,
                "measurements": {
                    "download": [
                        {"date": marker, "time": marker, "mbps": marker}
                    ],
                    "upload": [],
                },
            }
        ]
        demo_page.route(
            "**/api/bnetz/measurements",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(payload),
            ),
        )
        demo_page.evaluate("window.__bnetzDomXss = false")

        open_view(demo_page, "bnetz")
        row = demo_page.locator("#bnetz-tbody tr[data-bnetz-idx]").first
        row.wait_for(state="visible")

        assert row.locator("td").nth(0).inner_text().strip() == marker
        assert row.locator("td").nth(1).inner_text() == marker
        row.click()
        assert demo_page.locator("#bnetz-tbody [onerror]").count() == 0
        assert demo_page.locator('a[href^="javascript:"]').count() == 0
        assert demo_page.evaluate("window.__bnetzDomXss") is False


class TestSmokepingEscaping:
    def test_target_markup_is_text_and_error_fallback_has_no_html_sink(
        self, demo_page
    ):
        target = '<img src=x onerror="window.__smokepingDomXss = true">'
        demo_page.route(
            "**/api/smokeping/targets",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps([target]),
            ),
        )
        demo_page.evaluate("window.__smokepingDomXss = false")

        open_view(demo_page, "smokeping")
        label = demo_page.locator("#smokeping-content .graph-frame-title").first
        label.wait_for(state="visible")

        assert label.inner_text() == "SmokePing \u00b7 " + target
        assert label.locator("img").count() == 0
        assert demo_page.evaluate("window.__smokepingDomXss") is False
