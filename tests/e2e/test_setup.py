"""E2E coverage for the value-led first-run experience."""

import re
import sqlite3
import tempfile
from pathlib import Path

import pytest
from playwright.sync_api import expect


SCREENSHOT_DIR = Path(tempfile.gettempdir()) / "docsight-first-run-screenshots"


def _start_modem_setup(page):
    page.locator("#connect-modem-btn").click()
    expect(page.locator("#setup-form")).to_be_visible()


def _click_next(page):
    page.locator(".step-content.active button.btn-primary", has_text="Next").click()


def _assert_no_horizontal_overflow(page):
    geometry = page.evaluate(
        """() => ({
            viewport: window.innerWidth,
            document: document.documentElement.scrollWidth,
            body: document.body.scrollWidth
        })"""
    )
    assert geometry["document"] <= geometry["viewport"] + 1
    assert geometry["body"] <= geometry["viewport"] + 1


def _assert_populated_demo_dashboard(page, server):
    page.wait_for_url(f"{server}/", timeout=60_000)
    expect(page.locator(".hero-card")).to_be_visible()
    expect(page.locator(".hero-health-card")).to_have_count(2)
    expect(page.locator(".demo-mode-banner")).to_be_visible()
    runtime = page.request.get(f"{server}/__runtime-status")
    assert runtime.ok
    runtime_state = runtime.json()
    assert runtime_state["running"] is True
    assert "demo" in runtime_state["collectors"]


class TestFirstRunValueChoice:
    def test_value_hierarchy_and_semantic_actions(self, setup_page):
        expect(setup_page.locator(".first-run-card")).to_be_visible()
        expect(setup_page.locator("#start-demo-btn")).to_be_visible()
        expect(setup_page.locator("#connect-modem-btn")).to_be_visible()
        expect(setup_page.locator("#restore-backup-btn")).to_be_visible()
        expect(setup_page.locator(".desktop-preview-first-run")).to_have_count(0)
        expect(setup_page.locator(".choice-grid")).to_have_count(0)
        alternatives = setup_page.get_by_role(
            "group", name="Other first-run options"
        )
        expect(alternatives).to_be_visible()
        expect(alternatives.get_by_role("button")).to_have_count(2)

        boxes = [
            setup_page.locator(selector).bounding_box()
            for selector in ("#start-demo-btn", "#connect-modem-btn", "#restore-backup-btn")
        ]
        assert all(box is not None for box in boxes)
        assert boxes[0]["y"] < boxes[1]["y"]
        assert boxes[0]["y"] < boxes[2]["y"]
        assert abs(boxes[1]["y"] - boxes[2]["y"]) < 2
        assert boxes[1]["x"] < boxes[2]["x"]
        assert setup_page.locator("#start-demo-btn").evaluate("el => el.tagName") == "BUTTON"
        assert setup_page.locator("#connect-modem-btn").evaluate("el => el.tagName") == "BUTTON"
        assert setup_page.locator("#restore-backup-btn").evaluate("el => el.tagName") == "BUTTON"
        assert setup_page.locator("#connect-modem-btn").evaluate(
            "el => el.classList.contains('btn-ghost')"
        )
        assert setup_page.locator("#restore-backup-btn").evaluate(
            "el => el.classList.contains('setup-text-action')"
        )

    def test_desktop_preview_hint_is_only_in_explicit_desktop_mode(
        self, desktop_setup_page
    ):
        expect(
            desktop_setup_page.locator(".desktop-preview-first-run")
        ).to_be_visible()

    def test_secondary_action_opens_modem_wizard(self, setup_page):
        _start_modem_setup(setup_page)
        expect(setup_page.locator(".setup-stepper")).to_be_visible()
        expect(setup_page.locator(".step-content[data-step='1']")).to_be_visible()

    def test_tertiary_action_opens_restore(self, setup_page):
        setup_page.locator("#restore-backup-btn").click()
        expect(setup_page.locator("#restore-section")).to_be_visible()
        expect(setup_page.locator("#restore-file")).to_be_visible()

    def test_connect_query_opens_modem_wizard(self, page, setup_server):
        page.goto(f"{setup_server}/setup?connect=1")
        expect(page.locator("#setup-form")).to_be_visible()
        expect(page.locator(".step-content[data-step='1']")).to_be_visible()


class TestSetupWizardFlow:
    def test_step_navigation_and_review(self, setup_page):
        _start_modem_setup(setup_page)
        _click_next(setup_page)
        expect(setup_page.locator(".step-content[data-step='2']")).to_be_visible()
        _click_next(setup_page)
        expect(setup_page.locator(".step-content[data-step='3']")).to_be_visible()
        assert setup_page.locator("#review-tz").text_content()
        setup_page.locator(".step-content.active button.btn-ghost", has_text="Back").click()
        expect(setup_page.locator(".step-content[data-step='2']")).to_be_visible()

    def test_restore_back_returns_to_value_choice(self, setup_page):
        setup_page.locator("#restore-backup-btn").click()
        setup_page.locator("#restore-section button.btn-ghost", has_text="Back").click()
        expect(setup_page.locator("#setup-start")).to_be_visible()


class TestFirstRunDeadEnds:
    def test_connection_failure_and_network_exception_offer_retry_and_demo(
        self, page, first_run_server
    ):
        page.goto(first_run_server)
        expect(page.locator("#start-demo-btn")).to_be_visible()
        _start_modem_setup(page)
        page.route(
            "**/api/test-modem",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body='{"success": false, "error": "Connection refused"}',
            ),
        )
        page.locator("#test-conn-btn").click()
        recovery = page.locator("#test-connection-recovery")
        expect(recovery).to_be_visible()
        expect(recovery.get_by_text("Retry connection")).to_be_visible()
        expect(recovery.get_by_text("View demo instead")).to_be_visible()

        page.unroute("**/api/test-modem")
        page.route("**/api/test-modem", lambda route: route.abort())
        recovery.get_by_text("Retry connection").click()
        expect(recovery).to_be_visible()
        expect(page.locator("#test-result")).to_contain_text("Network error")

        recovery.get_by_text("View demo instead").click()
        _assert_populated_demo_dashboard(page, first_run_server)


class TestDemoReadinessRetry:
    def test_readiness_timeout_retry_does_not_post_or_restart_twice(
        self,
        page,
        first_run_server,
    ):
        post_count = 0
        health_ready = False

        def count_start(route):
            nonlocal post_count
            post_count += 1
            route.continue_()

        def control_health(route):
            if health_ready:
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body='{"docsis_health": "good"}',
                )
                return
            route.fulfill(
                status=200,
                content_type="application/json",
                body='{"docsis_health": "waiting"}',
            )

        page.goto(first_run_server)
        page.route("**/api/demo/start", count_start)
        page.route("**/health", control_health)
        page.locator("#start-demo-btn").evaluate(
            "button => button.dataset.demoReadyTimeoutMs = '25'"
        )

        page.locator("#start-demo-btn").click()
        status = page.locator("#demo-start-status")
        expect(status).to_have_class(re.compile(r"\berror\b"), timeout=10_000)
        expect(page.locator("#start-demo-btn")).to_be_enabled()

        page.wait_for_function(
            """async () => {
                const response = await fetch(
                    '/__runtime-status',
                    {cache: 'no-store'}
                );
                return response.ok && (await response.json()).demo_ready;
            }""",
            timeout=30_000,
        )
        runtime_before = page.request.get(
            f"{first_run_server}/__runtime-status"
        ).json()
        assert post_count == 1
        assert runtime_before["running"] is True
        assert runtime_before["poll_attempt"] is not None

        health_ready = True
        page.locator("#start-demo-btn").click()
        page.wait_for_url(f"{first_run_server}/", timeout=30_000)

        runtime_after = page.request.get(
            f"{first_run_server}/__runtime-status"
        ).json()
        assert post_count == 1
        assert runtime_after["generation"] == runtime_before["generation"]
        assert runtime_after["poll_attempt"] == runtime_before["poll_attempt"]
        assert runtime_after["running"] is True

    def test_health_502_retry_only_rechecks_same_runtime_attempt(
        self,
        page,
        first_run_server,
    ):
        post_count = 0
        health_ready = False

        def count_start(route):
            nonlocal post_count
            post_count += 1
            route.continue_()

        def control_health(route):
            if health_ready:
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body='{"docsis_health": "good"}',
                )
                return
            route.fulfill(
                status=502,
                content_type="application/json",
                body='{"error": "temporary"}',
            )

        page.goto(first_run_server)
        page.route("**/api/demo/start", count_start)
        page.route("**/health", control_health)
        page.locator("#start-demo-btn").evaluate(
            "button => button.dataset.demoReadyTimeoutMs = '25'"
        )

        page.locator("#start-demo-btn").click()
        expect(page.locator("#demo-start-status")).to_have_class(
            re.compile(r"\berror\b"),
            timeout=10_000,
        )
        expect(page.locator("#start-demo-btn")).to_be_enabled()

        page.wait_for_function(
            """async () => {
                const response = await fetch(
                    '/__runtime-status',
                    {cache: 'no-store'}
                );
                return response.ok && (await response.json()).demo_ready;
            }""",
            timeout=30_000,
        )
        runtime_before = page.request.get(
            f"{first_run_server}/__runtime-status"
        ).json()
        assert post_count == 1
        assert runtime_before["poll_attempt"] is not None

        health_ready = True
        page.locator("#start-demo-btn").click()
        page.wait_for_url(f"{first_run_server}/", timeout=30_000)

        runtime_after = page.request.get(
            f"{first_run_server}/__runtime-status"
        ).json()
        assert post_count == 1
        assert runtime_after["generation"] == runtime_before["generation"]
        assert runtime_after["poll_attempt"] == runtime_before["poll_attempt"]
        assert runtime_after["running"] is True

    def test_post_failure_retry_may_post_again(
        self,
        page,
        first_run_server,
    ):
        post_count = 0

        def fail_once(route):
            nonlocal post_count
            post_count += 1
            if post_count == 1:
                route.fulfill(
                    status=503,
                    content_type="application/json",
                    body='{"success": false, "error": "temporary"}',
                )
                return
            route.continue_()

        page.goto(first_run_server)
        page.route("**/api/demo/start", fail_once)

        page.locator("#start-demo-btn").click()
        expect(page.locator("#demo-start-status")).to_have_class(
            re.compile(r"\berror\b")
        )
        expect(page.locator("#start-demo-btn")).to_be_enabled()
        assert post_count == 1

        page.locator("#start-demo-btn").click()
        page.wait_for_url(f"{first_run_server}/", timeout=60_000)

        assert post_count == 2
        _assert_populated_demo_dashboard(page, first_run_server)


def test_fresh_data_dir_demo_post_creates_and_seeds_all_module_storages(
    page,
    first_run_instance,
):
    server = first_run_instance["url"]
    data_dir = Path(first_run_instance["data_dir"])
    post_count = 0

    def count_start(route):
        nonlocal post_count
        post_count += 1
        route.continue_()

    page.goto(server)
    page.route("**/api/demo/start", count_start)
    page.locator("#start-demo-btn").click()
    page.wait_for_url(f"{server}/", timeout=60_000)
    assert post_count == 1

    health = page.request.get(f"{server}/health")
    assert health.ok
    assert health.json()["docsis_health"] != "waiting"

    runtime = page.request.get(f"{server}/__runtime-status")
    assert runtime.ok
    runtime_state = runtime.json()
    assert runtime_state["collectors"] == ["demo"]
    assert runtime_state["poll_attempt"] is not None

    core_db = data_dir / "docsis_history.db"
    assert core_db.exists()
    expected_tables = {
        "speedtest_results",
        "bqm_graphs",
        "bnetz_measurements",
        "weather_data",
        "journal_entries",
        "incidents",
    }
    with sqlite3.connect(core_db) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert expected_tables <= tables
        core_counts = {
            "speedtest": conn.execute(
                "SELECT COUNT(*) FROM speedtest_results WHERE is_demo = 1"
            ).fetchone()[0],
            "bqm": conn.execute(
                "SELECT COUNT(*) FROM bqm_graphs WHERE is_demo = 1"
            ).fetchone()[0],
            "bnetza": conn.execute(
                "SELECT COUNT(*) FROM bnetz_measurements WHERE is_demo = 1"
            ).fetchone()[0],
        }
    assert all(count > 0 for count in core_counts.values()), core_counts

    connection_db = data_dir / "connection_monitor.db"
    assert connection_db.exists()
    with sqlite3.connect(connection_db) as conn:
        connection_counts = {
            "targets": conn.execute(
                "SELECT COUNT(*) FROM connection_targets WHERE is_demo = 1"
            ).fetchone()[0],
            "samples": conn.execute(
                "SELECT COUNT(*) FROM connection_samples AS samples "
                "JOIN connection_targets AS targets "
                "ON targets.id = samples.target_id "
                "WHERE targets.is_demo = 1"
            ).fetchone()[0],
        }
    assert all(count > 0 for count in connection_counts.values()), connection_counts


class TestFirstRunSaveDeadEnd:
    def test_setup_save_api_failure_offers_retry_and_demo(
        self, page, first_run_server
    ):
        page.goto(first_run_server)
        expect(page.locator("#start-demo-btn")).to_be_visible()
        _start_modem_setup(page)
        _click_next(page)
        _click_next(page)
        page.route(
            "**/api/config",
            lambda route: route.fulfill(
                status=500,
                content_type="application/json",
                body='{"success": false, "error": "Save failed"}',
            ),
        )
        page.locator("#submit-btn").click()

        recovery = page.locator("#setup-submit-recovery")
        expect(recovery).to_be_visible()
        expect(recovery.get_by_text("Retry setup")).to_be_visible()
        expect(recovery.get_by_text("View demo instead")).to_be_visible()

        recovery.get_by_text("View demo instead").click()
        _assert_populated_demo_dashboard(page, first_run_server)


class TestSetupTheme:
    def test_theme_toggle_round_trip(self, setup_page):
        assert setup_page.locator("html").get_attribute("data-theme") == "dark"
        setup_page.get_by_role("button", name="Theme").click()
        assert setup_page.locator("html").get_attribute("data-theme") == "light"
        setup_page.get_by_role("button", name="Theme").click()
        assert setup_page.locator("html").get_attribute("data-theme") == "dark"


@pytest.mark.parametrize(("width", "height"), [(1280, 800), (375, 760)])
def test_first_run_actions_have_real_44px_touch_targets(
    page, setup_server, width, height
):
    page.set_viewport_size({"width": width, "height": height})
    page.goto(setup_server)

    for selector in (
        "#start-demo-btn",
        "#connect-modem-btn",
        "#restore-backup-btn",
    ):
        box = page.locator(selector).bounding_box()
        assert box is not None
        assert box["width"] >= 44, (selector, width, box)
        assert box["height"] >= 44 - 0.01, (selector, width, box)


@pytest.mark.parametrize(
    ("width", "height", "banner_action", "expected_query"),
    [
        (1280, 800, "connect", "connect=1"),
        (375, 760, "exit", None),
    ],
)
def test_one_click_demo_populates_dashboard_and_banner_actions_work(
    page, first_run_server, width, height, banner_action, expected_query
):
    errors = []
    page.on(
        "console",
        lambda message: errors.append(f"console: {message.text}")
        if message.type == "error"
        else None,
    )
    page.on("pageerror", lambda error: errors.append(f"page: {error}"))
    page.set_viewport_size({"width": width, "height": height})
    page.goto(first_run_server)

    expect(page.locator("#start-demo-btn")).to_be_visible()
    _assert_no_horizontal_overflow(page)
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    page.screenshot(
        path=str(SCREENSHOT_DIR / f"first-run-{width}.png"),
        full_page=True,
    )

    page.locator("#start-demo-btn").click()
    expect(page.locator("#demo-start-status")).to_be_visible()
    page.wait_for_url(f"{first_run_server}/", timeout=60_000)

    _assert_populated_demo_dashboard(page, first_run_server)
    expect(page.locator(".demo-mode-banner")).to_be_visible()
    expect(page.locator('[data-demo-action="connect"]')).to_be_visible()
    expect(page.locator('[data-demo-action="exit"]')).to_be_visible()
    for selector in (
        '[data-demo-action="connect"]',
        '[data-demo-action="exit"]',
    ):
        box = page.locator(selector).bounding_box()
        assert box is not None
        assert box["width"] >= 44, (selector, width, box)
        assert box["height"] >= 44, (selector, width, box)
    _assert_no_horizontal_overflow(page)
    page.screenshot(
        path=str(SCREENSHOT_DIR / f"demo-dashboard-{width}.png"),
        full_page=True,
    )
    assert errors == []

    page.locator(f'[data-demo-action="{banner_action}"]').click()
    expected_url = (
        f"{first_run_server}/setup?connect=1"
        if expected_query
        else f"{first_run_server}/setup"
    )
    page.wait_for_url(re.compile(f"^{re.escape(expected_url)}$"), timeout=30_000)
    assert page.url == expected_url
    if banner_action == "connect":
        expect(page.locator("#setup-form")).to_be_visible()
    else:
        expect(page.locator("#setup-start")).to_be_visible()
    page.wait_for_function(
        """async url => {
            const response = await fetch(url + '/__runtime-status', {cache: 'no-store'});
            if (!response.ok) return false;
            const state = await response.json();
            return state.running === false && state.collectors.length === 0;
        }""",
        arg=first_run_server,
        timeout=30_000,
    )
    stopped = page.request.get(f"{first_run_server}/__runtime-status")
    assert stopped.ok
    stopped_state = stopped.json()
    assert stopped_state["running"] is False
    assert stopped_state["collectors"] == []
    assert stopped_state["poll_attributed"] is False
    _assert_no_horizontal_overflow(page)


def test_mobile_settings_drawer_and_backdrop_layer_above_demo_banner(
    page,
    first_run_server,
):
    page.set_viewport_size({"width": 375, "height": 760})
    page.goto(first_run_server)
    page.locator("#start-demo-btn").click()
    page.wait_for_url(f"{first_run_server}/", timeout=60_000)
    expect(page.locator(".demo-mode-banner")).to_be_visible()

    page.goto(f"{first_run_server}/settings")
    banner = page.locator(".demo-mode-banner")
    expect(banner).to_be_visible()
    page.locator("#mobile-menu-button").click()
    expect(page.locator("#settings-sidebar")).to_have_class(
        re.compile(r"\bopen\b")
    )
    expect(page.locator("#sidebar-backdrop")).to_have_class(
        re.compile(r"\bactive\b")
    )
    page.wait_for_function(
        """() => {
            const sidebar = document.querySelector('#settings-sidebar');
            return sidebar && Math.abs(sidebar.getBoundingClientRect().left) < 1;
        }"""
    )

    layers = page.evaluate(
        """() => {
            const banner = document.querySelector('.demo-mode-banner');
            const sidebar = document.querySelector('#settings-sidebar');
            const bannerBox = banner.getBoundingClientRect();
            const sidebarBox = sidebar.getBoundingClientRect();
            const y = bannerBox.top + Math.min(20, bannerBox.height / 2);
            const sidebarHit = document.elementFromPoint(
                Math.max(1, sidebarBox.left + 20),
                y
            );
            const backdropHit = document.elementFromPoint(
                Math.min(window.innerWidth - 2, sidebarBox.right + 20),
                y
            );
            return {
                sidebar: Boolean(
                    sidebarHit && sidebarHit.closest('#settings-sidebar')
                ),
                backdrop: Boolean(
                    backdropHit && backdropHit.closest('#sidebar-backdrop')
                ),
                sidebarTag: sidebarHit && sidebarHit.tagName,
                backdropTag: backdropHit && backdropHit.tagName
            };
        }"""
    )
    assert layers["sidebar"], layers
    assert layers["backdrop"], layers
