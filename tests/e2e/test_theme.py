"""E2E tests for theme (dark/light) support."""

import pytest
from playwright.sync_api import expect


class TestTheme:
    """Theme attribute on <html> element."""

    def test_default_theme_is_dark(self, demo_page):
        theme = demo_page.locator("html").get_attribute("data-theme")
        assert theme == "dark"

    def test_settings_has_theme_attribute(self, settings_page):
        theme = settings_page.locator("html").get_attribute("data-theme")
        assert theme in ("dark", "light")

    def test_builtin_theme_preview_resolves_alias_tokens(self, settings_page):
        """Previewing canonical theme tokens should update legacy compatibility aliases."""
        settings_page.locator('button[data-section="appearance"]').click()
        card = settings_page.locator('.theme-card[data-theme-id="docsight.theme_amber_terminal"]').first
        card.wait_for()

        for mode in ("dark", "light"):
            settings_page.locator("html").evaluate(
                "(el, mode) => el.setAttribute('data-theme', mode)", mode
            )
            expected = card.evaluate(
                "(el, mode) => JSON.parse(el.getAttribute('data-theme-' + mode))",
                mode,
            )
            card.locator(".theme-preview-btn").click()
            resolved = settings_page.locator("html").evaluate(
                """
                (el) => {
                  const styles = getComputedStyle(el);
                  return {
                    cardBg: styles.getPropertyValue('--card-bg').trim(),
                    textPrimary: styles.getPropertyValue('--text-primary').trim(),
                    textMuted: styles.getPropertyValue('--text-muted').trim(),
                    success: styles.getPropertyValue('--success').trim(),
                    warning: styles.getPropertyValue('--warning').trim(),
                    danger: styles.getPropertyValue('--danger').trim(),
                  };
                }
                """
            )

            assert resolved == {
                "cardBg": expected["--card"],
                "textPrimary": expected["--text"],
                "textMuted": expected["--muted"],
                "success": expected["--good"],
                "warning": expected["--warn"],
                "danger": expected["--crit"],
            }
            settings_page.locator("#theme-preview-overlay button", has_text="Cancel").click()

    def test_login_page_has_theme(self, auth_page, auth_server):
        auth_page.goto(f"{auth_server}/login")
        theme = auth_page.locator("html").get_attribute("data-theme")
        assert theme in ("dark", "light")

    @pytest.mark.parametrize("leave_section", [False, True])
    def test_changing_previews_restores_original_colors(self, settings_page, leave_section):
        settings_page.locator('button[data-section="appearance"]').click()
        root = settings_page.locator("html")
        colors = "el => ['--bg', '--accent', '--text'].map(key => getComputedStyle(el).getPropertyValue(key).trim())"
        original = root.evaluate(colors)

        for theme in ("amber_terminal", "ocean"):
            settings_page.locator(
                f'[data-theme-id="docsight.theme_{theme}"] .theme-preview-btn'
            ).click()
        assert root.evaluate(colors) != original

        if leave_section:
            settings_page.locator('button[data-section="general"]').click()
        else:
            settings_page.locator("#theme-preview-overlay button", has_text="Cancel").click()

        assert root.evaluate(colors) == original
        expect(settings_page.locator("#theme-preview-overlay")).to_be_hidden()

    def test_preview_follows_color_mode_and_cancel_restores_that_mode(self, settings_page):
        settings_page.locator('button[data-section="appearance"]').click()
        root = settings_page.locator("html")
        mode = settings_page.get_by_label("Dark Mode", exact=True)
        toggle = settings_page.locator('label[for="theme-toggle-appearance"]')
        toggle.click()
        background = "el => getComputedStyle(el).getPropertyValue('--bg').trim()"
        original_light = root.evaluate(background)
        toggle.click()
        card = settings_page.locator('[data-theme-id="docsight.theme_amber_terminal"]')
        card.locator(".theme-preview-btn").click()
        toggle.click()

        expected = card.evaluate("el => JSON.parse(el.dataset.themeLight)['--bg']")
        assert root.evaluate(background) == expected
        settings_page.locator("#theme-preview-overlay button", has_text="Cancel").click()
        assert root.evaluate(background) == original_light

        settings_page.reload()
        expect(mode).not_to_be_checked()
        palette = card.locator(".palette-dot").first
        expected_rgb = settings_page.evaluate("color => { const el = document.createElement('span'); el.style.background = color; return el.style.background; }", expected)
        assert palette.evaluate("el => el.style.background") == expected_rgb

    @pytest.mark.parametrize("preview_first", [False, True])
    def test_activate_theme_survives_reload_and_applies_to_dashboard(self, settings_page, live_server, preview_first):
        page = settings_page
        page.locator('button[data-section="appearance"]').click()
        original = page.locator('#theme-gallery .theme-card.active').get_attribute('data-theme-id')
        card = page.locator('[data-theme-id="docsight.theme_ocean"]')
        expected = card.evaluate("el => JSON.parse(el.dataset.themeDark)['--bg']")
        try:
            if preview_first:
                response = page.request.post(f'{live_server}/api/modules/docsight.theme_amber_terminal/enable')
                assert response.ok
                page.reload()
                card.locator('.theme-preview-btn').click()
                preview_font = page.locator('html').evaluate("el => getComputedStyle(el).getPropertyValue('--font-sans').trim()")
                button = page.locator('#preview-apply-btn')
            else:
                button = card.locator('.theme-apply-btn')
            with page.expect_response('**/api/modules/docsight.theme_ocean/enable') as response:
                button.click()
            assert response.value.ok
            expect(card).to_have_class('theme-card glass active')
            expect(page.locator('#theme-preview-overlay')).to_be_hidden()
            if preview_first:
                assert page.locator('html').evaluate("el => getComputedStyle(el).getPropertyValue('--font-sans').trim()") == preview_font
            page.reload()
            expect(page.locator('#theme-gallery .theme-card').first).to_have_attribute('data-theme-id', 'docsight.theme_ocean')
            page.locator('.sidebar-header').click()
            assert page.locator('html').evaluate("el => getComputedStyle(el).getPropertyValue('--bg').trim()") == expected
        finally:
            response = page.request.post(f'{live_server}/api/modules/{original}/enable')
            assert response.ok
