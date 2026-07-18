"""Browser coverage for the correlation timeline UI."""

import csv
import io

from datetime import datetime, timedelta, timezone

import pytest
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


def _sample_correlation_severity_data():
    base = datetime.now(timezone.utc).replace(microsecond=0)

    def ts(minutes_ago):
        return (base - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")

    return [
        {
            "source": "modem",
            "timestamp": ts(60),
            "health": "good",
            "ds_snr_min": 38.5,
            "ds_power_avg": 1.1,
            "us_power_avg": 41.8,
            "ds_uncorrectable_errors": 0,
        },
        {
            "source": "event",
            "timestamp": ts(45),
            "event_type": "health_change",
            "severity": "warning",
            "message": "Health warning",
        },
        {
            "source": "event",
            "timestamp": ts(35),
            "event_type": "health_change",
            "severity": "critical",
            "message": "Health critical",
        },
        {
            "source": "event",
            "timestamp": ts(25),
            "event_type": "snr_change",
            "severity": "info",
            "message": "Informational SNR movement",
        },
    ]


def _sample_correlation_severity_edge_data():
    base = datetime.now(timezone.utc).replace(microsecond=0)

    def ts(minutes_ago):
        return (base - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")

    return [
        {
            "source": "modem",
            "timestamp": ts(60),
            "health": "good",
            "ds_snr_min": 38.5,
            "ds_power_avg": 1.1,
            "us_power_avg": 41.8,
            "ds_uncorrectable_errors": 0,
        },
        {
            "source": "event",
            "timestamp": ts(40),
            "event_type": 'custom" data-owned="1',
            "message": "Missing severity stays filterable",
        },
        {
            "source": "event",
            "timestamp": ts(30),
            "event_type": "snr_change",
            "severity": "debug",
            "message": "Unknown severity falls back to info",
        },
    ]


def _point_measurement_data():
    """Sparse Speedtests with modem and event evidence between the tests."""
    base = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=8)

    def ts(hours):
        return (base + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")

    return [
        {
            "source": "speedtest",
            "timestamp": ts(0),
            "download_mbps": 310.5,
            "upload_mbps": 51.25,
            "ping_ms": 11.75,
            "jitter_ms": 1.5,
            "packet_loss_pct": 0.25,
        },
        {
            "source": "modem",
            "timestamp": ts(2),
            "health": "good",
            "ds_snr_min": 37.0,
            "ds_power_avg": 1.0,
            "us_power_avg": 42.0,
            "ds_uncorrectable_errors": 4,
        },
        {
            "source": "modem",
            "timestamp": ts(4),
            "health": "marginal",
            "ds_snr_min": 35.0,
            "ds_power_avg": 0.5,
            "us_power_avg": 43.0,
            "ds_uncorrectable_errors": 12,
        },
        {
            "source": "event",
            "timestamp": ts(5),
            "event_type": "health_change",
            "severity": "warning",
            "message": "Signal degraded between tests",
        },
        {
            "source": "speedtest",
            "timestamp": ts(6),
            "download_mbps": 180.75,
            "upload_mbps": 34.5,
            "ping_ms": 19.25,
            "jitter_ms": 3.25,
            "packet_loss_pct": 1.5,
        },
    ]


def _single_point_measurement_data():
    base = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=8)

    def ts(hours):
        return (base + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")

    return [
        {
            "source": "modem",
            "timestamp": ts(0),
            "health": "good",
            "ds_snr_min": 38.0,
            "ds_power_avg": 1.0,
            "us_power_avg": 42.0,
            "ds_uncorrectable_errors": 0,
        },
        {
            "source": "speedtest",
            "timestamp": ts(3),
            "download_mbps": 222.2,
            "upload_mbps": 44.4,
            "ping_ms": 12.3,
            "jitter_ms": 2.1,
            "packet_loss_pct": 0.4,
        },
        {
            "source": "event",
            "timestamp": ts(6),
            "event_type": "monitoring_started",
            "severity": "info",
            "message": "Range boundary",
        },
    ]


def _dense_point_measurement_data():
    base = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=7)

    def ts(seconds):
        return (base + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")

    samples = []
    for index, seconds in enumerate((0, 10, 20, 21600)):
        samples.append({
            "source": "speedtest",
            "timestamp": ts(seconds),
            "download_mbps": 200 + index * 10,
            "upload_mbps": 40 + index,
        })
    return samples


def _partial_point_measurement_data():
    base = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=3)

    def ts(hours):
        return (base + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")

    return [
        {
            "source": "speedtest",
            "timestamp": ts(0),
            "download_mbps": 120.0,
            "ping_ms": -5.0,
            "jitter_ms": 1.0,
            "packet_loss_pct": 0.0,
        },
        {
            "source": "speedtest",
            "timestamp": ts(1),
            "download_mbps": -20.0,
            "upload_mbps": 0.0,
            "ping_ms": 0.0,
            "jitter_ms": -1.0,
            "packet_loss_pct": -1.0,
        },
        {
            "source": "speedtest",
            "timestamp": ts(1),
            "download_mbps": 33.0,
            "upload_mbps": -2.0,
            "ping_ms": 7.0,
            "jitter_ms": 2.0,
            "packet_loss_pct": 0.0,
        },
        {
            "source": "speedtest",
            "timestamp": ts(2),
            "download_mbps": 0.0,
            "upload_mbps": -4.0,
        },
    ]


def _record_correlation_canvas_operations(page):
    """Record paths on the real chart canvas without replacing canvas drawing."""
    page.add_init_script(
        """
        (() => {
            const proto = CanvasRenderingContext2D.prototype;
            const paths = new WeakMap();
            window.__corrCanvasOps = [];
            const originalClearRect = proto.clearRect;
            proto.clearRect = function(...args) {
                if (this.canvas && this.canvas.id === 'correlation-chart' && args[0] === 0 && args[1] === 0) {
                    window.__corrCanvasOps = [];
                }
                return originalClearRect.apply(this, args);
            };
            const recordPathMethod = (name) => {
                const original = proto[name];
                proto[name] = function(...args) {
                    if (this.canvas && this.canvas.id === 'correlation-chart') {
                        const path = paths.get(this) || [];
                        path.push({ kind: name, args: args.map(Number) });
                        paths.set(this, path);
                    }
                    return original.apply(this, args);
                };
            };
            const originalBeginPath = proto.beginPath;
            proto.beginPath = function(...args) {
                if (this.canvas && this.canvas.id === 'correlation-chart') paths.set(this, []);
                return originalBeginPath.apply(this, args);
            };
            ['moveTo', 'lineTo', 'bezierCurveTo', 'arc'].forEach(recordPathMethod);
            ['stroke', 'fill'].forEach((name) => {
                const original = proto[name];
                proto[name] = function(...args) {
                    if (this.canvas && this.canvas.id === 'correlation-chart') {
                        window.__corrCanvasOps.push({
                            kind: name,
                            strokeStyle: String(this.strokeStyle),
                            fillStyle: String(this.fillStyle),
                            lineWidth: this.lineWidth,
                            path: (paths.get(this) || []).map((part) => ({ ...part })),
                        });
                    }
                    return original.apply(this, args);
                };
            });
            const originalFillRect = proto.fillRect;
            proto.fillRect = function(...args) {
                if (this.canvas && this.canvas.id === 'correlation-chart') {
                    window.__corrCanvasOps.push({
                        kind: 'fillRect',
                        fillStyle: String(this.fillStyle),
                        args: args.map(Number),
                    });
                }
                return originalFillRect.apply(this, args);
            };
        })();
        """
    )


def _route_correlation(page, payload=None):
    page.route("**/api/correlation?**", lambda route: route.fulfill(json=_sample_correlation_data() if payload is None else payload))
    page.route("**/api/weather/range?**", lambda route: route.fulfill(json=[]))
    page.route("**/api/fritzbox/segment-utilization/range?**", lambda route: route.fulfill(json=[]))
    page.route("**/api/connection-monitor/targets", lambda route: route.fulfill(json=[]))
    page.route(
        "**/api/connection-monitor/samples/**",
        lambda route: route.fulfill(
            json={
                "meta": {"resolution": "raw", "bucket_seconds": None, "blended": False, "mixed": False},
                "samples": [],
            }
        ),
    )


def _route_sample_correlation(page):
    _route_correlation(page)


def _route_reachability(page, samples_by_target, targets=None, request_count=None):
    targets = targets if targets is not None else [
        {"id": target_id, "label": f"Target {target_id}", "enabled": True, "poll_interval_ms": 10000}
        for target_id in sorted(samples_by_target)
    ]

    def targets_handler(route):
        if request_count is not None:
            request_count["targets"] = request_count.get("targets", 0) + 1
        route.fulfill(json=targets)

    def samples_handler(route):
        target_id = int(route.request.url.split("/samples/", 1)[1].split("?", 1)[0])
        if request_count is not None:
            request_count["samples"] = request_count.get("samples", 0) + 1
        route.fulfill(
            json={
                "meta": {"resolution": "raw", "bucket_seconds": None, "blended": False, "mixed": False},
                "samples": samples_by_target.get(target_id, []),
            }
        )

    page.unroute("**/api/connection-monitor/targets")
    page.unroute("**/api/connection-monitor/samples/**")
    page.route("**/api/connection-monitor/targets", targets_handler)
    page.route("**/api/connection-monitor/samples/**", samples_handler)


def _open_correlation(page, viewport=DESKTOP_VIEWPORT, expect_table=True):
    page.set_viewport_size(viewport)
    base_url = page.url.split("#", 1)[0].split("?", 1)[0].rstrip("/")
    page.goto(f"{base_url}/?lang=en#correlation", wait_until="networkidle")
    page.wait_for_selector("#view-correlation.active", state="visible")
    page.wait_for_selector("#correlation-chart-container", state="visible")
    if expect_table:
        page.wait_for_selector("#correlation-table-card", state="visible")


def _hover_correlation_timestamp(page, timestamp):
    point = page.evaluate(
        """
        (timestamp) => ({
            x: window._corrChartState.xScale(new Date(timestamp).getTime()),
            y: window._corrChartState.pad.top + window._corrChartState.plotH / 2,
        })
        """,
        timestamp,
    )
    overlay = page.locator("#correlation-overlay")
    box = overlay.bounding_box()
    assert box is not None
    page.mouse.move(box["x"] + point["x"] - 1, box["y"] + point["y"])
    page.mouse.move(box["x"] + point["x"], box["y"] + point["y"])
    tooltip = page.locator("#correlation-tooltip")
    expect(tooltip).to_be_visible()
    return tooltip


def test_reachability_bucket_helper_uses_coverage_weighting_and_unknown_gaps(demo_page):
    page = demo_page
    result = page.evaluate(
        """
        () => window._corrBucketReachability([
            {
                target: { id: 1, label: 'Gateway', poll_interval_ms: 10000 },
                samples: [
                    { timestamp: 1000, bucket_seconds: null, packet_loss_pct: 100, sample_count: 1 },
                    { timestamp: 1040, bucket_seconds: 20, packet_loss_pct: 0, sample_count: 3 },
                ],
            },
            {
                target: { id: 2, label: 'Resolver', poll_interval_ms: 20000 },
                samples: [
                    { timestamp: 1005, bucket_seconds: null, packet_loss_pct: 0, sample_count: 1 },
                    { timestamp: 1040, bucket_seconds: 20, packet_loss_pct: 100, sample_count: 1 },
                ],
            },
        ], 1000000, 1080000, 8)
        """
    )

    assert len(result) == 8
    assert [bucket["startMs"] for bucket in result] == list(range(1000000, 1080000, 10000))
    # A failed target plus a healthy target is degraded, never down.
    assert result[0]["state"] == "degraded"
    assert result[0]["lossPct"] == 50
    assert result[0]["sampleCount"] == 2
    assert result[0]["targetsObserved"] == 2
    # Offset coverage intersects both adjacent display buckets.
    assert result[1]["state"] == "ok"
    assert result[2]["state"] == "ok"
    assert result[3]["state"] == "unknown"
    # Aggregate sample_count weights loss: (0*3 + 100*1) / 4.
    assert result[4]["state"] == "degraded"
    assert result[4]["lossPct"] == 25
    assert result[4]["sampleCount"] == 4
    assert result[4]["targetsObserved"] == 2
    assert result[5]["state"] == "degraded"
    assert result[6]["state"] == "unknown"


def test_reachability_bucket_helper_empty_never_ok_and_caps_long_ranges(demo_page):
    page = demo_page
    result = page.evaluate(
        """
        () => ({
            empty: window._corrBucketReachability([], 0, 1000, 10),
            long: window._corrBucketReachability([
                {
                    target: { id: 1, poll_interval_ms: 5000 },
                    samples: [{ timestamp: 1700000000, bucket_seconds: 3600, packet_loss_pct: 100, sample_count: 720 }],
                },
            ], 1700000000000, 1707776000000, 1000),
        })
        """
    )

    assert len(result["empty"]) == 10
    assert {bucket["state"] for bucket in result["empty"]} == {"unknown"}
    assert len(result["long"]) == 300
    assert result["long"][0]["startMs"] == 1700000000000
    assert result["long"][-1]["endMs"] == 1707776000000


def test_reachability_bucket_helper_classifies_all_four_states_and_all_target_down(demo_page):
    page = demo_page
    result = page.evaluate(
        """
        () => window._corrBucketReachability([
            {
                target: { id: 1, poll_interval_ms: 10000 },
                samples: [
                    { timestamp: 2000, packet_loss_pct: 0, sample_count: 1 },
                    { timestamp: 2010, packet_loss_pct: 25, sample_count: 2 },
                    { timestamp: 2020, packet_loss_pct: 100, sample_count: 1 },
                ],
            },
            {
                target: { id: 2, poll_interval_ms: 10000 },
                samples: [
                    { timestamp: 2020, packet_loss_pct: 100, sample_count: 3 },
                ],
            },
        ], 2000000, 2040000, 4)
        """
    )

    assert [bucket["state"] for bucket in result] == ["ok", "degraded", "down", "unknown"]
    assert result[2]["lossPct"] == 100
    assert result[2]["sampleCount"] == 4
    assert result[2]["targetsObserved"] == 2


@pytest.mark.parametrize("viewport", [DESKTOP_VIEWPORT, MOBILE_VIEWPORT])
def test_correlation_renders_aligned_reachability_lane_and_legend(demo_page, viewport):
    page = demo_page
    page.set_viewport_size(viewport)
    now = int(datetime.now(timezone.utc).timestamp())
    _record_correlation_canvas_operations(page)
    _route_correlation(page)
    _route_reachability(
        page,
        {
            1: [
                {"timestamp": now - 2400, "bucket_seconds": 600, "packet_loss_pct": 0, "sample_count": 120},
                {"timestamp": now - 1200, "bucket_seconds": 600, "packet_loss_pct": 100, "sample_count": 120},
            ],
            2: [
                {"timestamp": now - 1200, "bucket_seconds": 600, "packet_loss_pct": 0, "sample_count": 120},
            ],
        },
    )
    _open_correlation(page, viewport)

    state = page.evaluate(
        """
        () => ({
            lane: window._corrChartState.reachabilityLane,
            buckets: window._corrChartState.reachabilityBuckets,
            height: document.querySelector('#correlation-chart').height / devicePixelRatio,
            fills: window.__corrCanvasOps.filter((op) => op.kind === 'fillRect'),
        })
        """
    )
    assert state["lane"]
    assert state["height"] == 306
    assert len(state["buckets"]) <= 300
    assert any(bucket["state"] == "ok" for bucket in state["buckets"])
    assert any(bucket["state"] == "degraded" for bucket in state["buckets"])
    assert any(bucket["state"] == "unknown" for bucket in state["buckets"])
    assert any(abs(fill["args"][1] - state["lane"]["y"]) < 0.01 for fill in state["fills"])
    expect(page.locator('#correlation-legend [data-metric="reachability"]')).to_be_visible()
    described_by = page.locator("#correlation-overlay").get_attribute("aria-describedby").split()
    assert "correlation-reachability-hint" in described_by


def test_sparse_cm_only_chart_uses_complete_selected_range_with_unknown_edges(demo_page):
    page = demo_page
    _route_correlation(page)
    _open_correlation(page)

    result = page.evaluate(
        """
        () => {
            const startMs = Date.UTC(2024, 0, 1, 0, 0, 0);
            const endMs = startMs + 24 * 60 * 60 * 1000;
            const sampleStartMs = startMs + 12 * 60 * 60 * 1000;
            const sampleEndMs = sampleStartMs + 5 * 60 * 1000;
            window._corrSelectedRange = { startMs, endMs };
            window._corrTargetData = [{
                target: { id: 1, label: 'Fixed healthy target', poll_interval_ms: 5000 },
                samples: [{
                    timestamp: sampleStartMs / 1000,
                    bucket_seconds: 300,
                    packet_loss_pct: 0,
                    sample_count: 60,
                }],
            }];
            window._correlationData = [];
            window._corrZoom = null;
            window.renderCorrelationChart([]);

            const state = window._corrChartState;
            const observedBuckets = state.reachabilityBuckets.filter(
                (bucket) => bucket.startMs < sampleEndMs && bucket.endMs > sampleStartMs
            );
            const unknownCount = state.reachabilityBuckets.filter(
                (bucket) => bucket.state === 'unknown'
            ).length;
            return {
                startMs,
                endMs,
                tMin: state.tMin,
                tMax: state.tMax,
                tMinFull: state.tMinFull,
                tMaxFull: state.tMaxFull,
                firstState: state.reachabilityBuckets[0].state,
                lastState: state.reachabilityBuckets[state.reachabilityBuckets.length - 1].state,
                observedStates: observedBuckets.map((bucket) => bucket.state),
                unknownCount,
                ariaLabel: document.querySelector('#correlation-overlay').getAttribute('aria-label'),
            };
        }
        """
    )

    assert result["tMin"] == result["tMinFull"] == result["startMs"]
    assert result["tMax"] == result["tMaxFull"] == result["endMs"]
    assert result["firstState"] == "unknown"
    assert result["lastState"] == "unknown"
    assert result["observedStates"]
    assert set(result["observedStates"]) == {"ok"}
    assert result["unknownCount"] > 0
    assert f'Unknown {result["unknownCount"]}' in result["ariaLabel"]


def test_reachability_legend_tooltip_and_mouse_keyboard_drilldown(demo_page):
    page = demo_page
    now = int(datetime.now(timezone.utc).timestamp())
    _route_correlation(page)
    _route_reachability(
        page,
        {1: [{"timestamp": now - 1800, "bucket_seconds": 900, "packet_loss_pct": 12.5, "sample_count": 18}]},
        targets=[{"id": 1, "label": "Gateway", "enabled": True, "poll_interval_ms": 5000}],
    )
    _open_correlation(page)

    overlay = page.locator("#correlation-overlay")
    expect(overlay).to_have_attribute("role", "button")
    expect(overlay).to_have_attribute("tabindex", "0")

    legend = page.locator('#correlation-legend [data-metric="reachability"]')
    legend.click()
    expect(legend).to_have_class("disabled")
    assert page.evaluate("() => window._corrVisible.reachability") is False
    expect(overlay).to_have_attribute("role", "img")
    assert overlay.get_attribute("tabindex") is None
    legend.click()
    assert page.evaluate("() => window._corrVisible.reachability") is True
    expect(overlay).to_have_attribute("role", "button")
    expect(overlay).to_have_attribute("tabindex", "0")

    lane_point = page.evaluate(
        """
        () => {
            const st = window._corrChartState;
            const bucket = st.reachabilityBuckets.find((item) => item.sampleCount > 0);
            return {
                x: st.xScale((bucket.startMs + bucket.endMs) / 2),
                y: st.reachabilityLane.y + st.reachabilityLane.height / 2,
            };
        }
        """
    )
    box = overlay.bounding_box()
    page.mouse.move(box["x"] + lane_point["x"], box["y"] + lane_point["y"])
    tooltip = page.locator("#correlation-tooltip")
    expect(tooltip).to_be_visible()
    tooltip_text = tooltip.inner_text()
    for expected in ("Reachability", "State", "Window", "Observed packet loss", "Samples", "Observed targets", "Target scope", "Gateway"):
        assert expected in tooltip_text

    overlay.focus()
    overlay.press("Enter")
    expect(page.locator("#view-connection-monitor.active")).to_be_visible()
    destination_title = page.locator("#cm-detail-view .view-page-title")
    expect(destination_title).to_have_attribute("tabindex", "-1")
    expect(destination_title).to_be_focused()
    page.evaluate("() => window.switchView('correlation')")
    page.wait_for_selector("#view-correlation.active")
    page.wait_for_selector("#correlation-chart-container", state="visible")
    overlay.focus()
    overlay.press("Space")
    expect(page.locator("#view-connection-monitor.active")).to_be_visible()
    expect(destination_title).to_be_focused()
    page.evaluate("() => window.switchView('correlation')")
    page.wait_for_selector("#view-correlation.active")
    page.wait_for_selector("#correlation-chart-container", state="visible")
    overlay = page.locator("#correlation-overlay")
    box = overlay.bounding_box()
    lane_point = page.evaluate(
        "() => ({ x: window._corrChartState.pad.left + 2, y: window._corrChartState.reachabilityLane.y + 2 })"
    )
    page.mouse.click(box["x"] + lane_point["x"], box["y"] + lane_point["y"])
    expect(page.locator("#view-connection-monitor.active")).to_be_visible()
    expect(destination_title).to_be_focused()


def test_correlation_zoom_rebuckets_loaded_samples_without_cm_refetch(demo_page):
    page = demo_page
    now = int(datetime.now(timezone.utc).timestamp())
    request_count = {}
    _route_correlation(page)
    _route_reachability(
        page,
        {1: [{"timestamp": now - 3600, "bucket_seconds": 1800, "packet_loss_pct": 100, "sample_count": 360}]},
        request_count=request_count,
    )
    _open_correlation(page)
    initial_requests = dict(request_count)
    result = page.evaluate(
        """
        () => {
            const before = window._corrChartState.reachabilityBuckets;
            const observed = before.find((bucket) => bucket.sampleCount > 0);
            window._corrZoom = { tMin: observed.startMs, tMax: observed.endMs };
            window.renderCorrelationChart(window._correlationData);
            return {
                beforeWidth: before[0].endMs - before[0].startMs,
                afterWidth: window._corrChartState.reachabilityBuckets[0].endMs - window._corrChartState.reachabilityBuckets[0].startMs,
            };
        }
        """
    )
    assert request_count == initial_requests
    assert result["afterWidth"] < result["beforeWidth"]


def test_drag_zoom_ending_in_reachability_lane_suppresses_drilldown(demo_page):
    page = demo_page
    now = int(datetime.now(timezone.utc).timestamp())
    request_count = {}
    _route_correlation(page)
    _route_reachability(
        page,
        {1: [{"timestamp": now - 3600, "bucket_seconds": 1800, "packet_loss_pct": 25, "sample_count": 360}]},
        request_count=request_count,
    )
    _open_correlation(page)
    initial_requests = dict(request_count)
    drag = page.evaluate(
        """
        () => {
            const st = window._corrChartState;
            return {
                startX: st.pad.left + st.plotW * 0.2,
                startY: st.pad.top + st.plotH / 2,
                endX: st.pad.left + st.plotW * 0.7,
                endY: st.reachabilityLane.y + st.reachabilityLane.height / 2,
                initialSpan: st.tMax - st.tMin,
            };
        }
        """
    )
    overlay = page.locator("#correlation-overlay")
    box = overlay.bounding_box()
    assert box is not None

    page.mouse.move(box["x"] + drag["startX"], box["y"] + drag["startY"])
    page.mouse.down()
    page.mouse.move(box["x"] + drag["endX"], box["y"] + drag["endY"])
    page.mouse.up()
    page.wait_for_function("() => window._corrZoom !== null")

    zoom_span = page.evaluate("() => window._corrZoom.tMax - window._corrZoom.tMin")
    assert zoom_span < drag["initialSpan"]
    expect(page.locator("#view-correlation.active")).to_be_visible()
    expect(page.locator("#view-connection-monitor.active")).to_have_count(0)
    assert request_count == initial_requests


@pytest.mark.parametrize("mode", ["zero_targets", "no_samples", "samples_outside", "api_error"])
def test_correlation_cm_empty_and_error_states_leave_base_chart_usable(demo_page, mode):
    page = demo_page
    console_errors = []
    page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
    _route_correlation(page)
    if mode == "zero_targets":
        _route_reachability(page, {}, targets=[])
    elif mode == "no_samples":
        _route_reachability(page, {1: []})
    elif mode == "samples_outside":
        old_timestamp = int((datetime.now(timezone.utc) - timedelta(days=2)).timestamp())
        _route_reachability(
            page,
            {1: [{"timestamp": old_timestamp, "bucket_seconds": 60, "packet_loss_pct": 0, "sample_count": 12}]},
        )
    else:
        page.route("**/api/connection-monitor/targets", lambda route: route.fulfill(json=None))
    _open_correlation(page)

    expect(page.locator("#correlation-chart-container")).to_be_visible()
    assert page.evaluate("() => window._corrChartState.reachabilityLane") is None
    assert page.locator('#correlation-legend [data-metric="reachability"]').count() == 0
    overlay = page.locator("#correlation-overlay")
    expect(overlay).to_have_attribute("role", "img")
    assert overlay.get_attribute("tabindex") is None
    expected_state = {
        "zero_targets": "targets_absent",
        "no_samples": "no_samples",
        "samples_outside": "samples_outside_range",
        "api_error": "fetch_error",
    }[mode]
    assert page.evaluate("() => window._corrCmState") == expected_state
    assert console_errors == []


def test_cm_only_correlation_remains_available_with_paused_collector_history(demo_page):
    page = demo_page
    now = int(datetime.now(timezone.utc).timestamp())
    _route_correlation(page, payload=[])
    _route_reachability(
        page,
        {1: [{"timestamp": now - 600, "bucket_seconds": 300, "packet_loss_pct": 0, "sample_count": 60}]},
        targets=[{"id": 1, "label": "Historical target", "enabled": True, "poll_interval_ms": 5000}],
    )
    _open_correlation(page, expect_table=False)

    expect(page.locator('.nav-item[data-view="correlation"]')).to_be_attached()
    expect(page.locator("#correlation-chart-container")).to_be_visible()
    expect(page.locator('#correlation-legend [data-metric="reachability"]')).to_be_visible()
    expect(page.locator("#correlation-table-card")).to_be_hidden()
    assert page.evaluate("() => window._corrCmState") == "ready"


def test_correlation_fetches_samples_only_for_enabled_targets(demo_page):
    page = demo_page
    now = int(datetime.now(timezone.utc).timestamp())
    fetched_target_ids = []
    _route_correlation(page)
    targets = [
        {"id": 1, "label": "Enabled history", "enabled": True, "poll_interval_ms": 5000},
        {"id": 2, "label": "Disabled target", "enabled": False, "poll_interval_ms": 5000},
    ]
    page.route("**/api/connection-monitor/targets", lambda route: route.fulfill(json=targets))

    def sample_handler(route):
        target_id = int(route.request.url.split("/samples/", 1)[1].split("?", 1)[0])
        fetched_target_ids.append(target_id)
        route.fulfill(
            json={
                "meta": {"resolution": "raw", "bucket_seconds": None},
                "samples": [{"timestamp": now - 300, "bucket_seconds": 60, "packet_loss_pct": 0, "sample_count": 12}],
            }
        )

    page.route("**/api/connection-monitor/samples/**", sample_handler)
    _open_correlation(page)

    assert fetched_target_ids
    assert set(fetched_target_ids) == {1}


def test_module_absent_gate_makes_no_connection_monitor_requests(demo_page):
    page = demo_page
    _route_correlation(page)
    request_count = {}
    _route_reachability(page, {}, targets=[], request_count=request_count)
    _open_correlation(page)
    request_count.clear()
    page.evaluate(
        """
        () => {
            window.CORRELATION_CM_AVAILABLE = false;
            window.loadCorrelationData();
        }
        """
    )
    page.wait_for_function("() => document.querySelector('#correlation-loading').style.display === 'none'")
    assert request_count == {}
    assert page.evaluate("() => window._corrCmState") == "module_absent"


def test_reachability_csv_contract_and_png_composition(demo_page):
    page = demo_page
    now = int(datetime.now(timezone.utc).timestamp())
    page.add_init_script(
        """
        (() => {
            window.__corrExport = { drawSources: [], legendText: [], csv: null };
            const drawImage = CanvasRenderingContext2D.prototype.drawImage;
            CanvasRenderingContext2D.prototype.drawImage = function(source, ...args) {
                if (source && source.id) window.__corrExport.drawSources.push(source.id);
                return drawImage.call(this, source, ...args);
            };
            const fillText = CanvasRenderingContext2D.prototype.fillText;
            CanvasRenderingContext2D.prototype.fillText = function(value, ...args) {
                if (!this.canvas.id) window.__corrExport.legendText.push(String(value));
                return fillText.call(this, value, ...args);
            };
            const createObjectURL = URL.createObjectURL.bind(URL);
            URL.createObjectURL = function(blob) {
                blob.text().then((text) => { window.__corrExport.csv = text; });
                return createObjectURL(blob);
            };
            HTMLAnchorElement.prototype.click = function() {};
        })();
        """
    )
    payload = _single_point_measurement_data()
    _route_correlation(page, payload)
    malicious_label = '  =HYPERLINK("https://evil.invalid","click")'
    _route_reachability(
        page,
        {1: [{"timestamp": now - 900, "bucket_seconds": 300, "packet_loss_pct": 25, "sample_count": 60}]},
        targets=[{"id": 1, "label": malicious_label, "enabled": True, "poll_interval_ms": 5000}],
    )
    _open_correlation(page)
    page.evaluate("() => { window._corrExportPNG(); window._corrExportCSV(); }")
    page.wait_for_function("() => window.__corrExport.csv !== null")
    exported = page.evaluate("() => window.__corrExport")

    assert "correlation-chart" in exported["drawSources"]
    assert "correlation-overlay" in exported["drawSources"]
    assert any("Reachability" in text for text in exported["legendText"])
    lines = exported["csv"].splitlines()
    assert lines[0].split(",") == [
        "timestamp", "source", "health", "ds_snr_min", "ds_power_avg", "us_power_avg",
        "ds_uncorrectable_errors", "download_mbps", "upload_mbps", "ping_ms", "severity", "message",
        "state", "packet_loss_pct", "sample_count", "bucket_start", "bucket_end", "target_scope",
    ]
    speed_row = next(line for line in lines[1:] if ",speedtest," in line)
    assert speed_row.split(",")[-6:] == ["", "", "", "", "", ""]
    cm_rows = [line for line in lines[1:] if ",connection_monitor," in line]
    assert cm_rows
    assert any(",degraded,25,60," in line for line in cm_rows)
    parsed_rows = list(csv.DictReader(io.StringIO(exported["csv"])))
    target_scopes = [row["target_scope"] for row in parsed_rows if row["source"] == "connection_monitor"]
    assert "'" + malicious_label in target_scopes
    assert malicious_label not in target_scopes


def test_localized_reachability_aria_summary(demo_page):
    page = demo_page
    now = int(datetime.now(timezone.utc).timestamp())
    _route_correlation(page)
    _route_reachability(page, {1: [{"timestamp": now - 600, "bucket_seconds": 300, "packet_loss_pct": 0, "sample_count": 60}]})
    base_url = page.url.split("#", 1)[0].split("?", 1)[0].rstrip("/")
    page.goto(f"{base_url}/?lang=de#correlation", wait_until="networkidle")
    page.wait_for_selector("#correlation-chart-container", state="visible")
    aria_label = page.locator("#correlation-overlay").get_attribute("aria-label")
    assert "Erreichbarkeit" in aria_label
    assert "Zusammenfassung" in aria_label
    assert "Reachability summary" not in aria_label


def test_correlation_renders_sparse_speedtests_as_unconnected_point_measurements(demo_page):
    page = demo_page
    payload = _point_measurement_data()
    _record_correlation_canvas_operations(page)
    _route_correlation(page, payload)
    _open_correlation(page)
    page.evaluate("() => { window._corrVisible.events = true; window.renderCorrelationChart(window._correlationData); }")

    rendered = page.evaluate(
        """
        () => ({
            marks: window._corrChartState.speedMarks,
            colors: window._corrChartState.colors,
            operations: window.__corrCanvasOps,
        })
        """
    )
    marks = rendered["marks"]
    assert [mark["timestamp"] for mark in marks] == [payload[0]["timestamp"], payload[-1]["timestamp"]]
    assert all(mark["visible"] for mark in marks)
    assert all(abs(mark["downloadX"] - (mark["timestampX"] - mark["offset"])) < 0.01 for mark in marks)
    assert all(abs(mark["uploadX"] - (mark["timestampX"] + mark["offset"])) < 0.01 for mark in marks)
    assert all(1 <= mark["stemWidth"] <= 2 for mark in marks)

    speed_colors = {rendered["colors"]["download"], rendered["colors"]["upload"]}
    speed_strokes = [
        operation for operation in rendered["operations"]
        if operation["kind"] == "stroke" and operation["strokeStyle"] in speed_colors
    ]
    assert speed_strokes
    assert all(
        part["kind"] in {"moveTo", "lineTo"}
        for operation in speed_strokes
        for part in operation["path"]
    )
    speed_lines = [
        operation["path"]
        for operation in speed_strokes
        if any(part["kind"] == "lineTo" for part in operation["path"])
    ]
    assert sum(sum(part["kind"] == "lineTo" for part in path) for path in speed_lines) == 4
    for path in speed_lines:
        for start, end in zip(path, path[1:]):
            if start["kind"] == "moveTo" and end["kind"] == "lineTo":
                assert abs(start["args"][0] - end["args"][0]) < 0.01

    speed_operation_indexes = [
        index for index, operation in enumerate(rendered["operations"])
        if (
            operation["kind"] == "stroke" and operation.get("strokeStyle") in speed_colors
        ) or (
            operation["kind"] == "fill" and operation.get("fillStyle") in speed_colors
        )
    ]
    signal_indexes = [
        index for index, operation in enumerate(rendered["operations"])
        if operation.get("strokeStyle") == rendered["colors"]["snr"]
    ]
    error_indexes = [
        index for index, operation in enumerate(rendered["operations"])
        if operation["kind"] == "fillRect" and "239" in operation.get("fillStyle", "")
    ]
    event_indexes = [
        index for index, operation in enumerate(rendered["operations"])
        if operation["kind"] == "stroke" and operation.get("strokeStyle") == rendered["colors"]["event"]
    ]
    assert signal_indexes and error_indexes and event_indexes
    assert max(speed_operation_indexes) < min(signal_indexes)
    assert max(speed_operation_indexes) < min(error_indexes)
    assert max(speed_operation_indexes) < min(event_indexes)


def test_correlation_single_speedtest_uses_stem_and_larger_head(demo_page):
    page = demo_page
    payload = _single_point_measurement_data()
    _record_correlation_canvas_operations(page)
    _route_correlation(page, payload)
    _open_correlation(page, MOBILE_VIEWPORT)

    result = page.evaluate(
        """
        () => ({
            marks: window._corrChartState.speedMarks,
            colors: window._corrChartState.colors,
            operations: window.__corrCanvasOps,
        })
        """
    )
    assert len(result["marks"]) == 1
    mark = result["marks"][0]
    assert mark["timestamp"] == payload[1]["timestamp"]
    assert mark["headRadius"] >= 4
    assert 1 <= mark["stemWidth"] <= 2
    speed_strokes = [
        operation for operation in result["operations"]
        if operation["kind"] == "stroke"
        and operation["strokeStyle"] in {result["colors"]["download"], result["colors"]["upload"]}
    ]
    assert sum(
        sum(part["kind"] == "lineTo" for part in operation["path"])
        for operation in speed_strokes
    ) == 2


def test_correlation_adapts_dense_mobile_and_zoomed_marks_without_merging(demo_page):
    page = demo_page
    payload = _dense_point_measurement_data()
    _route_correlation(page, payload)
    _open_correlation(page, MOBILE_VIEWPORT)

    dense_marks = page.evaluate("() => window._corrChartState.speedMarks")
    assert len(dense_marks) == len(payload)
    assert len({mark["timestamp"] for mark in dense_marks}) == len(payload)
    assert all(mark["offset"] == 0 for mark in dense_marks[:3])
    assert all(mark["downloadX"] == mark["uploadX"] == mark["timestampX"] for mark in dense_marks[:3])

    first_ts = datetime.fromisoformat(payload[0]["timestamp"].replace("Z", "+00:00")).timestamp() * 1000
    third_ts = datetime.fromisoformat(payload[2]["timestamp"].replace("Z", "+00:00")).timestamp() * 1000
    zoomed_marks = page.evaluate(
        """
        ({ firstTs, thirdTs }) => {
            window._corrZoom = { tMin: firstTs - 1000, tMax: thirdTs + 1000 };
            window.renderCorrelationChart(window._correlationData);
            return window._corrChartState.speedMarks;
        }
        """,
        {"firstTs": first_ts, "thirdTs": third_ts},
    )
    assert len(zoomed_marks) == len(payload)
    visible_marks = [mark for mark in zoomed_marks if mark["visible"]]
    assert len(visible_marks) == 3
    for index, mark in enumerate(visible_marks):
        neighbor_distances = []
        if index > 0:
            neighbor_distances.append(abs(mark["timestampX"] - visible_marks[index - 1]["timestampX"]))
        if index < len(visible_marks) - 1:
            neighbor_distances.append(abs(visible_marks[index + 1]["timestampX"] - mark["timestampX"]))
        assert abs(mark["nearestVisibleDistance"] - min(neighbor_distances)) < 0.01
    assert all(mark["offset"] > 0 for mark in visible_marks)
    assert all(mark["downloadX"] < mark["timestampX"] < mark["uploadX"] for mark in visible_marks)
    assert all(mark["offset"] < mark["nearestVisibleDistance"] / 2 for mark in visible_marks)


def test_correlation_speedtest_help_accessibility_and_tooltip_details(demo_page):
    page = demo_page
    payload = _single_point_measurement_data()
    _route_correlation(page, payload)
    _open_correlation(page)

    help_text = page.locator("#correlation-speedtest-hint")
    expect(help_text).to_be_visible()
    expect(help_text).to_contain_text("individual measurements")
    expect(help_text).to_contain_text("between tests")
    overlay = page.locator("#correlation-overlay")
    described_by = overlay.get_attribute("aria-describedby").split()
    assert "correlation-speedtest-hint" in described_by
    aria_label = overlay.get_attribute("aria-label")
    assert aria_label
    assert "chart" in aria_label.lower()
    assert "speedtest" in aria_label.lower()

    speed_timestamp = payload[1]["timestamp"]
    tooltip = _hover_correlation_timestamp(page, speed_timestamp)
    tooltip_text = tooltip.inner_text()
    assert "Timestamp" in tooltip_text
    assert speed_timestamp[:10] in tooltip_text
    assert "Download: 222.2 Mbps" in tooltip_text
    assert "Upload: 44.4 Mbps" in tooltip_text
    assert "Ping: 12.3 ms" in tooltip_text
    assert "Jitter: 2.1 ms" in tooltip_text
    assert "Packet Loss: 0.4%" in tooltip_text


def test_correlation_tooltip_respects_each_speed_legend_toggle_at_exact_timestamp(demo_page):
    page = demo_page
    payload = _single_point_measurement_data()
    _route_correlation(page, payload)
    _open_correlation(page)
    speed_timestamp = payload[1]["timestamp"]

    page.locator('#correlation-legend span[data-metric="download"]').click()
    tooltip_text = _hover_correlation_timestamp(page, speed_timestamp).inner_text()
    assert "Download:" not in tooltip_text
    assert "Upload: 44.4 Mbps" in tooltip_text
    assert "Ping: 12.3 ms" in tooltip_text
    assert speed_timestamp[:10] in tooltip_text

    page.locator('#correlation-legend span[data-metric="download"]').click()
    page.locator('#correlation-legend span[data-metric="upload"]').click()
    tooltip_text = _hover_correlation_timestamp(page, speed_timestamp).inner_text()
    assert "Download: 222.2 Mbps" in tooltip_text
    assert "Upload:" not in tooltip_text
    assert "Packet Loss: 0.4%" in tooltip_text
    assert speed_timestamp[:10] in tooltip_text


def test_correlation_zoom_without_visible_speedtests_has_no_speed_tooltip_or_highlight(demo_page):
    page = demo_page
    payload = _point_measurement_data()
    _route_correlation(page, payload)
    _open_correlation(page)

    zoom_start = datetime.fromisoformat(payload[1]["timestamp"].replace("Z", "+00:00")).timestamp() * 1000
    zoom_end = datetime.fromisoformat(payload[2]["timestamp"].replace("Z", "+00:00")).timestamp() * 1000
    result = page.evaluate(
        """
        ({ zoomStart, zoomEnd }) => {
            const proto = CanvasRenderingContext2D.prototype;
            const originalArc = proto.arc;
            window.__corrOverlayArcs = [];
            proto.arc = function(...args) {
                if (this.canvas && this.canvas.id === 'correlation-overlay') {
                    window.__corrOverlayArcs.push(args.map(Number));
                }
                return originalArc.apply(this, args);
            };
            Object.keys(window._corrVisible).forEach((metric) => { window._corrVisible[metric] = false; });
            window._corrVisible.download = true;
            window._corrZoom = { tMin: zoomStart, tMax: zoomEnd };
            window.renderCorrelationChart(window._correlationData);
            window.__corrOverlayArcs = [];
            return window._corrChartState.speedMarks.map((mark) => mark.visible);
        }
        """,
        {"zoomStart": zoom_start, "zoomEnd": zoom_end},
    )
    assert result == [False, False]

    mid_timestamp = datetime.fromtimestamp((zoom_start + zoom_end) / 2000, tz=timezone.utc).isoformat()
    tooltip_text = _hover_correlation_timestamp(page, mid_timestamp).inner_text()
    assert "Download:" not in tooltip_text
    assert page.locator("#correlation-tooltip .tt-speedtest-time").count() == 0
    assert page.locator('#correlation-tbody tr[data-src="speedtest"].corr-highlight').count() == 0
    assert page.evaluate("() => window.__corrOverlayArcs") == []


def test_correlation_partial_and_negative_speedtests_keep_samples_without_invalid_marks(demo_page):
    page = demo_page
    payload = _partial_point_measurement_data()
    _record_correlation_canvas_operations(page)
    _route_correlation(page, payload)
    _open_correlation(page)

    rendered = page.evaluate(
        """
        () => ({
            marks: window._corrChartState.speedMarks,
            baselineY: window._corrChartState.yDl(0),
            colors: window._corrChartState.colors,
            operations: window.__corrCanvasOps,
        })
        """
    )
    marks = rendered["marks"]
    assert len(marks) == len(payload)
    assert [mark["timestamp"] for mark in marks] == [sample["timestamp"] for sample in payload]
    assert [mark["hasDownload"] for mark in marks] == [True, False, True, True]
    assert [mark["hasUpload"] for mark in marks] == [False, True, False, False]
    assert marks[1]["uploadY"] == rendered["baselineY"]
    assert marks[3]["downloadY"] == rendered["baselineY"]

    speed_colors = {rendered["colors"]["download"], rendered["colors"]["upload"]}
    speed_strokes = [
        operation for operation in rendered["operations"]
        if operation["kind"] == "stroke" and operation["strokeStyle"] in speed_colors
    ]
    speed_lines = [
        part for operation in speed_strokes for part in operation["path"] if part["kind"] == "lineTo"
    ]
    assert len(speed_lines) == 4
    assert all(part["args"][1] <= rendered["baselineY"] + 0.01 for part in speed_lines)

    tooltip_text = _hover_correlation_timestamp(page, payload[1]["timestamp"]).inner_text()
    assert "Download:" not in tooltip_text
    assert "Upload: 0.0 Mbps" in tooltip_text
    assert "Ping: 0.0 ms" in tooltip_text
    assert "Jitter:" not in tooltip_text
    assert "Packet Loss:" not in tooltip_text


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
    page.locator('#corr-event-popover input[data-event-type="health_change"]:not([data-event-severity])').evaluate(
        """
        (checkbox) => {
            checkbox.checked = false;
            checkbox.dispatchEvent(new Event('change', { bubbles: true }));
        }
        """
    )

    expect(event_rows).to_have_count(0)
    expect(page.locator("#correlation-legend .corr-legend-events")).to_contain_text("(0/2)")


def test_correlation_event_filter_popover_stays_above_unified_timeline(demo_page):
    page = demo_page
    _route_sample_correlation(page)
    _open_correlation(page)

    page.locator("#correlation-legend .corr-event-filter-btn").click()
    popover = page.locator("#corr-event-popover")
    expect(popover).to_be_visible()

    layering = popover.evaluate(
        """
        (node) => {
            const rect = node.getBoundingClientRect();
            const samples = [
                [rect.left + Math.min(rect.width - 2, Math.max(2, rect.width * 0.5)), rect.bottom - 2],
                [rect.left + Math.min(rect.width - 2, Math.max(2, rect.width * 0.2)), rect.bottom - 10],
                [rect.left + Math.min(rect.width - 2, Math.max(2, rect.width * 0.8)), rect.bottom - 10],
            ];
            const blockers = samples
                .map(([x, y]) => document.elementFromPoint(x, y))
                .filter((el) => el && !node.contains(el));
            const tableCard = document.querySelector('#correlation-table-card');
            const tableRect = tableCard.getBoundingClientRect();
            return {
                blockers: blockers.map((el) => ({
                    id: el.id,
                    tag: el.tagName,
                    className: typeof el.className === 'string' ? el.className : '',
                    text: (el.textContent || '').trim().slice(0, 60),
                })),
                overlapsTable: rect.bottom > tableRect.top,
                popoverBottom: rect.bottom,
                tableTop: tableRect.top,
                popoverParentTag: node.parentElement && node.parentElement.tagName,
            };
        }
        """
    )

    assert layering["overlapsTable"]
    assert layering["popoverParentTag"] == "BODY"
    assert layering["blockers"] == []


def test_correlation_event_severity_filter_updates_chart_and_table_in_browser(demo_page):
    page = demo_page
    _route_correlation(page, _sample_correlation_severity_data())
    _open_correlation(page)

    event_rows = page.locator('#correlation-tbody tr[data-src="event"]')
    expect(event_rows).to_have_count(3)
    expect(event_rows).to_contain_text(["Informational SNR movement", "Health critical", "Health warning"])

    page.locator("#correlation-legend .corr-event-filter-btn").click()
    expect(page.locator('#corr-event-popover input[data-event-severity="info"]')).to_have_count(2)
    page.locator('#corr-event-popover input[data-event-type="snr_change"][data-event-severity="info"]').evaluate(
        """
        (checkbox) => {
            checkbox.checked = false;
            checkbox.dispatchEvent(new Event('change', { bubbles: true }));
        }
        """
    )

    expect(event_rows).to_have_count(2)
    row_text = "\n".join(event_rows.all_text_contents())
    assert "Informational SNR movement" not in row_text
    assert "Health critical" in row_text
    assert "Health warning" in row_text
    visible_markers = page.locator("#correlation-legend .corr-legend-events").evaluate("(node) => node.textContent")
    assert "2/3" in visible_markers


def test_correlation_event_severity_normalizes_edge_cases_and_escapes_filter_attributes(demo_page):
    page = demo_page
    malicious_type = 'custom" data-owned="1'
    _route_correlation(page, _sample_correlation_severity_edge_data())
    _open_correlation(page)

    event_rows = page.locator('#correlation-tbody tr[data-src="event"]')
    expect(event_rows).to_have_count(2)
    row_text = "\n".join(event_rows.all_text_contents())
    assert "Info" in row_text
    assert "undefined" not in row_text
    assert "debug" not in row_text

    page.locator("#correlation-legend .corr-event-filter-btn").click()
    expect(page.locator("#corr-event-popover input[data-owned]")).to_have_count(0)
    popover_event_types = page.locator("#corr-event-popover input[data-event-type]").evaluate_all(
        "(inputs) => inputs.map((input) => input.dataset.eventType)"
    )
    assert malicious_type in popover_event_types

    page.evaluate(
        """
        (eventType) => {
            const checkbox = [...document.querySelectorAll('#corr-event-popover input[data-event-severity="info"]')]
                .find((input) => input.dataset.eventType === eventType);
            if (!checkbox) throw new Error('Expected malicious event type info checkbox');
            checkbox.checked = false;
            checkbox.dispatchEvent(new Event('change', { bubbles: true }));
        }
        """,
        malicious_type,
    )

    expect(event_rows).to_have_count(1)
    remaining_text = "\n".join(event_rows.all_text_contents())
    assert "Missing severity stays filterable" not in remaining_text
    assert "Unknown severity falls back to info" in remaining_text


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
