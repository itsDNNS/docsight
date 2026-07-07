"""E2E tests for the standalone glossary page."""

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


def test_standalone_glossary_page_renders_simple_summary_and_explanation(page, live_server):
    page.goto(f"{live_server}/glossary?lang=en&term=docsis&level=basic")
    page.wait_for_load_state("networkidle")

    expect(page.locator("h1", has_text="Glossary")).to_be_visible()
    expect(page.locator("#glossary-term-title", has_text="DOCSIS")).to_be_visible()
    expect(page.locator("#summary-heading", has_text="Quick summary")).to_be_visible()
    expect(page.locator("#explanation-heading", has_text="Explanation")).to_be_visible()
    expect(page.locator(".glossary-index-desktop .glossary-term-link").first).to_have_text("Attenuation")
    expect(page.locator(".glossary-related", has_text="SC-QAM")).to_be_visible()
    _assert_visible_boxes_do_not_overlap(page, ".glossary-article > .glossary-card, .glossary-meta-grid > .glossary-card")


def test_glossary_related_term_navigation(page, live_server):
    page.goto(f"{live_server}/glossary?lang=en&term=sc_qam&level=basic")
    page.wait_for_load_state("networkidle")

    expect(page.locator("#summary-heading", has_text="Quick summary")).to_be_visible()
    expect(page.locator(".glossary-explanation-card", has_text="gross Layer-1 capacity")).to_be_visible()

    page.locator(".glossary-related a", has_text="Capacity vs. speedtest").click()
    expect(page).to_have_url(re.compile(r"term=capacity_vs_throughput"))
    expect(page.locator("#glossary-term-title", has_text="Capacity vs. speedtest")).to_be_visible()


def test_glossary_mobile_layout_has_no_horizontal_overflow(page, live_server):
    page.set_viewport_size({"width": 393, "height": 852})
    page.goto(f"{live_server}/glossary?lang=en&term=capacity_vs_throughput&level=eli5")
    page.wait_for_load_state("networkidle")

    expect(page.locator("#glossary-term-title", has_text="Capacity vs. speedtest")).to_be_visible()
    has_overflow = page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
    assert has_overflow is False
    _assert_visible_boxes_do_not_overlap(page, ".glossary-article > .glossary-card, .glossary-meta-grid > .glossary-card")


def test_glossary_search_filters_alphabetical_terms(page, live_server):
    page.goto(f"{live_server}/glossary?lang=en&term=docsis&level=basic")
    page.wait_for_load_state("networkidle")

    search = page.locator("#glossary-search")
    search.fill("CMTS")
    expect(page.locator(".glossary-index-desktop [data-glossary-term]", has_text="CMTS")).to_be_visible()
    expect(page.locator(".glossary-index-desktop [data-search^='Speedtest ']")).to_be_hidden()
    expect(page.locator("#glossary-result-count")).to_contain_text("1 term shown")


def test_glossary_mobile_uses_picker_instead_of_inline_long_list(page, live_server):
    page.set_viewport_size({"width": 393, "height": 852})
    page.goto(f"{live_server}/glossary?lang=en&term=docsis&level=basic")
    page.wait_for_load_state("networkidle")

    expect(page.locator(".glossary-index-desktop")).to_be_hidden()
    expect(page.locator(".glossary-mobile-picker-trigger", has_text="Search or change term")).to_be_visible()
    expect(page.locator("#glossary-term-title", has_text="DOCSIS")).to_be_visible()

    page.locator(".glossary-mobile-picker-trigger").click()
    expect(page.locator("#glossary-mobile-picker")).to_be_visible()
    mobile_search = page.locator("#glossary-mobile-search")
    expect(mobile_search).to_be_focused()
    mobile_search.fill("CMTS")
    expect(page.locator("#glossary-mobile-picker [data-glossary-term]", has_text="CMTS")).to_be_visible()
    expect(page.locator("#glossary-mobile-picker [data-search^='Speedtest ']")).to_be_hidden()


def test_dashboard_contextual_help_links_to_matching_glossary_term(page, live_server):
    page.goto(f"{live_server}/?lang=en")
    page.wait_for_load_state("networkidle")

    page.locator(".hero-meta-item.glossary-hint", has_text="DOCSIS basics").click()
    link = page.locator("#glossary-popover-overlay .glossary-popover-link")
    expect(link).to_be_visible()
    expect(link).to_have_attribute("href", re.compile(r"/glossary\?lang=en&term=docsis&level=basic"))


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
    expect(page).to_have_url(re.compile(r"/glossary\?lang=en&term=docsis&level=basic"))
    expect(page.locator("#glossary-term-title", has_text="DOCSIS")).to_be_visible()
