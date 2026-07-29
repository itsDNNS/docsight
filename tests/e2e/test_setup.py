"""E2E tests for the demo-first setup experience and modem wizard."""

import os
import pytest
from playwright.sync_api import expect


SCREENSHOT_DIR = os.path.join(os.path.dirname(__file__), "screenshots", "setup")


@pytest.fixture(autouse=True, scope="module")
def ensure_screenshot_dir():
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)


def _start_fresh(page):
    """Open the modem wizard and wait for its form."""
    page.locator("#connect-modem-btn").click()
    expect(page.locator("#setup-form")).to_be_visible()


def _click_next(page):
    """Click the visible 'Next' button within the active step."""
    page.locator(".step-content.active button.btn-primary", has_text="Next").click()


def _click_back(page):
    """Click the visible 'Back' button within the active step."""
    page.locator(".step-content.active button.btn-ghost", has_text="Back").click()


class TestSetupPageLoad:
    """Setup page renders with Tribu Design System elements."""

    def test_redirects_to_setup(self, setup_page):
        assert "/setup" in setup_page.url

    def test_has_mesh_background(self, setup_page):
        mesh = setup_page.locator(".mesh-bg")
        assert mesh.count() == 1

    def test_has_glass_cards(self, setup_page):
        glass = setup_page.locator(".glass")
        assert glass.count() >= 1

    def test_lucide_icons_render(self, setup_page):
        svgs = setup_page.locator(".first-run-card svg")
        assert svgs.count() >= 2

    def test_setup_title_visible(self, setup_page):
        title = setup_page.locator(".setup-title")
        assert title.is_visible()


class TestSetupStartHierarchy:
    """The local demo is the positive path; connection and restore remain available."""

    def test_demo_is_primary_and_full_width(self, setup_page):
        card = setup_page.locator(".first-run-card")
        demo = setup_page.locator("#start-demo-btn")
        connect = setup_page.locator("#connect-modem-btn")
        restore = setup_page.locator("#restore-action")

        expect(card).to_be_visible()
        expect(demo).to_be_visible()
        expect(connect).to_be_visible()
        expect(restore).to_be_visible()
        assert abs(demo.bounding_box()["width"] - card.bounding_box()["width"]) < 60
        assert demo.bounding_box()["y"] < connect.bounding_box()["y"] < restore.bounding_box()["y"]

    def test_click_connect_modem_shows_stepper(self, setup_page):
        setup_page.locator("#connect-modem-btn").click()
        stepper = setup_page.locator(".setup-stepper")
        expect(stepper).to_be_visible()

    def test_click_restore_shows_restore_section(self, setup_page):
        setup_page.locator("#restore-action").click()
        restore = setup_page.locator("#restore-section")
        expect(restore).to_be_visible()


class TestSetupWizardFlow:
    """Step-by-step wizard navigation."""

    def test_step1_to_step2(self, setup_page):
        _start_fresh(setup_page)
        step1 = setup_page.locator(".step-content[data-step='1']")
        expect(step1).to_be_visible()
        _click_next(setup_page)
        step2 = setup_page.locator(".step-content[data-step='2']")
        expect(step2).to_be_visible()

    def test_step2_back_to_step1(self, setup_page):
        _start_fresh(setup_page)
        _click_next(setup_page)
        expect(setup_page.locator(".step-content[data-step='2']")).to_be_visible()
        _click_back(setup_page)
        step1 = setup_page.locator(".step-content[data-step='1']")
        expect(step1).to_be_visible()

    def test_step3_review_populates(self, setup_page):
        _start_fresh(setup_page)
        _click_next(setup_page)
        expect(setup_page.locator(".step-content[data-step='2']")).to_be_visible()
        _click_next(setup_page)
        expect(setup_page.locator(".step-content[data-step='3']")).to_be_visible()
        review_tz = setup_page.locator("#review-tz")
        assert review_tz.text_content() != ""


class TestSetupRestore:
    """Restore flow."""

    def test_restore_file_input_visible(self, setup_page):
        setup_page.locator("#restore-action").click()
        file_input = setup_page.locator("#restore-file")
        expect(file_input).to_be_visible()

    def test_restore_back_to_start(self, setup_page):
        setup_page.locator("#restore-action").click()
        expect(setup_page.locator("#restore-section")).to_be_visible()
        setup_page.locator("#restore-section button.btn-ghost", has_text="Back").click()
        start = setup_page.locator("#setup-start")
        expect(start).to_be_visible()


class TestSetupThemeToggle:
    """Theme toggle on setup page."""

    def test_default_theme_dark(self, setup_page):
        theme = setup_page.locator("html").get_attribute("data-theme")
        assert theme == "dark"

    def test_toggle_to_light(self, setup_page):
        setup_page.locator("button", has_text="Theme").click()
        theme = setup_page.locator("html").get_attribute("data-theme")
        assert theme == "light"

    def test_toggle_back_to_dark(self, setup_page):
        setup_page.locator("button", has_text="Theme").click()  # -> light
        setup_page.locator("button", has_text="Theme").click()  # -> dark
        theme = setup_page.locator("html").get_attribute("data-theme")
        assert theme == "dark"


class TestSetupResponsive:
    """Desktop and mobile first-run layouts stay dense and error-free."""

    @pytest.mark.parametrize(
        ("width", "height", "screenshot_name"),
        ((1280, 800, "first_run_desktop.png"), (375, 812, "first_run_mobile.png")),
    )
    def test_first_run_has_no_overflow_or_browser_errors(
        self, page, setup_server, width, height, screenshot_name
    ):
        console_errors = []
        page_errors = []
        page.on(
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error"
            else None,
        )
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.set_viewport_size({"width": width, "height": height})
        page.goto(setup_server)
        page.wait_for_load_state("networkidle")
        page.screenshot(
            path=os.path.join(SCREENSHOT_DIR, screenshot_name),
            full_page=False,
        )

        overflow = page.evaluate(
            "document.documentElement.scrollWidth - window.innerWidth"
        )
        assert overflow <= 1
        assert console_errors == []
        assert page_errors == []


class TestSetupRecovery:
    def test_modem_failure_offers_retry_and_demo_fallback(self, page, setup_server):
        page.route(
            "**/api/demo/start",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body='{"success": true, "demo_mode": true, "status": "active"}',
            ),
        )
        page.route(
            "**/health",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body='{"status":"ok","docsis_health":"waiting"}',
            ),
        )
        page.route(
            "**/api/test-modem",
            lambda route: route.fulfill(
                status=502,
                content_type="application/json",
                body='{"success": false, "error": "Modem unavailable"}',
            ),
        )
        page.goto(setup_server)
        _start_fresh(page)
        page.locator("#test-conn-btn").click()

        result = page.locator("#test-result")
        retry = result.get_by_role("button", name="Try again")
        demo = result.get_by_role("button", name="Try the demo instead")
        expect(retry).to_be_visible()
        expect(demo).to_be_visible()

        demo.click()
        expect(page.locator(".first-run-card")).to_be_visible()
        expect(page.locator("#setup-form")).to_be_hidden()
        expect(page.locator("#start-demo-btn")).to_contain_text(
            "Preparing the populated dashboard"
        )

    def test_final_save_failure_offers_retry_and_demo_fallback(self, page, setup_server):
        page.route(
            "**/api/config",
            lambda route: route.fulfill(
                status=500,
                content_type="application/json",
                body='{"success": false}',
            ),
        )
        page.goto(setup_server)
        _start_fresh(page)
        _click_next(page)
        _click_next(page)
        page.locator("#submit-btn").click()

        result = page.locator("#setup-submit-result")
        expect(result.get_by_role("button", name="Try again")).to_be_visible()
        expect(result.get_by_role("button", name="Try the demo instead")).to_be_visible()


class TestOneClickDemo:
    def test_one_click_reaches_populated_dashboard_with_banner(
        self, page, first_run_server
    ):
        console_errors = []
        page_errors = []
        page.on(
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error"
            else None,
        )
        page.on("pageerror", lambda error: page_errors.append(str(error)))

        page.goto(first_run_server)
        expect(page.locator("#start-demo-btn")).to_be_visible()
        page.locator("#start-demo-btn").click()

        page.wait_for_url(first_run_server + "/", timeout=60_000)
        banner = page.locator(".demo-banner")
        expect(banner).to_be_visible()
        expect(banner.get_by_role("button", name="Connect own modem")).to_be_visible()
        expect(banner.get_by_role("button", name="Exit demo")).to_be_visible()
        expect(page.locator(".hero-card")).to_be_visible()
        expect(page.locator(".hero-meta-item .badge", has_text="DEMO")).to_be_visible()
        page.screenshot(path=os.path.join(SCREENSHOT_DIR, "demo_dashboard_desktop.png"))

        page.set_viewport_size({"width": 375, "height": 812})
        page.goto("about:blank")
        console_errors.clear()
        page_errors.clear()
        page.goto(first_run_server, wait_until="networkidle")
        banner = page.locator(".demo-banner")
        expect(banner.get_by_role("button", name="Connect own modem")).to_be_visible()
        expect(banner.get_by_role("button", name="Exit demo")).to_be_visible()
        overflow = page.evaluate(
            "document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
        assert overflow <= 1
        page.screenshot(path=os.path.join(SCREENSHOT_DIR, "demo_dashboard_mobile.png"))
        assert console_errors == []
        assert page_errors == []

    @pytest.mark.parametrize(
        ("action_name", "target_suffix", "visible_selector"),
        (
            ("Connect own modem", "/setup?connect=1", "#setup-form"),
            ("Exit demo", "/setup", ".first-run-card"),
        ),
    )
    def test_banner_actions_leave_demo_through_production_runtime(
        self, page, first_run_server, action_name, target_suffix, visible_selector
    ):
        page.goto(first_run_server)
        page.locator("#start-demo-btn").click()
        page.wait_for_url(first_run_server + "/", timeout=60_000)

        page.get_by_role("button", name=action_name).click()
        confirm_modal = page.locator("#docsight-confirm-modal")
        expect(confirm_modal).to_be_visible()
        expect(page.locator("#docsight-confirm-message")).to_contain_text(
            "delete all demo data"
        )
        page.locator("#docsight-confirm-cancel").click()
        expect(confirm_modal).to_be_hidden()
        expect(page.locator(".demo-banner")).to_be_visible()

        page.get_by_role("button", name=action_name).click()
        expect(confirm_modal).to_be_visible()
        page.locator("#docsight-confirm-ok").click()
        page.wait_for_url(first_run_server + target_suffix, timeout=30_000)
        expect(page.locator(visible_selector)).to_be_visible()
        expect(page.locator(".demo-banner")).to_have_count(0)

    def test_retry_after_acceptance_does_not_repeat_start_mutation(
        self, page, first_run_server
    ):
        start_requests = []
        page.on(
            "request",
            lambda request: start_requests.append(request.url)
            if request.url.endswith("/api/demo/start")
            else None,
        )
        page.route(
            "**/health",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body='{"status":"ok","docsis_health":"waiting"}',
            ),
        )
        page.goto(first_run_server + "/setup")
        page.locator("#start-demo-btn").click()
        expect(page.locator("#start-demo-btn")).to_contain_text(
            "Preparing the populated dashboard"
        )

        page.evaluate("demoWaitDeadline = Date.now() - 1; waitForDemoData(false)")
        retry = page.locator("#demo-start-result").get_by_role(
            "button", name="Try again"
        )
        expect(retry).to_be_visible()
        retry.click()
        page.wait_for_timeout(750)

        assert len(start_requests) == 1
