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


def _choose_cable_modem(page, query, name):
    """Pick a cable modem through the searchable list."""
    page.locator('input[name="connection_kind"][value="cable"]').check()
    page.locator("#modem-search").fill(query)
    page.locator("#modem-options [role='option']", has_text=name).click()


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
        setup_page.locator('input[name="connection_kind"][value="other"]').check()
        _click_next(setup_page)
        step2 = setup_page.locator(".step-content[data-step='2']")
        expect(step2).to_be_visible()

    def test_step2_back_to_step1(self, setup_page):
        _start_fresh(setup_page)
        setup_page.locator('input[name="connection_kind"][value="other"]').check()
        _click_next(setup_page)
        expect(setup_page.locator(".step-content[data-step='2']")).to_be_visible()
        _click_back(setup_page)
        step1 = setup_page.locator(".step-content[data-step='1']")
        expect(step1).to_be_visible()

    def test_step3_review_populates(self, setup_page):
        _start_fresh(setup_page)
        _choose_cable_modem(setup_page, "fritz", "AVM FRITZ!Box")
        _click_next(setup_page)
        expect(setup_page.locator(".step-content[data-step='2']")).to_be_visible()
        _click_next(setup_page)
        expect(setup_page.locator(".step-content[data-step='3']")).to_be_visible()
        review_tz = setup_page.locator("#review-tz")
        assert review_tz.text_content() != ""
        expect(setup_page.locator("#review-modem-type")).to_have_text("AVM FRITZ!Box")


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
        _choose_cable_modem(page, "fritz", "AVM FRITZ!Box")
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
        page.locator('input[name="connection_kind"][value="other"]').check()
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
        expect(page.locator(".hero-card").first).to_be_visible()
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


class TestGuidedModemChoice:
    """Connection kind first, then a searchable modem list; time zone from the browser."""

    def test_next_requires_a_connection_kind_and_a_modem(self, setup_page):
        _start_fresh(setup_page)
        error = setup_page.locator("#step-1-error")
        expect(setup_page.locator("#modem-credentials-group")).to_be_hidden()
        _click_next(setup_page)
        expect(error).to_have_text("Choose your connection type.")
        expect(setup_page.locator(".step-content[data-step='1']")).to_be_visible()

        setup_page.locator('input[name="connection_kind"][value="cable"]').check()
        expect(error).to_be_hidden()
        _click_next(setup_page)
        expect(error).to_have_text("Choose your modem model.")
        expect(setup_page.locator("#modem-search")).to_be_focused()

    def test_fiber_and_dsl_reach_the_generic_router_without_the_modem_list(self, setup_page):
        _start_fresh(setup_page)
        setup_page.locator('input[name="connection_kind"][value="other"]').check()
        expect(setup_page.locator("#modem-picker")).to_be_hidden()
        expect(setup_page.locator("#generic-note")).to_be_visible()
        expect(setup_page.locator("#modem_type")).to_have_value("generic")
        expect(setup_page.locator("#modem-credentials-group")).to_be_hidden()
        _click_next(setup_page)
        _click_next(setup_page)
        expect(setup_page.locator("#review-modem-type")).to_have_text("Generic Router (No DOCSIS)")

        # Switching back to cable must not keep the generic driver.
        _click_back(setup_page)
        _click_back(setup_page)
        setup_page.locator('input[name="connection_kind"][value="cable"]').check()
        expect(setup_page.locator("#modem_type")).to_have_value("")

    def test_modem_list_is_grouped_and_searchable_by_keyboard(self, setup_page):
        _start_fresh(setup_page)
        setup_page.locator('input[name="connection_kind"][value="cable"]').check()
        options = setup_page.locator("#modem-options [role='option']")
        expect(setup_page.locator("#modem-options [role='option'][data-value='generic']")).to_have_count(0)
        expect(setup_page.locator("#modem-options .setup-modem-group-label").first).to_have_text("Arris")

        search = setup_page.locator("#modem-search")
        search.fill("virgin media")
        visible = setup_page.locator("#modem-options [role='option']:not([hidden])")
        expect(visible).to_have_count(1)
        expect(visible).to_contain_text("Virgin Media Hub 5")
        expect(setup_page.locator("#modem-options .setup-modem-group:not([hidden])")).to_have_count(1)

        search.press("ArrowDown")
        expect(search).to_have_attribute("aria-activedescendant", "modem-option-f3896lg")
        search.press("Enter")
        expect(setup_page.locator("#modem_type")).to_have_value("f3896lg")
        expect(setup_page.locator("#modem-option-f3896lg")).to_have_attribute("aria-selected", "true")
        expect(setup_page.locator("#modem_url")).to_have_value("https://192.168.100.1")

        search.fill("no such modem")
        expect(setup_page.locator("#modem-search-empty")).to_be_visible()
        search.press("Escape")
        expect(search).to_have_value("")
        assert options.count() == visible.count()

    def test_time_zone_is_prefilled_from_the_browser_and_validated(self, browser, setup_server):
        context = browser.new_context(timezone_id="America/Chicago")
        page = context.new_page()
        try:
            page.goto(setup_server)
            _start_fresh(page)
            page.locator('input[name="connection_kind"][value="other"]').check()
            _click_next(page)
            timezone = page.locator("#timezone")
            expect(timezone).to_have_value("America/Chicago")
            timezone.fill("Atlantis/Lost")
            _click_next(page)
            expect(page.locator("#step-2-error")).to_have_text("Choose a time zone from the list.")
            expect(page.locator(".step-content[data-step='2']")).to_be_visible()
            timezone.fill("Europe/Berlin")
            _click_next(page)
            expect(page.locator("#review-tz")).to_have_text("Europe/Berlin")
        finally:
            context.close()

    def test_submission_carries_the_driver_but_not_the_connection_kind(self, setup_page):
        posted = []

        def save(route):
            posted.append(route.request.post_data_json)
            route.fulfill(status=500, json={"error": "not saved in this test"})

        setup_page.route("**/api/config", save)
        _start_fresh(setup_page)
        setup_page.locator('input[name="connection_kind"][value="other"]').check()
        _click_next(setup_page)
        _click_next(setup_page)
        setup_page.locator("#submit-btn").click()
        expect(setup_page.locator("#setup-submit-result")).to_be_visible()
        assert posted and posted[0]["modem_type"] == "generic"
        assert "connection_kind" not in posted[0]


class TestModemDetection:
    """Local detection runs only on click and fills in model and address."""

    def _serve(self, page, devices):
        calls = []

        def detect(route):
            calls.append(route.request.method)
            route.fulfill(json={"devices": devices})

        page.route("**/api/setup/detect-modem", detect)
        return calls

    def test_nothing_is_probed_until_the_user_asks(self, setup_page):
        calls = self._serve(setup_page, [])
        _start_fresh(setup_page)
        setup_page.locator('input[name="connection_kind"][value="cable"]').check()
        expect(setup_page.locator("#detect-modem-btn")).to_be_visible()
        setup_page.wait_for_timeout(500)
        assert calls == []

        setup_page.locator("#detect-modem-btn").click()
        expect(setup_page.locator("#detect-modem-results")).to_contain_text("No device answered")
        assert calls == ["POST"]

    def test_a_recognized_modem_is_used_with_its_address(self, setup_page):
        self._serve(setup_page, [
            {"host": "192.168.178.1", "url": "http://192.168.178.1", "drivers": ["fritzbox"]},
            {"host": "10.0.0.1", "url": "https://10.0.0.1", "drivers": ["surfboard", "sb8200_cbn"]},
        ])
        _start_fresh(setup_page)
        setup_page.locator('input[name="connection_kind"][value="cable"]').check()
        setup_page.locator("#detect-modem-btn").click()
        results = setup_page.locator("#detect-modem-results")
        expect(results.locator(".setup-detect-device")).to_have_count(2)
        expect(results).to_contain_text("A device answers at http://192.168.178.1")

        results.get_by_role("button", name="Use: Arris SURFboard (S33/S34/SB8200)").click()
        expect(setup_page.locator("#modem_type")).to_have_value("surfboard")
        # The driver's scheme stays, the address is the one that answered.
        expect(setup_page.locator("#modem_url")).to_have_value("https://10.0.0.1")
        expect(setup_page.locator("#modem-option-surfboard")).to_have_attribute("aria-selected", "true")

        results.get_by_role("button", name="Use: AVM FRITZ!Box").click()
        expect(setup_page.locator("#modem_type")).to_have_value("fritzbox")
        expect(setup_page.locator("#modem_url")).to_have_value("http://192.168.178.1")

    def test_an_unknown_device_lends_its_address_to_the_chosen_model(self, setup_page):
        self._serve(setup_page, [{"host": "10.0.0.1", "url": "http://10.0.0.1", "drivers": []}])
        _start_fresh(setup_page)
        setup_page.locator('input[name="connection_kind"][value="cable"]').check()
        setup_page.locator("#detect-modem-btn").click()
        results = setup_page.locator("#detect-modem-results")
        expect(results).to_contain_text("The model was not recognized")
        results.get_by_role("button", name="Use this address").click()
        expect(setup_page.locator("#modem-search")).to_be_focused()

        setup_page.locator("#modem-search").fill("tc4400")
        setup_page.locator("#modem-search").press("Enter")
        expect(setup_page.locator("#modem_type")).to_have_value("tc4400")
        expect(setup_page.locator("#modem_url")).to_have_value("http://10.0.0.1")

    def test_a_failed_search_offers_a_retry(self, setup_page):
        setup_page.route("**/api/setup/detect-modem", lambda route: route.fulfill(status=500, body="down"))
        _start_fresh(setup_page)
        setup_page.locator('input[name="connection_kind"][value="cable"]').check()
        setup_page.locator("#detect-modem-btn").click()
        results = setup_page.locator("#detect-modem-results")
        expect(results.get_by_role("button", name="Try again")).to_be_visible()
        setup_page.unroute("**/api/setup/detect-modem")
        self._serve(setup_page, [])
        results.get_by_role("button", name="Try again").click()
        expect(results).to_contain_text("No device answered")
        expect(results).not_to_have_class("test-result error")


class TestConnectionDiagnosis:
    """A failed connection test names the likely cause and links to help."""

    @pytest.mark.parametrize("reason, text, help_page", [
        ("unreachable", "DOCSight cannot reach http://192.168.178.1.", "Bridge-Mode-Compatibility#modem-not-reachable"),
        ("auth", "rejected the login", "Supported-Modems"),
        ("unexpected", "cannot read its pages", "Requesting-Modem-Support"),
    ])
    def test_each_reason_has_its_message_and_help(self, setup_page, reason, text, help_page):
        help_url = "https://github.com/itsDNNS/docsight/wiki/" + help_page
        setup_page.route("**/api/test-modem", lambda route: route.fulfill(json={
            "success": False, "error": "Modem connection failed", "reason": reason, "help_url": help_url}))
        _start_fresh(setup_page)
        _choose_cable_modem(setup_page, "fritz", "AVM FRITZ!Box")
        setup_page.locator("#test-conn-btn").click()

        result = setup_page.locator("#test-result")
        expect(result).to_contain_text(text)
        link = result.get_by_role("link", name="How to fix this")
        expect(link).to_have_attribute("href", help_url)
        expect(link).to_have_attribute("target", "_blank")
        expect(result.get_by_role("button", name="Try again")).to_be_visible()

    def test_links_outside_the_wiki_are_not_shown(self, setup_page):
        setup_page.route("**/api/test-modem", lambda route: route.fulfill(json={
            "success": False, "error": "Modem connection failed", "reason": "auth",
            "help_url": "https://example.com/phish"}))
        _start_fresh(setup_page)
        _choose_cable_modem(setup_page, "fritz", "AVM FRITZ!Box")
        setup_page.locator("#test-conn-btn").click()
        result = setup_page.locator("#test-result")
        expect(result).to_contain_text("rejected the login")
        expect(result.get_by_role("link")).to_have_count(0)

    def test_a_closed_local_port_is_reported_as_unreachable(self, setup_page):
        _start_fresh(setup_page)
        _choose_cable_modem(setup_page, "fritz", "AVM FRITZ!Box")
        # Port 9 (discard) is closed on the test runner, so the real driver fails to connect.
        setup_page.locator("#modem_url").fill("http://127.0.0.1:9")
        with setup_page.expect_response("**/api/test-modem") as response:
            setup_page.locator("#test-conn-btn").click()
        assert response.value.json()["reason"] == "unreachable"
        expect(setup_page.locator("#test-result")).to_contain_text("DOCSight cannot reach http://127.0.0.1:9.")
