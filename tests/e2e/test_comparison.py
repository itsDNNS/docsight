"""E2E tests for the Before/After Comparison feature."""

from playwright.sync_api import expect


def _comparison_payload(errors_supported, uncorr_errors):
    return {
        "period_a": {
            "from": "2026-03-01T00:00:00Z",
            "to": "2026-03-01T23:59:00Z",
            "snapshots": 1,
            "avg": {"ds_power": 3.1, "ds_snr": 34.2, "us_power": 42.1},
            "total": {
                "corr_errors": 0 if errors_supported else None,
                "uncorr_errors": uncorr_errors if errors_supported else None,
            },
            "errors_supported": errors_supported,
            "corr_errors_supported": errors_supported,
            "uncorr_errors_supported": errors_supported,
            "health_distribution": {"good": 1},
            "timeseries": [{
                "timestamp": "2026-03-01T06:00:00Z",
                "ds_power_avg": 3.1,
                "ds_snr_avg": 34.2,
                "us_power_avg": 42.1,
                "uncorr_errors": uncorr_errors if errors_supported else None,
                "health": "good",
            }],
        },
        "period_b": {
            "from": "2026-03-08T00:00:00Z",
            "to": "2026-03-08T23:59:00Z",
            "snapshots": 1,
            "avg": {"ds_power": 3.2, "ds_snr": 34.3, "us_power": 42.2},
            "total": {
                "corr_errors": 0 if errors_supported else None,
                "uncorr_errors": uncorr_errors if errors_supported else None,
            },
            "errors_supported": errors_supported,
            "corr_errors_supported": errors_supported,
            "uncorr_errors_supported": errors_supported,
            "health_distribution": {"good": 1},
            "timeseries": [{
                "timestamp": "2026-03-08T06:00:00Z",
                "ds_power_avg": 3.2,
                "ds_snr_avg": 34.3,
                "us_power_avg": 42.2,
                "uncorr_errors": uncorr_errors if errors_supported else None,
                "health": "good",
            }],
        },
        "delta": {
            "ds_power": 0.1,
            "ds_snr": 0.1,
            "us_power": 0.1,
            "uncorr_errors": 0 if errors_supported else None,
            "verdict": "unchanged",
        },
    }


def navigate_to_comparison(page):
    """Open the comparison view and wait for the control bar."""
    page.locator('.nav-item[data-view="comparison"]').click()
    expect(page.locator("#comparison-controls")).to_be_visible()


class TestComparisonView:
    def test_nav_item_visible(self, demo_page):
        nav = demo_page.locator('.nav-item[data-view="comparison"]')
        assert nav.count() == 1

    def test_run_comparison_shows_health_distribution(self, demo_page):
        navigate_to_comparison(demo_page)
        demo_page.locator("#comparison-run-btn").click()

        expect(demo_page.locator("#comparison-health")).to_be_visible()
        assert demo_page.locator("#comparison-health-bars-a .comparison-health-row").count() == 5
        assert demo_page.locator("#comparison-health-bars-b .comparison-health-row").count() == 5

    def test_hides_error_chart_when_docsis_errors_are_unsupported(self, demo_page):
        demo_page.route(
            "**/api/comparison**",
            lambda route: route.fulfill(json=_comparison_payload(False, None)),
        )
        navigate_to_comparison(demo_page)

        demo_page.locator("#comparison-run-btn").click()

        expect(demo_page.locator("#comparison-health")).to_be_visible()
        expect(demo_page.locator("#comparison-errors-card")).to_be_hidden()
        assert demo_page.locator("#cmp-chart-errors .uplot").count() == 0

    def test_hides_uncorrectable_delta_row_when_docsis_errors_are_unsupported(self, demo_page):
        demo_page.route(
            "**/api/comparison**",
            lambda route: route.fulfill(json=_comparison_payload(False, None)),
        )
        navigate_to_comparison(demo_page)

        demo_page.locator("#comparison-run-btn").click()

        expect(demo_page.locator("#comparison-delta")).to_be_visible()
        expect(demo_page.locator("#comparison-delta")).not_to_contain_text("Uncorr. Errors")

    def test_hides_uncorrectable_chart_when_only_correctable_errors_are_supported(self, demo_page):
        payload = _comparison_payload(False, None)
        for period_key in ("period_a", "period_b"):
            period = payload[period_key]
            period["errors_supported"] = True
            period["corr_errors_supported"] = True
            period["uncorr_errors_supported"] = False
            period["total"]["corr_errors"] = 5
        demo_page.route("**/api/comparison**", lambda route: route.fulfill(json=payload))
        navigate_to_comparison(demo_page)

        demo_page.locator("#comparison-run-btn").click()

        expect(demo_page.locator("#comparison-health")).to_be_visible()
        expect(demo_page.locator("#comparison-errors-card")).to_be_hidden()
        assert demo_page.locator("#cmp-chart-errors .uplot").count() == 0

    def test_keeps_zero_error_chart_when_docsis_errors_are_supported(self, demo_page):
        demo_page.route(
            "**/api/comparison**",
            lambda route: route.fulfill(json=_comparison_payload(True, 0)),
        )
        navigate_to_comparison(demo_page)

        demo_page.locator("#comparison-run-btn").click()

        expect(demo_page.locator("#comparison-health")).to_be_visible()
        expect(demo_page.locator("#comparison-errors-card")).to_be_visible()

    def test_comparison_can_open_report_modal_with_attached_evidence(self, demo_page):
        navigate_to_comparison(demo_page)
        demo_page.locator("#comparison-run-btn").click()
        expect(demo_page.locator("#comparison-health")).to_be_visible()

        demo_page.locator("button.comparison-report-btn").click()
        expect(demo_page.locator("#report-modal")).to_have_class("modal-overlay open")

        comparison_toggle = demo_page.locator("#report-include-comparison")
        expect(comparison_toggle).to_be_enabled()
        expect(comparison_toggle).to_be_checked()

        note = demo_page.locator("#report-comparison-note")
        expect(note).to_contain_text("attached")
