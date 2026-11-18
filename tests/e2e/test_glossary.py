"""E2E tests for in-app glossary tooltips."""

from playwright.sync_api import expect
from tests.e2e.support.navigation import open_view


# The visible popover is one shared element that JS places right after the open hint
POPOVER = '#glossary-popover-overlay'


class TestGlossaryPresence:
    """Verify glossary hint icons are rendered on the dashboard."""

    def test_key_figure_has_glossary_hint(self, demo_page):
        hint = demo_page.locator('#view-dashboard .home-kpi .glossary-hint').first
        expect(hint).to_be_visible()

    def test_glossary_hint_has_info_icon(self, demo_page):
        icon = demo_page.locator('#view-dashboard .home-kpi .glossary-hint svg').first
        expect(icon).to_be_visible()

    def test_multiple_glossary_hints_on_dashboard(self, demo_page):
        hints = demo_page.locator('#view-dashboard .home-kpi .glossary-hint')
        assert hints.count() >= 4, f"Expected at least 4 glossary hints, got {hints.count()}"

    def test_dashboard_docsis_basics_help_is_reachable(self, demo_page):
        hint = demo_page.locator('#view-dashboard .hero-meta-item.glossary-hint', has_text='DOCSIS basics')
        expect(hint).to_be_visible()
        hint.click()
        popover = demo_page.locator(POPOVER)
        expect(popover).to_be_visible()
        text = popover.text_content()
        assert 'Cable internet uses DOCSIS, not DSL' in text
        assert 'not Speedtest/IP throughput or tariff speed' in text
        assert 'shared medium' in text


class TestGlossaryPopover:
    """Verify popover open/close behavior."""

    def test_popover_hidden_by_default(self, demo_page):
        popover = demo_page.locator(POPOVER)
        expect(popover).not_to_be_visible()

    def test_click_opens_popover(self, demo_page):
        hint = demo_page.locator('#view-dashboard .home-kpi .glossary-hint').first
        hint.click()
        expect(demo_page.locator(POPOVER)).to_be_visible()

    def test_popover_has_text_content(self, demo_page):
        hint = demo_page.locator('#view-dashboard .home-kpi .glossary-hint').first
        hint.click()
        popover = demo_page.locator(POPOVER)
        text = popover.text_content()
        assert len(text) > 20, f"Popover text too short: {text}"

    def test_click_outside_closes_popover(self, demo_page):
        hint = demo_page.locator('#view-dashboard .home-kpi .glossary-hint').first
        hint.click()
        popover = demo_page.locator(POPOVER)
        expect(popover).to_be_visible()
        demo_page.locator('body').click(position={"x": 10, "y": 10})
        expect(popover).not_to_be_visible()

    def test_escape_closes_popover(self, demo_page):
        hint = demo_page.locator('#view-dashboard .home-kpi .glossary-hint').first
        hint.click()
        popover = demo_page.locator(POPOVER)
        expect(popover).to_be_visible()
        demo_page.keyboard.press("Escape")
        expect(popover).not_to_be_visible()

    def test_clicking_second_hint_closes_first(self, demo_page):
        hints = demo_page.locator('#view-dashboard .home-kpi .glossary-hint')
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
        open_view(demo_page, "channels")
        hint = demo_page.locator('#view-channels .docsis-group-header .glossary-hint').first
        expect(hint).to_be_visible()

    def test_channel_glossary_popover_works(self, demo_page):
        open_view(demo_page, "channels")
        hint = demo_page.locator('#view-channels .docsis-group-header .glossary-hint').first
        hint.click()
        popover = demo_page.locator(POPOVER)
        expect(popover).to_be_visible()
        text = popover.text_content()
        assert len(text) > 20


class TestGlossaryModulation:
    """Verify glossary hints on modulation KPI cards."""

    def test_modulation_kpi_has_glossary_hints(self, demo_page):
        open_view(demo_page, "modulation")
        demo_page.wait_for_timeout(2000)
        hints = demo_page.locator('#view-modulation .glossary-hint')
        assert hints.count() >= 4, f"Expected at least 4 modulation glossary hints, got {hints.count()}"

    def test_modulation_capacity_docsis_basics_help_is_reachable(self, demo_page):
        open_view(demo_page, "modulation")
        demo_page.locator('#modulation-capacity-panel').wait_for(state='visible')
        hint = demo_page.locator('#modulation-capacity-panel .mod-capacity-basics-hint')
        expect(hint).to_be_visible()
        hint.click()
        popover = demo_page.locator(POPOVER)
        expect(popover).to_be_visible()
        text = popover.text_content()
        assert 'Cable internet uses DOCSIS, not DSL' in text
        assert 'not Speedtest/IP throughput or tariff speed' in text

    def test_health_index_popover(self, demo_page):
        open_view(demo_page, "modulation")
        demo_page.wait_for_timeout(2000)
        hint = demo_page.locator('#view-modulation .glossary-hint').first
        hint.click()
        expect(demo_page.locator(POPOVER)).to_be_visible()


class TestGlossaryHintAccessibility:
    """Icon hints have a short name, read their explanation once and keep focus nearby."""

    def test_icon_hint_has_a_short_name_and_its_explanation_as_description(self, demo_page):
        hint = demo_page.locator('#view-dashboard .home-kpi .glossary-hint').first
        names = hint.evaluate("""el => ({
            label: el.getAttribute('aria-label'),
            description: document.getElementById(el.getAttribute('aria-describedby')).textContent.trim(),
            explanation: el.querySelector('.glossary-popover').textContent.trim(),
        })""")
        assert names["label"] == "Explanation"
        assert names["description"] == names["explanation"] and len(names["explanation"]) > 20
        hint.click()
        assert hint.get_attribute("aria-describedby") != "glossary-popover-overlay"

    def test_tab_moves_into_the_popover_and_escape_returns_to_the_hint(self, demo_page):
        hint = demo_page.locator('#view-dashboard .home-kpi .glossary-hint[data-glossary-term-id]').first
        hint.focus()
        popover = demo_page.locator(POPOVER)
        expect(popover).to_be_visible()
        assert hint.evaluate("el => el.nextElementSibling.id") == "glossary-popover-overlay"
        demo_page.keyboard.press("Tab")
        assert demo_page.evaluate("document.activeElement.classList.contains('glossary-popover-link')")
        demo_page.keyboard.press("Escape")
        expect(popover).not_to_be_visible()
        assert hint.evaluate("el => el === document.activeElement")


    def test_dashboard_header_items_explain_themselves_without_a_mouse(self, demo_page):
        title_only = demo_page.evaluate("""() => Array.from(document.querySelectorAll('#view-dashboard .hero-meta-hint'))
            .filter(el => !el.classList.contains('glossary-hint') || !el.querySelector('.glossary-popover'))
            .map(el => el.textContent.trim())""")
        assert title_only == []
        isp = demo_page.locator('#view-dashboard .hero-meta-hint.glossary-hint').first
        isp.focus()
        expect(demo_page.locator(POPOVER)).to_be_visible()
        assert isp.get_attribute("aria-label") is None

    def test_capacity_column_explains_the_estimate(self, demo_page):
        demo_page.goto(demo_page.url.split('#')[0] + '#channels', wait_until='networkidle')
        demo_page.evaluate("document.querySelectorAll('#channel-current-values .docsis-group').forEach(g => g.classList.add('open'))")
        hint = demo_page.locator('#channel-current-values th .glossary-hint').first
        hint.click()
        expect(demo_page.locator(POPOVER)).to_contain_text('not usable IP throughput')
        assert demo_page.locator('#channel-current-values [title*="not usable IP throughput"]').count() == 0
