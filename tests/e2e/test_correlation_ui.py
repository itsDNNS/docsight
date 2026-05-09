"""Browser coverage for the correlation timeline UI."""

from datetime import datetime, timedelta, timezone

from playwright.sync_api import expect

DESKTOP_VIEWPORT = {"width": 1440, "height": 1000}
MOBILE_VIEWPORT = {"width": 393, "height": 852}
MAX_HORIZONTAL_OVERFLOW = 1


def _sample_correlation_data():
    base = datetime.now(timezone.utc).replace(microsecond=0)

    def ts(minutes_ago):
        return (base - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")

    return [
        {
            "source": "modem",
            "timestamp": ts(45),
            "health": "good",
            "ds_snr_min": 38.2,
            "ds_power_avg": 1.3,
            "us_power_avg": 42.1,
            "ds_uncorrectable_errors": 0,
        },
        {
            "source": "speedtest",
            "timestamp": ts(35),
            "download_mbps": 280.4,
            "upload_mbps": 48.2,
            "ping_ms": 12.5,
            "jitter_ms": 1.7,
            "modem_health": "good",
        },
        {
            "source": "event",
            "timestamp": ts(25),
            "event_type": "health_change",
            "severity": "warning",
            "message": "Health changed from good to warning",
        },
        {
            "source": "event",
            "timestamp": ts(15),
            "event_type": "monitoring_started",
            "severity": "info",
            "message": "Monitoring started",
        },
    ]


def _route_sample_correlation(page):
    page.route("**/api/correlation?**", lambda route: route.fulfill(json=_sample_correlation_data()))
    page.route("**/api/weather/range?**", lambda route: route.fulfill(json=[]))
    page.route("**/api/fritzbox/segment-utilization/range?**", lambda route: route.fulfill(json=[]))


def _open_correlation(page):
    page.set_viewport_size(DESKTOP_VIEWPORT)
    base_url = page.url.split("#", 1)[0].split("?", 1)[0].rstrip("/")
    page.goto(f"{base_url}/?lang=en#correlation", wait_until="networkidle")
    page.wait_for_selector("#view-correlation.active", state="visible")
    page.wait_for_selector("#correlation-chart-container", state="visible")
    page.wait_for_selector("#correlation-table-card", state="visible")


def test_correlation_signal_legend_matches_home_chart_order(demo_page):
    page = demo_page
    _open_correlation(page)

    legend_metrics = page.locator("#correlation-legend span[data-metric]").evaluate_all(
        """
        (items) => items
            .map((item) => ({ metric: item.dataset.metric, text: item.textContent.trim() }))
            .filter((item) => ['dsPower', 'txPower', 'snr'].includes(item.metric))
        """
    )

    assert [item["metric"] for item in legend_metrics[:3]] == ["dsPower", "txPower", "snr"]
    assert "DS Power (dBmV)" in legend_metrics[0]["text"]
    assert "US Power (dBmV)" in legend_metrics[1]["text"]
    assert "SNR (dB)" in legend_metrics[2]["text"]


def test_correlation_table_keeps_stable_desktop_columns(demo_page):
    page = demo_page
    _open_correlation(page)

    table = page.locator("#correlation-table")
    expect(table).to_be_visible()
    expect(page.locator("#correlation-tbody tr").first).to_be_visible()

    geometry = page.evaluate(
        """
        () => {
            const table = document.querySelector('#correlation-table');
            const wrap = document.querySelector('#correlation-table-wrap');
            const firstRow = document.querySelector('#correlation-tbody tr');
            const cell = (selector) => {
                const node = firstRow.querySelector(selector);
                const rect = node.getBoundingClientRect();
                return { width: rect.width, whiteSpace: getComputedStyle(node).whiteSpace };
            };
            return {
                tableLayout: getComputedStyle(table).tableLayout,
                documentOverflow: document.documentElement.scrollWidth - window.innerWidth,
                wrapOverflow: wrap.scrollWidth - wrap.clientWidth,
                timestamp: cell('.correlation-cell-timestamp'),
                source: cell('.correlation-cell-source'),
                message: cell('.correlation-cell-message'),
                details: cell('.correlation-cell-details'),
            };
        }
        """
    )

    assert geometry["tableLayout"] == "fixed"
    assert geometry["documentOverflow"] <= MAX_HORIZONTAL_OVERFLOW
    assert geometry["wrapOverflow"] <= MAX_HORIZONTAL_OVERFLOW
    assert 150 <= geometry["timestamp"]["width"] <= 220
    assert 90 <= geometry["source"]["width"] <= 140
    assert geometry["message"]["width"] >= 180
    assert geometry["details"]["width"] >= geometry["message"]["width"]


def test_correlation_event_type_filter_updates_table_in_browser(demo_page):
    page = demo_page
    _route_sample_correlation(page)
    _open_correlation(page)

    event_rows = page.locator('#correlation-tbody tr[data-src="event"]')
    expect(event_rows).to_have_count(1)
    expect(event_rows.first.locator(".correlation-cell-details")).to_contain_text("Health Change")
    expect(page.locator("#correlation-legend .corr-legend-events")).to_contain_text("(1/2)")

    page.locator("#correlation-legend .corr-event-filter-btn").click()
    page.locator('#corr-event-popover input[data-event-type="health_change"]').evaluate(
        """
        (checkbox) => {
            checkbox.checked = false;
            checkbox.dispatchEvent(new Event('change', { bubbles: true }));
        }
        """
    )

    expect(event_rows).to_have_count(0)
    expect(page.locator("#correlation-legend .corr-legend-events")).to_contain_text("(0/2)")


def test_correlation_table_uses_card_layout_without_mobile_overflow(demo_page):
    page = demo_page
    page.set_viewport_size(MOBILE_VIEWPORT)
    _route_sample_correlation(page)
    base_url = page.url.split("#", 1)[0].split("?", 1)[0].rstrip("/")
    page.goto(f"{base_url}/?lang=en#correlation", wait_until="networkidle")
    page.wait_for_selector("#view-correlation.active", state="visible")
    page.wait_for_selector("#correlation-tbody tr", state="visible")

    geometry = page.evaluate(
        """
        () => {
            const wrap = document.querySelector('#correlation-table-wrap');
            const row = document.querySelector('#correlation-tbody tr');
            const timestamp = row.querySelector('.correlation-cell-timestamp');
            const before = getComputedStyle(timestamp, '::before');
            const rect = (node) => {
                const box = node.getBoundingClientRect();
                return { left: box.left, right: box.right, width: box.width, display: getComputedStyle(node).display };
            };
            return {
                viewportWidth: window.innerWidth,
                documentOverflow: document.documentElement.scrollWidth - window.innerWidth,
                wrapOverflow: wrap.scrollWidth - wrap.clientWidth,
                row: rect(row),
                timestamp: rect(timestamp),
                timestampLabel: before.content,
            };
        }
        """
    )

    assert geometry["documentOverflow"] <= MAX_HORIZONTAL_OVERFLOW
    assert geometry["wrapOverflow"] <= MAX_HORIZONTAL_OVERFLOW
    assert geometry["row"]["display"] == "block"
    assert geometry["row"]["left"] >= 0
    assert geometry["row"]["right"] <= geometry["viewportWidth"] + MAX_HORIZONTAL_OVERFLOW
    assert geometry["timestamp"]["display"] == "flex"
    assert geometry["timestamp"]["width"] >= 300
    assert "Timestamp" in geometry["timestampLabel"]
