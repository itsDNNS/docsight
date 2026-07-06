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
