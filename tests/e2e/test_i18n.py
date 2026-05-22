"""E2E tests for internationalization (language switching)."""

import pytest

EUROPEAN_LANGUAGE_PACK = {
    "bg", "cs", "da", "de", "el", "en", "es", "et", "fi", "fr",
    "ga", "hr", "hu", "it", "lt", "lv", "nb", "nl", "pl", "pt",
    "ro", "sk", "sl", "sv",
}


class TestLanguageSwitching:
    """Language can be switched via ?lang= query parameter."""

    def test_default_language_is_english(self, demo_page):
        lang = demo_page.locator("html").get_attribute("lang")
        assert lang == "en"

    def test_switch_to_german(self, page, live_server):
        page.goto(f"{live_server}/?lang=de")
        page.wait_for_load_state("networkidle")
        lang = page.locator("html").get_attribute("lang")
        assert lang == "de"

    def test_switch_to_french(self, page, live_server):
        page.goto(f"{live_server}/?lang=fr")
        page.wait_for_load_state("networkidle")
        lang = page.locator("html").get_attribute("lang")
        assert lang == "fr"

    def test_switch_to_spanish(self, page, live_server):
        page.goto(f"{live_server}/?lang=es")
        page.wait_for_load_state("networkidle")
        lang = page.locator("html").get_attribute("lang")
        assert lang == "es"

    def test_settings_respects_lang_param(self, page, live_server):
        page.goto(f"{live_server}/settings?lang=de")
        page.wait_for_load_state("networkidle")
        lang = page.locator("html").get_attribute("lang")
        assert lang == "de"

    def test_switch_to_new_european_language(self, page, live_server):
        page.goto(f"{live_server}/?lang=it")
        page.wait_for_load_state("networkidle")
        lang = page.locator("html").get_attribute("lang")
        assert lang == "it"

    def test_settings_language_selector_lists_european_pack(self, page, live_server):
        page.goto(f"{live_server}/settings?lang=pl")
        page.wait_for_load_state("networkidle")
        page.evaluate("switchSection('general')")
        values = page.locator("#language option").evaluate_all("opts => opts.map(o => o.value)")
        assert set(values) == EUROPEAN_LANGUAGE_PACK

    @pytest.mark.parametrize("width,height", [(1280, 900), (390, 844)])
    def test_settings_language_selector_does_not_overflow_viewport(self, page, live_server, width, height):
        page.set_viewport_size({"width": width, "height": height})
        page.goto(f"{live_server}/settings?lang=nb")
        page.wait_for_load_state("networkidle")
        page.evaluate("switchSection('general')")
        page.locator("#language").scroll_into_view_if_needed()
        metrics = page.evaluate(
            """() => ({
                viewport: window.innerWidth,
                doc: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
                selectorRight: document.querySelector('#language').getBoundingClientRect().right,
            })"""
        )
        assert metrics["doc"] <= metrics["viewport"]
        assert metrics["selectorRight"] <= metrics["viewport"]
