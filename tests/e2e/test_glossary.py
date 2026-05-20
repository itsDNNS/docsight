"""E2E tests for in-app glossary tooltips."""

import pytest
from playwright.sync_api import expect


# The visible popover is a body-level overlay (JS moves it out of the hint)
POPOVER = 'body > .glossary-popover'


class TestGlossaryPresence:
    """Verify glossary hint icons are rendered on the dashboard."""

    def test_snr_card_has_glossary_hint(self, demo_page):
        hint = demo_page.locator('#view-dashboard .metric-card .glossary-hint').first
        expect(hint).to_be_visible()

    def test_glossary_hint_has_info_icon(self, demo_page):
        icon = demo_page.locator('#view-dashboard .metric-card .glossary-hint svg').first
        expect(icon).to_be_visible()

    def test_multiple_glossary_hints_on_dashboard(self, demo_page):
        hints = demo_page.locator('#view-dashboard .metric-card .glossary-hint')
        assert hints.count() >= 4, f"Expected at least 4 glossary hints, got {hints.count()}"


class TestGlossaryPopover:
    """Verify popover open/close behavior."""

    def test_popover_hidden_by_default(self, demo_page):
        popover = demo_page.locator(POPOVER)
        expect(popover).not_to_be_visible()

    def test_click_opens_popover(self, demo_page):
        hint = demo_page.locator('#view-dashboard .metric-card .glossary-hint').first
        hint.click()
        expect(demo_page.locator(POPOVER)).to_be_visible()

    def test_popover_has_text_content(self, demo_page):
        hint = demo_page.locator('#view-dashboard .metric-card .glossary-hint').first
        hint.click()
        popover = demo_page.locator(POPOVER)
        text = popover.text_content()
        assert len(text) > 20, f"Popover text too short: {text}"

    def test_click_outside_closes_popover(self, demo_page):
        hint = demo_page.locator('#view-dashboard .metric-card .glossary-hint').first
        hint.click()
        popover = demo_page.locator(POPOVER)
        expect(popover).to_be_visible()
        demo_page.locator('body').click(position={"x": 10, "y": 10})
        expect(popover).not_to_be_visible()

    def test_escape_closes_popover(self, demo_page):
        hint = demo_page.locator('#view-dashboard .metric-card .glossary-hint').first
        hint.click()
        popover = demo_page.locator(POPOVER)
        expect(popover).to_be_visible()
        demo_page.keyboard.press("Escape")
        expect(popover).not_to_be_visible()

    def test_clicking_second_hint_closes_first(self, demo_page):
        hints = demo_page.locator('#view-dashboard .metric-card .glossary-hint')
        first = hints.nth(0)
        second = hints.nth(2)  # skip nth(1) — same glossary_power text as nth(0)
        popover = demo_page.locator(POPOVER)
        first.click()
        expect(popover).to_be_visible()
        first_text = popover.text_content()
        second.click()
        expect(popover).to_be_visible()
        second_text = popover.text_content()
        assert first_text != second_text, "Popover text should change between hints"


class TestGlossaryChannels:
    """Verify glossary hints in channel tables."""

    def test_ds_channel_group_has_glossary_hint(self, demo_page):
        hint = demo_page.locator('#view-dashboard .docsis-group-header .glossary-hint').first
        expect(hint).to_be_visible()

    def test_channel_glossary_popover_works(self, demo_page):
        hint = demo_page.locator('#view-dashboard .docsis-group-header .glossary-hint').first
        hint.click()
        popover = demo_page.locator(POPOVER)
        expect(popover).to_be_visible()
        text = popover.text_content()
        assert len(text) > 20


class TestGlossaryModulation:
    """Verify glossary hints on modulation KPI cards."""

    def test_modulation_kpi_has_glossary_hints(self, demo_page):
        demo_page.locator('.nav-item[data-view="modulation"]').click()
        demo_page.wait_for_timeout(2000)
        hints = demo_page.locator('#view-modulation .glossary-hint')
        assert hints.count() >= 3, f"Expected 3 modulation glossary hints, got {hints.count()}"

    def test_health_index_popover(self, demo_page):
        demo_page.locator('.nav-item[data-view="modulation"]').click()
        demo_page.wait_for_timeout(2000)
        hint = demo_page.locator('#view-modulation .glossary-hint').first
        hint.click()
        expect(demo_page.locator(POPOVER)).to_be_visible()
