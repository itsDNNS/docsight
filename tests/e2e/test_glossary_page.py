"""E2E tests for the standalone glossary page."""

import re

from playwright.sync_api import expect


def test_standalone_glossary_page_renders_terms_and_levels(page, live_server):
    page.goto(f"{live_server}/glossary?lang=en&term=docsis&level=basic")
    page.wait_for_load_state("networkidle")

    expect(page.locator("h1", has_text="Glossary")).to_be_visible()
    expect(page.locator("#glossary-term-title", has_text="DOCSIS")).to_be_visible()
    expect(page.locator(".glossary-level", has_text="ELI5")).to_be_visible()
    expect(page.locator(".glossary-level", has_text="Technician")).to_be_visible()
    expect(page.locator(".glossary-index", has_text="Cable/DOCSIS basics")).to_be_visible()
    expect(page.locator(".glossary-related", has_text="SC-QAM")).to_be_visible()


def test_glossary_level_and_related_term_navigation(page, live_server):
    page.goto(f"{live_server}/glossary?lang=en&term=sc_qam&level=basic")
    page.wait_for_load_state("networkidle")

    page.locator(".glossary-level", has_text="Technician").click()
    expect(page).to_have_url(re.compile(r"level=technician"))
    expect(page.locator("#selected-level-heading", has_text="Technician")).to_be_visible()
    expect(page.locator(".glossary-level-panel", has_text="gross Layer-1 estimates")).to_be_visible()

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


def test_glossary_search_and_category_filter(page, live_server):
    page.goto(f"{live_server}/glossary?lang=en&term=docsis&level=basic")
    page.wait_for_load_state("networkidle")

    search = page.locator("#glossary-search")
    search.fill("CMTS")
    expect(page.locator("[data-glossary-term]", has_text="CMTS")).to_be_visible()
    expect(page.locator("[data-glossary-term][data-search^='Speedtest ']")).to_be_hidden()
    expect(page.locator("#glossary-result-count")).to_contain_text("1 term shown")

    search.fill("")
    page.locator("[data-category-filter='signal_quality']").click()
    expect(page.locator("[data-glossary-term]", has_text="Power level")).to_be_visible()
    expect(page.locator("[data-glossary-term]", has_text="CMTS")).to_be_hidden()
    expect(page.locator("[data-category-filter='signal_quality']")).to_have_attribute("aria-pressed", "true")


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
