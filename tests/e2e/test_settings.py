"""E2E tests for the settings page."""

import re

import pytest
from playwright.sync_api import expect


class TestSettingsLoad:
    """Settings page loads correctly."""

    def test_page_title(self, settings_page):
        assert "DOCSight" in settings_page.title()
        assert "Settings" in settings_page.title() or "Einstellungen" in settings_page.title()

    def test_sidebar_visible(self, settings_page):
        sidebar = settings_page.locator("#settings-sidebar")
        assert sidebar.is_visible()

    def test_connection_tab_active(self, settings_page):
        btn = settings_page.locator('button[data-section="connection"]')
        assert "active" in btn.get_attribute("class")


class TestSettingsTabSwitching:
    """Clicking sidebar tabs shows the correct panel."""

    @pytest.mark.parametrize("section", [
        "general",
        "security",
        "appearance",
        "notifications",
        "extensions",
    ])
    def test_switch_to_section(self, settings_page, section):
        btn = settings_page.locator(f'button[data-section="{section}"]')
        btn.click()
        panel = settings_page.locator(f'#panel-{section}, [id="panel-{section}"]')
        assert panel.is_visible()

    def test_switch_back_to_connection(self, settings_page):
        settings_page.locator('button[data-section="general"]').click()
        settings_page.locator('button[data-section="connection"]').click()
        panel = settings_page.locator("#panel-connection")
        assert panel.is_visible()


class TestSettingsFormElements:
    """Form elements exist on settings panels."""

    def test_connection_has_modem_type_select(self, settings_page):
        select = settings_page.locator('select[name="modem_type"], #modem_type, #modem-type')
        assert select.count() > 0

    def test_security_has_password_field(self, settings_page):
        settings_page.locator('button[data-section="security"]').click()
        pw = settings_page.locator('input[type="password"]')
        assert pw.count() > 0

    def test_back_to_dashboard_link(self, settings_page):
        link = settings_page.locator('a[href="/"]')
        assert link.count() > 0


class TestSettingsDirtyState:
    """Unsaved-change prompts only appear for deliberate settings edits."""

    def test_saved_secret_user_edit_guard_requires_active_field(self, settings_page):
        result = settings_page.evaluate(
            """
            () => {
              const input = document.querySelector('#modem_password');
              input.dataset.savedSecret = 'true';
              const inactive = window._shouldTreatSavedSecretEventAsUserEdit({
                target: input,
                isTrusted: true,
              });
              input.focus();
              const active = window._shouldTreatSavedSecretEventAsUserEdit({
                target: input,
                isTrusted: true,
              });
              const untrusted = window._shouldTreatSavedSecretEventAsUserEdit({
                target: input,
                isTrusted: false,
              });
              return {inactive, active, untrusted};
            }
            """
        )

        assert result == {"inactive": False, "active": True, "untrusted": False}

    def test_modem_password_autofill_does_not_show_unsaved_footer(self, settings_page):
        footer = settings_page.locator("#save-footer")
        expect(footer).not_to_have_class(re.compile(r".*\bvisible\b.*"))

        settings_page.evaluate(
            """
            () => {
              const input = document.querySelector('#modem_password');
              input.dataset.savedSecret = 'true';
              input.setAttribute('placeholder', 'Gespeichert');
              input.value = 'autofilled-password';
              input.dispatchEvent(new Event('input', {bubbles: true}));
              input.dispatchEvent(new Event('change', {bubbles: true}));
            }
            """
        )

        expect(footer).not_to_have_class(re.compile(r".*\bvisible\b.*"))
        expect(footer).to_have_attribute("aria-hidden", "true")
        expect(footer).to_have_attribute("inert", "")
        settings_page.locator('button[data-section="extensions"]').click()
        expect(footer).not_to_have_class(re.compile(r".*\bvisible\b.*"))

    def test_autofilled_saved_secret_is_masked_when_unrelated_setting_is_saved(self, settings_page):
        payloads = []

        def capture_config(route):
            payloads.append(route.request.post_data_json)
            route.fulfill(json={"success": True})

        settings_page.route("**/api/config", capture_config)
        settings_page.evaluate(
            """
            () => {
              const input = document.querySelector('#modem_password');
              input.dataset.savedSecret = 'true';
              input.setAttribute('placeholder', 'Gespeichert');
              input.value = 'autofilled-password';
              input.dispatchEvent(new Event('input', {bubbles: true}));
              input.dispatchEvent(new Event('change', {bubbles: true}));
            }
            """
        )
        settings_page.locator('#modem_url').fill('http://192.168.100.1')

        settings_page.locator('#save-footer button[type="submit"]').click()
        expect(settings_page.locator("#save-footer")).not_to_have_class(re.compile(r".*\bvisible\b.*"))

        assert payloads[-1]["modem_password"] == "••••••••"

    def test_user_edited_saved_secret_is_submitted_and_cleared_after_save(self, settings_page):
        payloads = []

        def capture_config(route):
            payloads.append(route.request.post_data_json)
            route.fulfill(json={"success": True})

        settings_page.route("**/api/config", capture_config)
        settings_page.evaluate(
            """
            () => {
              const input = document.querySelector('#modem_password');
              input.dataset.savedSecret = 'true';
              input.setAttribute('placeholder', 'Gespeichert');
            }
            """
        )

        settings_page.locator('#modem_password').fill('new-secret-value')
        settings_page.locator('#save-footer button[type="submit"]').click()
        expect(settings_page.locator("#save-footer")).not_to_have_class(re.compile(r".*\bvisible\b.*"))

        assert payloads[-1]["modem_password"] == "new-secret-value"
        assert settings_page.locator('#modem_password').input_value() == ""

    def test_real_settings_edit_shows_only_footer_when_module_toggle_is_clicked(self, settings_page):
        footer = settings_page.locator("#save-footer")
        settings_page.locator('#modem_url').fill('http://192.168.100.1')
        expect(footer).to_have_class(re.compile(r".*\bvisible\b.*"))
        expect(footer).not_to_have_attribute("aria-hidden", "true")
        expect(footer).not_to_have_attribute("inert", "")

        settings_page.locator('button[data-section="extensions"]').click()
        toggle = settings_page.locator('.module-toggle-input').first
        assert toggle.count() == 1
        settings_page.locator('.module-toggle .toggle-slider').first.click()

        expect(settings_page.locator('#docsight-confirm-modal')).to_have_count(0)
        expect(footer).to_have_class(re.compile(r".*\bvisible\b.*"))


class TestSettingsExtensionsBatchSave:
    """Installed module changes are saved with the Settings save flow."""

    def test_module_toggles_batch_save_once_without_immediate_api_calls(self, settings_page):
        config_payloads = []
        batch_payloads = []
        immediate_calls = []

        def capture_config(route):
            config_payloads.append(route.request.post_data_json)
            route.fulfill(json={"success": True})

        def capture_batch(route):
            batch_payloads.append(route.request.post_data_json)
            route.fulfill(json={"success": True, "restart_required": True})

        def capture_immediate(route):
            immediate_calls.append(route.request.url)
            route.fulfill(status=500, json={"success": False})

        settings_page.route("**/api/config", capture_config)
        settings_page.route("**/api/modules/batch", capture_batch)
        settings_page.route(re.compile(r".*/api/modules/.+/(enable|disable)$"), capture_immediate)

        settings_page.locator('button[data-section="extensions"]').click()
        toggles = settings_page.locator('.module-toggle-input[data-is-threshold="false"]')
        assert toggles.count() >= 2
        settings_page.locator('.module-toggle-input[data-is-threshold="false"] + .toggle-slider').nth(0).click()
        settings_page.locator('.module-toggle-input[data-is-threshold="false"] + .toggle-slider').nth(1).click()

        footer = settings_page.locator("#save-footer")
        expect(footer).to_have_class(re.compile(r".*\bvisible\b.*"))
        settings_page.locator('#save-footer button[type="submit"]').click()

        expect(footer).not_to_have_class(re.compile(r".*\bvisible\b.*"))
        expect(settings_page.locator("#module-restart-banner")).to_be_visible()
        assert len(config_payloads) == 1
        assert len(batch_payloads) == 1
        assert len(batch_payloads[0]["modules"]) == 2
        assert immediate_calls == []

    def test_threshold_profile_toggles_are_exclusive_radios(self, settings_page):
        settings_page.locator('button[data-section="extensions"]').click()
        threshold_toggles = settings_page.locator('.module-toggle-input[data-is-threshold="true"]')
        assert threshold_toggles.count() >= 1
        assert threshold_toggles.first.get_attribute("type") == "radio"
        assert threshold_toggles.first.get_attribute("name") == "threshold_profile_module"
        assert threshold_toggles.first.get_attribute("aria-labelledby")
        assert threshold_toggles.first.get_attribute("aria-describedby")
        expect(settings_page.locator('[role="group"][aria-labelledby="extensions-modules-heading"]')).to_be_visible()


class TestSpeedtestModule:
    """Speedtest module settings interactions."""

    def test_speedtest_section_shows_test_button(self, settings_page):
        settings_page.locator('button[data-section="mod-docsight_speedtest"]').click()

        button = settings_page.get_by_role("button", name="Test Connection")
        assert button.is_visible()

    def test_speedtest_test_connection_success(self, settings_page):
        settings_page.route(
            "**/api/test-speedtest",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body="""
                {
                  "success": true,
                  "results": 1,
                  "latest": {
                    "download": "120.50 Mbps",
                    "upload": "24.10 Mbps",
                    "ping": "11.4 ms"
                  }
                }
                """,
            ),
        )

        settings_page.locator('button[data-section="mod-docsight_speedtest"]').click()
        settings_page.get_by_role("button", name="Test Connection").click()

        result = settings_page.locator("#speedtest-test")
        expect(result).to_be_visible()
        expect(result).to_contain_text("Connected")
        expect(result).to_contain_text("120.50 Mbps")
        expect(result).to_contain_text("24.10 Mbps")
        expect(result).to_contain_text("11.4 ms")

    def test_speedtest_test_connection_error(self, settings_page):
        settings_page.route(
            "**/api/test-speedtest",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body='{"success": false, "error": "HTTP 401"}',
            ),
        )

        settings_page.locator('button[data-section="mod-docsight_speedtest"]').click()
        settings_page.get_by_role("button", name="Test Connection").click()

        result = settings_page.locator("#speedtest-test")
        expect(result).to_be_visible()
        expect(result).to_contain_text("Error")
        expect(result).to_contain_text("HTTP 401")


class TestBackupModule:
    """Backup module settings interactions."""

    def test_backup_section_loads_existing_backups(self, settings_page):
        settings_page.route(
            "**/api/backup/list",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body="""
                [
                  {
                    "filename": "docsight_backup_2026-03-14_120000.tar.gz",
                    "size": 3145728,
                    "modified": "2026-03-14T12:00:00"
                  }
                ]
                """,
            ),
        )

        settings_page.locator('button[data-section="mod-docsight_backup"]').click()

        backup_list = settings_page.locator("#backup-list")
        assert backup_list.locator("code").first.text_content() == "docsight_backup_2026-03-14_120000.tar.gz"
        assert backup_list.get_by_text("3.0 MB").count() > 0
