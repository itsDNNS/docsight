"""Focused mobile viewport quality gate for high-value DOCSight surfaces."""

from playwright.sync_api import expect

MOBILE_VIEWPORT = {"width": 393, "height": 852}
MAX_HORIZONTAL_OVERFLOW = 1
MIN_TOUCH_TARGET = 44


MAIN_BLADES = [
    ("Home", "live", "#view-dashboard"),
    ("Event Log", "events", "#view-events"),
    ("Channels", "channels", "#view-channels"),
    ("Signal Trends", "trends", "#view-trends"),
    ("Correlation", "correlation", "#view-correlation"),
    ("Connection Monitor", "connection-monitor", "#view-connection-monitor"),
    ("Segment Utilization", "segment-utilization", "#view-segment-utilization"),
    ("Before/After Comparison", "comparison", "#view-comparison"),
    ("Gaming Quality", "gaming", "#view-gaming"),
    ("Modulation Performance", "modulation", "#view-modulation"),
    ("Speedtest", "speedtest", "#view-speedtest"),
    ("BQM", "bqm", "#view-bqm"),
    ("SmokePing", "smokeping", "#view-smokeping"),
    ("BNetzA", "bnetz", "#view-bnetz"),
    ("Incident Journal", "journal", "#view-journal"),
]

MODALS = [
    ("Report evidence builder", "openReportModal()", "#report-modal"),
    ("AI export", "exportForLLM()", "#export-modal"),
    ("Speedtest setup", "openSpeedtestSetupModal()", "#speedtest-setup-modal"),
    ("BQM setup", "openBqmSetupModal()", "#bqm-setup-modal"),
    ("SmokePing setup", "openSmokepingSetupModal()", "#smokeping-setup-modal"),
    ("BQM image import", "openBqmImportModal()", "#bqm-import-modal"),
    ("Journal entry", "openEntryModal()", "#entry-modal"),
    ("Incident container", "openIncidentModal()", "#incident-container-modal"),
    ("Journal import", "openImportModal()", "#import-modal"),
]


def _record_console_error(errors):
    def _handler(msg):
        if msg.type != "error":
            return
        # Chromium reports failed image/network resources as console errors without a
        # stable URL in the message. The gate tracks JavaScript/page errors as
        # blockers and lets surface geometry assertions catch visible breakage.
        if msg.text.startswith("Failed to load resource:"):
            return
        errors.append(msg.text)
    return _handler


def _assert_no_browser_errors(page, console_errors, page_errors, surface):
    assert console_errors == [], f"{surface} console errors: {console_errors}"
    assert page_errors == [], f"{surface} page errors: {page_errors}"


def _assert_no_horizontal_overflow(page, surface, root_selector=None):
    geometry = page.evaluate(
        """
        (selector) => {
            const root = selector ? document.querySelector(selector) : document.documentElement;
            const activeView = document.querySelector('.view.active');
            return {
                documentOverflow: document.documentElement.scrollWidth - window.innerWidth,
                bodyOverflow: document.body.scrollWidth - window.innerWidth,
                rootOverflow: root ? root.scrollWidth - root.clientWidth : 0,
                activeViewOverflow: activeView ? activeView.scrollWidth - activeView.clientWidth : 0,
            };
        }
        """,
        root_selector,
    )
    offenders = {key: value for key, value in geometry.items() if value > MAX_HORIZONTAL_OVERFLOW}
    assert offenders == {}, f"{surface} horizontal overflow: {offenders}"


def _assert_visible_controls_stay_in_view(page, surface, root_selector):
    controls = page.locator(
        f"{root_selector} button, {root_selector} a[href], {root_selector} input, "
        f"{root_selector} select, {root_selector} textarea, {root_selector} [role='button']"
    ).evaluate_all(
        """
        (nodes) => nodes.map((node) => {
            const rect = node.getBoundingClientRect();
            const style = getComputedStyle(node);
            return {
                text: (node.textContent || node.getAttribute('aria-label') || node.id || node.className || node.tagName).trim(),
                left: rect.left,
                right: rect.right,
                width: rect.width,
                height: rect.height,
                visible: style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0,
                viewportWidth: window.innerWidth,
            };
        }).filter((item) => item.visible)
        """
    )
    offscreen = [
        control for control in controls
        if control["left"] < -MAX_HORIZONTAL_OVERFLOW
        or control["right"] > control["viewportWidth"] + MAX_HORIZONTAL_OVERFLOW
    ]
    assert offscreen == [], f"{surface} off-screen controls: {offscreen}"


def _assert_touch_targets(page, surface, selector):
    targets = page.locator(selector).evaluate_all(
        """
        (nodes) => nodes.map((node) => {
            const rect = node.getBoundingClientRect();
            const style = getComputedStyle(node);
            return {
                text: (node.textContent || node.getAttribute('aria-label') || node.id || node.className || node.tagName).trim(),
                width: rect.width,
                height: rect.height,
                left: rect.left,
                right: rect.right,
                visible: style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0,
                bottom: rect.bottom,
                viewportWidth: window.innerWidth,
                viewportHeight: window.innerHeight,
            };
        }).filter((item) => item.visible)
        """
    )
    assert targets, f"{surface} expected visible touch targets for {selector}"
    too_small = [target for target in targets if target["width"] < MIN_TOUCH_TARGET or target["height"] < MIN_TOUCH_TARGET]
    offscreen = [
        target for target in targets
        if target["left"] < -MAX_HORIZONTAL_OVERFLOW
        or target["right"] > target["viewportWidth"] + MAX_HORIZONTAL_OVERFLOW
        or target["bottom"] > target["viewportHeight"] + MAX_HORIZONTAL_OVERFLOW
    ]
    assert too_small == [], f"{surface} small touch targets: {too_small}"
    assert offscreen == [], f"{surface} off-screen touch targets: {offscreen}"


def _close_modal(page, selector):
    page.keyboard.press("Escape")
    expect(page.locator(selector)).not_to_be_visible()


def test_mobile_main_blades_have_no_overflow_or_offscreen_controls(demo_page):
    """Main mobile blades should fit a modern phone viewport without hidden horizontal controls."""
    page = demo_page
    page.set_viewport_size(MOBILE_VIEWPORT)
    console_errors = []
    page_errors = []
    page.on("console", _record_console_error(console_errors))
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))
    page.reload()
    page.wait_for_load_state("networkidle")

    for label, view, selector in MAIN_BLADES:
        if page.locator(f'.nav-item[data-view="{view}"]').count() == 0:
            continue
        page.evaluate("view => switchView(view)", view)
        page.wait_for_selector(f"{selector}.active", state="visible")
        _assert_no_browser_errors(page, console_errors, page_errors, label)
        _assert_no_horizontal_overflow(page, label, selector)
        _assert_visible_controls_stay_in_view(page, label, selector)


def test_mobile_navigation_and_high_value_modals_pass_quality_gate(demo_page):
    """Mobile nav and key modals should expose controls without footer overlap or off-screen targets."""
    page = demo_page
    page.set_viewport_size(MOBILE_VIEWPORT)
    console_errors = []
    page_errors = []
    page.on("console", _record_console_error(console_errors))
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))
    page.reload()
    page.wait_for_load_state("networkidle")

    sidebar = page.locator("#sidebar")
    hamburger = page.locator("#hamburger")
    expect(sidebar).to_have_attribute("aria-hidden", "true")
    hidden_focus_targets = page.evaluate(
        """
        () => Array.from(document.querySelectorAll(
            '#sidebar a[href], #sidebar button, #sidebar input, #sidebar [role="button"], #sidebar [tabindex]'
        )).filter((el) => !el.disabled && el.getAttribute('tabindex') !== '-1')
          .map((el) => el.textContent.trim() || el.id || el.getAttribute('data-view'))
        """
    )
    assert hidden_focus_targets == []
    hamburger.focus()
    hamburger.click()
    page.wait_for_timeout(300)
    expect(sidebar).to_have_attribute("aria-hidden", "false")
    _assert_visible_controls_stay_in_view(page, "open mobile navigation", "#sidebar")
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    expect(sidebar).to_have_attribute("aria-hidden", "true")
    assert page.evaluate("document.activeElement && document.activeElement.id") == "hamburger"

    page.evaluate("switchView('journal')")
    page.wait_for_selector("#view-journal.active", state="visible")
    for label, opener, selector in MODALS:
        if page.locator(selector).count() == 0:
            continue
        page.evaluate(opener)
        modal = page.locator(selector)
        expect(modal).to_be_visible()
        page.wait_for_timeout(100)
        if modal.locator(".modal-body").count() > 0:
            modal.locator(".modal-body").evaluate("el => { el.scrollTop = el.scrollHeight; }")
            body_height = modal.locator(".modal-body").evaluate("el => el.getBoundingClientRect().height")
            body_scroll_height = modal.locator(".modal-body").evaluate("el => el.scrollHeight")
            if body_scroll_height > 0:
                assert body_height >= 96, f"{label} modal body is crowded by surrounding content"
        _assert_no_browser_errors(page, console_errors, page_errors, label)
        _assert_no_horizontal_overflow(page, label, selector)
        _assert_visible_controls_stay_in_view(page, label, selector)
        _assert_touch_targets(page, label, f"{selector} .modal-close, {selector} .modal-footer .btn")
        if modal.locator(".setup-guide-card:last-child").count() > 0:
            spacing = modal.evaluate(
                """
                (el) => {
                    const footer = el.querySelector('.modal-footer');
                    const body = el.querySelector('.modal-body');
                    const last = body.querySelector('.setup-guide-card:last-child');
                    return {
                        lastBottom: last.getBoundingClientRect().bottom,
                        bodyBottom: body.getBoundingClientRect().bottom,
                        footerTop: footer.getBoundingClientRect().top,
                    };
                }
                """
            )
            assert spacing["lastBottom"] <= spacing["footerTop"] - 8, f"{label} footer covers content"
            assert spacing["bodyBottom"] <= spacing["footerTop"] - 8, f"{label} body overlaps footer"
        _close_modal(page, selector)
