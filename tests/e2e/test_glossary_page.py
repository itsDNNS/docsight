"""E2E tests for the in-app glossary view."""

import re

from playwright.sync_api import expect


def _assert_visible_boxes_do_not_overlap(page, selector):
    boxes = page.locator(selector).evaluate_all(
        """nodes => nodes
            .filter(node => {
              const style = window.getComputedStyle(node);
              const rect = node.getBoundingClientRect();
              return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
            })
            .map((node, index) => {
              const rect = node.getBoundingClientRect();
              return { index, left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom };
            })"""
    )
    for i, first in enumerate(boxes):
        for second in boxes[i + 1:]:
            overlaps = not (
                first["right"] <= second["left"]
                or second["right"] <= first["left"]
                or first["bottom"] <= second["top"]
                or second["bottom"] <= first["top"]
            )
            assert not overlaps, f"{selector} boxes overlap: {first} vs {second}"


def _active_article(page):
    return page.locator("#view-glossary .glossary-term-article:not([hidden])")


def test_glossary_app_view_renders_inside_shell(page, live_server):
    page.goto(f"{live_server}/?lang=en&term=docsis#glossary?term=docsis")
    page.wait_for_selector("#view-glossary.active", state="visible")

    expect(page.locator(".sidebar")).to_be_visible()
    expect(page.locator('.nav-item[data-view="glossary"]')).to_have_class(re.compile(r"active"))
    expect(page.locator("#view-glossary .view-page-title", has_text="Glossary")).to_be_visible()
    expect(_active_article(page).locator(".glossary-term-header-card h3", has_text="DOCSIS")).to_be_visible()
    expect(_active_article(page).locator(".glossary-summary-card", has_text="Quick summary")).to_be_visible()
    expect(_active_article(page).locator(".glossary-explanation-card", has_text="Explanation")).to_be_visible()
    expect(page.locator(".glossary-index-desktop .glossary-term-link").first).to_have_text("Attenuation")
    _assert_visible_boxes_do_not_overlap(page, "#view-glossary .glossary-term-article:not([hidden]) > .glossary-card")


def test_glossary_term_list_navigation_updates_hash_and_article(page, live_server):
    page.goto(f"{live_server}/?lang=en&term=sc_qam#glossary?term=sc_qam")
    page.wait_for_selector("#view-glossary.active", state="visible")

    expect(_active_article(page).locator(".glossary-explanation-card", has_text="gross Layer-1 capacity")).to_be_visible()

    page.locator(".glossary-index-desktop [data-glossary-term]", has_text="Capacity vs. speedtest").click()
    expect(page).to_have_url(re.compile(r"#glossary\?term=capacity_vs_throughput"))
    expect(_active_article(page).locator(".glossary-term-header-card h3", has_text="Capacity vs. speedtest")).to_be_visible()


def test_glossary_mobile_layout_has_no_horizontal_overflow(page, live_server):
    page.set_viewport_size({"width": 393, "height": 852})
    page.goto(f"{live_server}/?lang=en&term=capacity_vs_throughput#glossary?term=capacity_vs_throughput")
    page.wait_for_selector("#view-glossary.active", state="visible")

    expect(_active_article(page).locator(".glossary-term-header-card h3", has_text="Capacity vs. speedtest")).to_be_visible()
    has_overflow = page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
    assert has_overflow is False
    _assert_visible_boxes_do_not_overlap(page, "#view-glossary .glossary-term-article:not([hidden]) > .glossary-card")


def test_glossary_search_filters_alphabetical_terms(page, live_server):
    page.goto(f"{live_server}/?lang=en&term=docsis#glossary?term=docsis")
    page.wait_for_selector("#view-glossary.active", state="visible")

    search = page.locator("#glossary-search")
    search.fill("CMTS")
    expect(page.locator(".glossary-index-desktop [data-glossary-term]", has_text="CMTS")).to_be_visible()
    expect(page.locator(".glossary-index-desktop [data-search^='Speedtest ']")).to_be_hidden()
    expect(page.locator("#glossary-result-count")).to_contain_text("1 term shown")


def test_glossary_desktop_click_does_not_refocus_closed_mobile_picker(page, live_server):
    page.set_viewport_size({"width": 393, "height": 852})
    page.goto(f"{live_server}/?lang=en&term=docsis#glossary?term=docsis")
    page.wait_for_selector("#view-glossary.active", state="visible")

    page.locator(".glossary-mobile-picker-trigger").click()
    page.keyboard.press("Escape")
    expect(page.locator("#glossary-mobile-picker")).to_be_hidden()

    page.set_viewport_size({"width": 1440, "height": 950})
    page.locator(".glossary-index-desktop [data-glossary-term]", has_text="CMTS").click()

    expect(_active_article(page).locator(".glossary-term-header-card h3", has_text="CMTS")).to_be_visible()
    trigger_has_focus = page.evaluate(
        "document.activeElement === document.querySelector('.glossary-mobile-picker-trigger')"
    )
    assert trigger_has_focus is False


def test_glossary_mobile_uses_picker_instead_of_inline_long_list(page, live_server):
    page.set_viewport_size({"width": 393, "height": 852})
    page.goto(f"{live_server}/?lang=en&term=docsis#glossary?term=docsis")
    page.wait_for_selector("#view-glossary.active", state="visible")

    expect(page.locator(".glossary-index-desktop")).to_be_hidden()
    expect(page.locator(".glossary-mobile-picker-trigger", has_text="Search or change term")).to_be_visible()
    expect(_active_article(page).locator(".glossary-term-header-card h3", has_text="DOCSIS")).to_be_visible()

    page.locator(".glossary-mobile-picker-trigger").click()
    expect(page.locator("#glossary-mobile-picker")).to_be_visible()
    mobile_search = page.locator("#glossary-mobile-search")
    expect(mobile_search).to_be_focused()
    mobile_search.fill("CMTS")
    expect(page.locator("#glossary-mobile-picker [data-glossary-term]", has_text="CMTS")).to_be_visible()
    expect(page.locator("#glossary-mobile-picker [data-search^='Speedtest ']")).to_be_hidden()

    page.keyboard.press("Shift+Tab")
    expect(page.locator(".glossary-mobile-picker-close")).to_be_focused()
    for _ in range(8):
        page.keyboard.press("Tab")
        focus_inside_picker = page.evaluate(
            "document.querySelector('#glossary-mobile-picker').contains(document.activeElement)"
        )
        assert focus_inside_picker is True

    page.keyboard.press("Escape")
    expect(page.locator("#glossary-mobile-picker")).to_be_hidden()
    expect(page.locator(".glossary-mobile-picker-trigger")).to_be_focused()


def test_dashboard_contextual_help_links_to_matching_in_app_glossary_term(page, live_server):
    page.goto(f"{live_server}/?lang=en")
    page.wait_for_load_state("networkidle")

    page.locator(".hero-meta-item.glossary-hint", has_text="DOCSIS basics").click()
    link = page.locator("#glossary-popover-overlay .glossary-popover-link")
    expect(link).to_be_visible()
    expect(link).to_have_attribute("href", re.compile(r"/\?lang=en#glossary\?term=docsis&level=basic"))


def test_dashboard_contextual_glossary_link_is_keyboard_reachable(page, live_server):
    page.goto(f"{live_server}/?lang=en")
    page.wait_for_load_state("networkidle")

    hint = page.locator(".hero-meta-item.glossary-hint", has_text="DOCSIS basics")
    hint.focus()
    page.keyboard.press("Enter")

    link = page.locator("#glossary-popover-overlay .glossary-popover-link")
    expect(link).to_be_visible()
    expect(link).to_be_focused()

    page.keyboard.press("Enter")
    expect(page).to_have_url(re.compile(r"/\?lang=en#glossary\?term=docsis&level=basic"))
    page.wait_for_selector("#view-glossary.active", state="visible")
    expect(_active_article(page).locator(".glossary-term-header-card h3", has_text="DOCSIS")).to_be_visible()
