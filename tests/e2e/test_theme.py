"""E2E tests for theme (dark/light) support."""

import pytest


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
